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


'''
This module defines a Device class, which stores the string identifying a CD reader device,
and provides various alternative names for the same device.

These alternative names are not necessary in Linux, but are necessary in Mac OS X (Darwin), and
might prove necessary in Windows.

Created on Mar 10, 2014

@author: jdlh
'''

import re
import os
import platform

from morituri.common import log

_DEVDISK_RE    = None
_DEVRAW_RE     = None
_DEVNOTRAW_RE  = None

# Regular expression to convert Darwin platform devices like /dev/rdisk1
# into /dev/disk1
if platform.system() == 'Darwin':
    _DEVDISK_RE   = re.compile(r'/dev/(?P<raw>r?)disk(?P<disknum>\d+)')
    _DEVRAW_RE    = r'/dev/rdisk\g<disknum>'  # leaves out the r in rdisk
    _DEVNOTRAW_RE = r'/dev/disk\g<disknum>'  # adds an r to /dev/disk

class Device(log.Loggable):
    """
    I am a Device class, which stores the string identifying a CD reader device,
    and provides various alternative names for the same device.

    These alternative names are not necessary in Linux, but are necessary in Mac OS X (Darwin), and
    might prove necessary in Windows.
    """

    logCategory = 'Device'
    description = "Handling device name"

    def __init__(self, path=None):
        self.original = path

        self.pathRaw = path
        self.pathNotRaw = path
        if _DEVDISK_RE:
            # Darwin and maybe other platforms need name spelled as a "raw" disk (e.g. "/dev/rdisk1")
            # in some cases, and not raw in others (e.g. "/dev/disk1"). Paths which don't match the
            # pattern are unchanged, and the pathRaw and pathNotRaw are identical.
            # If no change needed, _DEVDISK_RE is "None".
            self.pathRaw = _DEVDISK_RE.sub(_DEVRAW_RE, path, 1)
            self.pathNotRaw = _DEVDISK_RE.sub(_DEVNOTRAW_RE, path, 1)

            self.debug('On %s, original device name %s is: Raw %s, Not Raw %s.'
                       % (platform.system(), self.original, self.pathRaw, self.pathNotRaw)
                )

    def getName(self):
        """Returns device name as supplied by caller."""
        return self.original

    def getRawPath(self):
        """
        Returns device name as raw disk path if caller supplied a disk path name,
        or the original device name otherwise.
        """
        return self.pathRaw

    def getNotRawPath(self):
        """
        Returns device name as non-raw disk path if caller supplied a disk path name,
        or the original device name otherwise.
        """
        return self.pathNotRaw

    def getRealPath(self):
        """
        Returns device name as path to real device, dereferencing symbolic links if necessary
        """
        return os.path.realpath(self.original)

    def getIOKit_ordinal(self):
        """
        Returns an ordinal number (1-based) identifying this device in IOKit's
        device registry. Only meaningful for Darwin platforms; 1 otherwise.
        WARNING: Currently hard-coded to return 1 even on Darwin.
        """
        if platform.system() == 'Darwin':
            i = 1 # FIXME with an ordinal derived from Darwin IO Registry
            self.debug('On %s, IOKit_ordinal is %d.' % (platform.system(), i))
            return i
        else:
            # All other platforms
            self.warning('Asking for IOKit_ordinal on %s, which is not meaningful.' % platform.system())
            return 1

    # TODO: consider moving the following methods here from common.drive.
    # _getAllDevicePathsPyCdio()
    # _getAllDevicePathsStatic()
    # getDeviceInfo()

    # Basic class Python infrastructure
    def __str__(self):
        return "Device('%s')" % self.original

    def __repr__(self):
        return self.__str__()
