# -*- Mode: Python; test-case-name:morituri.test.test_program_cdrdao -*-
# vi:si:et:sw=4:sts=4:ts=4

# Morituri - for those about to RIP

# Copyright (C) 2009 Thomas Vander Stichele

# This file is part of morituri.
#
# morituri is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# morituri is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with morituri.  If not, see <http://www.gnu.org/licenses/>.


import re
import os
import tempfile
import platform

from morituri.common import log, common
from morituri.image import toc, table
from morituri.common import task as ctask

from morituri.extern.task import task


class ProgramError(Exception):
    """
    The program had a fatal error.
    """

    def __init__(self, errorMessage):
        self.args = (errorMessage, )
        self.errorMessage = errorMessage

states = ['START', 'TRACK', 'LEADOUT', 'DONE']

_VERSION_RE = re.compile(r'^Cdrdao version (?P<version>.*) - \(C\)')

_ANALYZING_RE = re.compile(r'^Analyzing track (?P<track>\d+).*')

_TRACK_RE = re.compile(r"""
    ^(?P<track>[\d\s]{2})\s+ # Track
    (?P<mode>\w+)\s+         # Mode; AUDIO
    \d\s+                    # Flags
    \d\d:\d\d:\d\d           # Start in HH:MM:FF
    \((?P<start>.+)\)\s+     # Start in frames
    \d\d:\d\d:\d\d           # Length in HH:MM:FF
    \((?P<length>.+)\)       # Length in frames
""", re.VERBOSE)

_LEADOUT_RE = re.compile(r"""
    ^Leadout\s
    \w+\s+               # Mode
    \d\s+                # Flags
    \d\d:\d\d:\d\d       # Start in HH:MM:FF
    \((?P<start>.+)\)    # Start in frames
""", re.VERBOSE)

_POSITION_RE = re.compile(r"""
    ^(?P<hh>\d\d):       # HH
    (?P<mm>\d\d):        # MM
    (?P<ss>\d\d)         # SS
""", re.VERBOSE)

_ERROR_RE = re.compile(r"""^ERROR: (?P<error>.*)""")

# cdrdao give "ObtainExclusiveAccess failed" error on Mac OS X (Darwin) if CD is not dismounted.
# Unfortunately Mac OS automounts CD after every CD operation on cdrdao, so it can easily happen.
_EXCLUSIVE_RE = re.compile(r"""^ERROR: init: (?P<error>ObtainExclusiveAccess failed):""")

class LineParser(object, log.Loggable):
    """
    Parse incoming bytes into lines
    Calls 'parse' on owner for each parsed line.
    """

    def __init__(self, owner):
        self._buffer = ""     # accumulate characters
        self._lines = []      # accumulate lines
        self._owner = owner

    def read(self, bytes):
        self.log('received %d bytes', len(bytes))
        self._buffer += bytes

        # parse buffer into lines if possible, and parse them
        if "\n" in self._buffer:
            self.log('buffer has newline, splitting')
            lines = self._buffer.split('\n')
            if lines[-1] != "\n":
                # last line didn't end yet
                self.log('last line still in progress')
                self._buffer = lines[-1]
                del lines[-1]
            else:
                self.log('last line finished, resetting buffer')
                self._buffer = ""

            for line in lines:
                self.log('Parsing %s', line)
                self._owner.parse(line)

            self._lines.extend(lines)


class OutputParser(object, log.Loggable):

    def __init__(self, taskk, session=None):
        self._buffer = ""     # accumulate characters
        self._lines = []      # accumulate lines
        self._state = 'START'
        self._frames = None   # number of frames
        self.track = 0        # which track are we analyzing?
        self._task = taskk
        self.tracks = 0      # count of tracks, relative to session
        self._session = session


        self.table = table.Table() # the index table for the TOC
        self.version = None # cdrdao version

    def read(self, bytes):
        self.log('received %d bytes in state %s', len(bytes), self._state)
        self._buffer += bytes

        # find counter in LEADOUT state; only when we read full toc
        self.log('state: %s, buffer bytes: %d', self._state, len(self._buffer))
        if self._buffer and self._state == 'LEADOUT':
            # split on lines that end in \r, which reset cursor to counter
            # start
            # this misses the first one, but that's ok:
            # length 03:40:71...\n00:01:00
            times = self._buffer.split('\r')
            # counter ends in \r, so the last one would be empty
            if not times[-1]:
                del times[-1]

            position = ""
            m = None
            while times and not m:
                position = times.pop()
                m = _POSITION_RE.search(position)

            # we need both a position reported and an Analyzing line
            # to have been parsed to report progress
            if m and self.track is not None:
                track = self.table.tracks[self.track - 1]
                frame = (track.getIndex(1).absolute or 0) \
                    + int(m.group('hh')) * 60 * common.FRAMES_PER_SECOND \
                    + int(m.group('mm')) * common.FRAMES_PER_SECOND \
                    + int(m.group('ss'))
                self.log('at frame %d of %d', frame, self._frames)
                self._task.setProgress(float(frame) / self._frames)

        # parse buffer into lines if possible, and parse them
        if "\n" in self._buffer:
            self.log('buffer has newline, splitting')
            lines = self._buffer.split('\n')
            if lines[-1] != "\n":
                # last line didn't end yet
                self.log('last line still in progress')
                self._buffer = lines[-1]
                del lines[-1]
            else:
                self.log('last line finished, resetting buffer')
                self._buffer = ""
            for line in lines:
                self.log('Parsing %s', line)
                m = _EXCLUSIVE_RE.search(line)
                if not m:
                    m = _ERROR_RE.search(line)
                if m:
                    error = m.group('error')
                    self._task.errors.append(error)
                    self.debug('Found ERROR: output: %s', error)
                    self._task.exception = ProgramError(error)
                    self._task.abort()
                    return

            self._parse(lines)
            self._lines.extend(lines)

    def _parse(self, lines):
        for line in lines:
            self.debug( 'parsing (len %d): %r' % (len(line), line) )
            methodName = "_parse_" + self._state
            getattr(self, methodName)(line)

    def _parse_START(self, line):
        if line.startswith('Cdrdao version'):
            m = _VERSION_RE.search(line)
            self.version = m.group('version')

        if line.startswith('Track'):
            self.debug('Found possible track line')
            if line == "Track   Mode    Flags  Start                Length":
                self.debug('Found track line, moving to TRACK state')
                self._state = 'TRACK'
                return

        m = _EXCLUSIVE_RE.search(line)
        if m:
            # Exclusive access failure: abort. Retrying won't fix it.
            error = m.group('error')
            self._task.errors.append(error)
            self._task.exception = ProgramError(error)
            self._task.abort()

        m = _ERROR_RE.search(line)
        if m:
            error = m.group('error')
            self._task.errors.append(error)

    def _parse_TRACK(self, line):
        if line.startswith('---'):
            return

        m = _TRACK_RE.search(line)
        if m:
            t = int(m.group('track'))
            self.tracks += 1
            track = table.Track(self.tracks, session=self._session)
            track.index(1, absolute=int(m.group('start')))
            self.table.tracks.append(track)
            self.debug('Found absolute track %d, session-relative %d', t,
                self.tracks)

        m = _LEADOUT_RE.search(line)
        if m:
            self.debug('Found leadout line, moving to LEADOUT state')
            self._state = 'LEADOUT'
            self._frames = int(m.group('start'))
            self.debug('Found absolute leadout at offset %r', self._frames)
            self.info('%d tracks found for this session', self.tracks)
            return

    def _parse_LEADOUT(self, line):
        m = _ANALYZING_RE.search(line)
        if m:
            self.debug('Found analyzing line')
            track = int(m.group('track'))
            self.description = 'Analyzing track %d...' % track
            self.track = track


# FIXME: handle errors


class CDRDAOTask(ctask.PopenTask):
    """
    I am a task base class that runs CDRDAO.
    """

    logCategory = 'CDRDAOTask'
    description = "Reading TOC..."
    options = None
    device = None

    def __init__(self, device=None):
        self.errors = []
        self.device = device
        self.debug('creating CDRDAOTask')

    def start(self, runner):
        self.debug('Starting cdrdao with options %r', self.options)
        self.command = ['cdrdao', ] + self.options

        if self.device and platform.system()=='Darwin':
            # if the device is mounted (data session), unmount it
            self.debug('Unmounting device %s, due to Darwin automount\n' % self.device.getNotRawPath())

            os.system('diskutil unmountDisk %s' % self.device.getNotRawPath())
            # self.program.unmountDevice(self.device.getNotRawPath())

        ctask.PopenTask.start(self, runner)


    def commandMissing(self):
        raise common.MissingDependencyException('cdrdao')


    def failed(self):
        if self.errors:
            raise DeviceOpenException("\n".join(self.errors))
        else:
            raise ProgramFailedException(self._popen.returncode)

    """
    convertDevice( deviceMorituri=None ): deviceCdrdao

    Accepts a device name (type: string) as used in the rest of Morituri.
    Converts it to a device name (type: string) as used by the cli tool cdrdao.

    On Linux, cdrdao can operate on a pathname such as "/dev/cdrom" just like
    Morituri can, so this conversion is identity. (See Scsiif-linux.cc in cdrdao.)

    On Mac OS X, cdrdao requires a device identifier which is either an index number
    or a full IOKit path.  (See Scsiif-osx.cc in cdrdao.)

    The index number is formatted as "%i,%i,%i", and the *sum* of these three integers
    plus 1 is the index. e.g. "0,0,0" is index == 1.  This index, which is 1-based,
    selects one of the devices, enumerated from the I/O Registry, with the property
    kIOPropertySCSITaskDeviceCategory having value kIOPropertySCSITaskAuthoringDevice .
    The following command line lists those I/O Registry entries:
        ioreg -r -k SCSITaskDeviceCategory -d 1 -S -w 0
    From the properties in each entry a developer can figure out which device it
    represents. An end user of morituri cannot be expected to.

    The full IOKit path is a long string, with the slash-separated entry names of the
    path from I/O Registry to device leaf node. An example path (line breaks added):
        IOService:/AppleACPIPlatformExpert/PCI0/AppleACPIPCI/EHC1@1D,7/AppleUSBEHCI/
        USB Mass Storage Device @fd100000/IOUSBInterface@0/IOUSBMassStorageClass/
        IOSCSIPeripheralDeviceNub/IOSCSIPeripheralDeviceType05/IODVDServices

    If you unmount all CD/DVD volumes, then run the command
        cdrdao scanbus
    the result will be a list of devices, with the proper I/O Registry path for each,
    in index number order. An end user of morituri cannot be expected to run this
    command or understand the result. Morituri's code cannot be expected to derive an
    I/O Registry path given a device file path (e.g. "/dev/rdisk3"), short of calling
    Objective-C APIs directly (note: consider PyObjC https://pythonhosted.org/pyobjc/).

    Thus, on Mac OS X this conversion always returns "0,0,0", meaning the first device.
    Until this limitation is eased, don't expect to use more than one device with
    morituri on a Mac.

    On Windows, cdrdao requires a device identifier which is a SCSI address, formatted
    as "%i:%i:%i". The three numbers are labeled haid_, lun_, and scsi_id_ . At
    present this function is not tested on Windows, so it does an identity conversion.
    (See Scsiif-win.cc in cdrdao.)

    (For all the above source code references, look in methods ScsiIf::ScsiIf() and
    ScsiIf::ScsiInit() in the named file. Available via http://cdrdao.sourceforge.net/ .
    Current as of cdrdao version 1.2.3.)
    """
    def convertDevice(self, deviceMorituri ):
        deviceCdrdao = deviceMorituri.getRawPath()  # identity conversion if we don't know better
        if platform.system()=='Darwin':
            deviceCdrdao = "0,0,0"  # means index == 1 to cdrdao
            self.debug('convertDevice(): Darwin platform; '
                    'original device %s, normalised device %s'
                    % (deviceMorituri.getRawPath(), deviceCdrdao)
            )
        return deviceCdrdao


class DiscInfoTask(CDRDAOTask):
    """
    I am a task that reads information about a disc.

    @ivar sessions: the number of sessions
    @type sessions: int
    """

    logCategory = 'DiscInfoTask'
    description = "Scanning disc..."
    table = None
    sessions = None

    def __init__(self, device=None):
        """
        @param device:  the device to rip from
        @type  device:  program.device.Device()
        """
        self.debug('creating DiscInfoTask for device %r', device)
        CDRDAOTask.__init__(self, device)

        self.options = ['disk-info', ]
        if device:
            self.options.extend(['--device', self.convertDevice(device), ])

        self.parser = LineParser(self)

    def readbytesout(self, bytes):
        self.parser.read(bytes)

    def readbyteserr(self, bytes):
        self.parser.read(bytes)

    def parse(self, line):
        # called by parser
        self.debug('Parsing: %r' % line)
        if line.startswith('Sessions'):
            self.sessions = int(line[line.find(':') + 1:])
            self.debug('Found %d sessions', self.sessions)

        m = _EXCLUSIVE_RE.search(line)
        if m:
            # Exclusive access failure: abort. Retrying won't fix it.
            error = m.group('error')
            self.errors.append(error)
            self.exception = ProgramError(error)
            self.abort()

        m = _ERROR_RE.search(line)
        if m:
            error = m.group('error')
            self.errors.append(error)

    def done(self):
        pass


# Read stuff for one session


class ReadSessionTask(CDRDAOTask):
    """
    I am a task that reads things for one session.

    @ivar table: the index table
    @type table: L{table.Table}
    """

    logCategory = 'ReadSessionTask'
    description = "Reading session"
    table = None
    extraOptions = None

    def __init__(self, session=None, device=None):
        """
        @param session: the session to read
        @type  session: int
        @param device:  the device to rip from
        @type  device:  str
        """
        self.debug('Creating ReadSessionTask for session %d on device %r',
            session, device)
        CDRDAOTask.__init__(self, device)
        self.parser = OutputParser(self)
        (fd, self._tocfilepath) = tempfile.mkstemp(
            suffix=u'.readtablesession.morituri')
        os.close(fd)
        os.unlink(self._tocfilepath)

        self.options = ['read-toc', ]
        if device:
            self.options.extend(['--device', self.convertDevice(device), ])
        if session:
            self.options.extend(['--session', str(session)])
            self.description = "%s of session %d..." % (
                self.description, session)
        if self.extraOptions:
            self.options.extend(self.extraOptions)

        self.options.extend([self._tocfilepath, ])

    def readbyteserr(self, bytes):
        self.parser.read(bytes)

        if self.parser.tracks > 0:
            self.setProgress(float(self.parser.track - 1) / self.parser.tracks)

    def done(self):
        # by merging the TOC info.
        self._tocfile = toc.TocFile(self._tocfilepath)
        self._tocfile.parse()
        os.unlink(self._tocfilepath)
        self.table = self._tocfile.table

        # we know the .toc file represents a single wav rip, so all offsets
        # are absolute since beginning of disc
        self.table.absolutize()
        # we unset relative since there is no real file backing this toc
        for t in self.table.tracks:
            for i in t.indexes.values():
                #i.absolute = i.relative
                i.relative = None

        # copy the leadout from the parser's table
        # FIXME: how do we get the length of the last audio track in the case
        # of a data track ?
        # self.table.leadout = self.parser.table.leadout

        # we should have parsed it from the initial output
        assert self.table.leadout is not None


class ReadTableSessionTask(ReadSessionTask):
    """
    I am a task that reads all indexes of a CD for a session.

    @ivar table: the index table
    @type table: L{table.Table}
    """

    logCategory = 'ReadTableSessionTask'
    description = "Scanning indexes"


class ReadTOCSessionTask(ReadSessionTask):
    """
    I am a task that reads the TOC of a CD, without pregaps.

    @ivar table: the index table that matches the TOC.
    @type table: L{table.Table}
    """

    logCategory = 'ReadTOCSessTask'
    description = "Reading TOC"
    extraOptions = ['--fast-toc', ]

    def done(self):
        ReadSessionTask.done(self)

        assert self.table.hasTOC(), "This Table Index should be a TOC"

# read all sessions


class ReadAllSessionsTask(task.MultiSeparateTask):
    """
    I am a base class for tasks that need to read all sessions.

    @ivar table: the index table
    @type table: L{table.Table}
    """

    logCategory = 'ReadAllSessionsTask'
    table = None
    _readClass = None
    _device = None

    def __init__(self, device=None):
        """
        @param device:  the device to rip from
        @type  device:  program.device.Device()
        """
        task.MultiSeparateTask.__init__(self)

        self._device = device

        self.debug('Starting ReadAllSessionsTask')
        self.tasks = [DiscInfoTask(device=device), ]

    def stopped(self, taskk):
        if not taskk.exception:
            # After first task, schedule additional ones
            if taskk == self.tasks[0]:
                for i in range(taskk.sessions):
                    self.tasks.append(self._readClass(session=i + 1,
                        device=self._device))

            if self._task == len(self.tasks):
                self.table = self.tasks[1].table
                if len(self.tasks) > 2:
                    for i, t in enumerate(self.tasks[2:]):
                        self.table.merge(t.table, i + 2)

                assert self.table.leadout is not None

        task.MultiSeparateTask.stopped(self, taskk)


class ReadTableTask(ReadAllSessionsTask):
    """
    I am a task that reads all indexes of a CD for all sessions.

    @ivar table: the index table
    @type table: L{table.Table}
    """

    logCategory = 'ReadTableTask'
    description = "Scanning indexes..."
    _readClass = ReadTableSessionTask


class ReadTOCTask(ReadAllSessionsTask):
    """
    I am a task that reads the TOC of a CD, without pregaps.

    @ivar table: the index table that matches the TOC.
    @type table: L{table.Table}
    """

    logCategory = 'ReadTOCTask'
    description = "Reading TOC..."
    _readClass = ReadTOCSessionTask


class DeviceOpenException(Exception):

    def __init__(self, msg):
        self.msg = msg
        self.args = (msg, )


class ProgramFailedException(Exception):

    def __init__(self, code):
        self.code = code
        self.args = (code, )


_VERSION_RE = re.compile(
    "^Cdrdao version (?P<version>.+) -")


def getCDRDAOVersion():
    getter = common.VersionGetter('cdrdao',
        ["cdrdao"],
        _VERSION_RE,
        "%(version)s")

    return getter.get()

