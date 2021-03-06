# -*- Mode: Python; test-case-name: morituri.test.test_common_common -*-
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


import os
import os.path
import commands
import math
import subprocess

from morituri.extern import asyncsub
from morituri.extern.log import log

FRAMES_PER_SECOND = 75

SAMPLES_PER_FRAME = 588 # a sample is 2 16-bit values, left and right channel
WORDS_PER_FRAME = SAMPLES_PER_FRAME * 2
BYTES_PER_FRAME = SAMPLES_PER_FRAME * 4


def msfToFrames(msf):
    """
    Converts a string value in MM:SS:FF to frames.

    @param msf: the MM:SS:FF value to convert
    @type  msf: str

    @rtype:   int
    @returns: number of frames
    """
    if not ':' in msf:
        return int(msf)

    m, s, f = msf.split(':')

    return 60 * FRAMES_PER_SECOND * int(m) \
        + FRAMES_PER_SECOND * int(s) \
        + int(f)


def framesToMSF(frames, frameDelimiter=':'):
    f = frames % FRAMES_PER_SECOND
    frames -= f
    s = (frames / FRAMES_PER_SECOND) % 60
    frames -= s * 60
    m = frames / FRAMES_PER_SECOND / 60

    return "%02d:%02d%s%02d" % (m, s, frameDelimiter, f)


def framesToHMSF(frames):
    # cdparanoia style
    f = frames % FRAMES_PER_SECOND
    frames -= f
    s = (frames / FRAMES_PER_SECOND) % 60
    frames -= s * FRAMES_PER_SECOND
    m = (frames / FRAMES_PER_SECOND / 60) % 60
    frames -= m * FRAMES_PER_SECOND * 60
    h = frames / FRAMES_PER_SECOND / 60 / 60

    return "%02d:%02d:%02d.%02d" % (h, m, s, f)


def formatTime(seconds, fractional=3):
    """
    Nicely format time in a human-readable format, like
    HH:MM:SS.mmm

    If fractional is zero, no seconds will be shown.
    If it is greater than 0, we will show seconds and fractions of seconds.
    As a side consequence, there is no way to show seconds without fractions.

    @param seconds:    the time in seconds to format.
    @type  seconds:    int or float
    @param fractional: how many digits to show for the fractional part of
                       seconds.
    @type  fractional: int

    @rtype: string
    @returns: a nicely formatted time string.
    """
    chunks = []

    if seconds < 0:
        chunks.append(('-'))
        seconds = -seconds

    hour = 60 * 60
    hours = seconds / hour
    seconds %= hour

    minute = 60
    minutes = seconds / minute
    seconds %= minute

    chunk = '%02d:%02d' % (hours, minutes)
    if fractional > 0:
        chunk += ':%0*.*f' % (fractional + 3, fractional, seconds)

    chunks.append(chunk)

    return " ".join(chunks)


def tagListToDict(tl):
    """
    Converts gst.TagList to dict.
    Also strips it of tags that are not writable.
    """
    import gst

    d = {}
    for key in tl.keys():
        if key == gst.TAG_DATE:
            date = tl[key]
            d[key] = "%4d-%2d-%2d" % (date.year, date.month, date.day)
        elif key in [
            gst.TAG_AUDIO_CODEC,
            gst.TAG_VIDEO_CODEC,
            gst.TAG_MINIMUM_BITRATE,
            gst.TAG_BITRATE,
            gst.TAG_MAXIMUM_BITRATE,
            ]:
            pass
        else:
            d[key] = tl[key]
    return d


def tagListEquals(tl1, tl2):
    d1 = tagListToDict(tl1)
    d2 = tagListToDict(tl2)

    return d1 == d2


def tagListDifference(tl1, tl2):
    d1 = tagListToDict(tl1)
    d2 = tagListToDict(tl2)
    return set(d1.keys()) - set(d2.keys())

    return d1 == d2


class MissingDependencyException(Exception):
    dependency = None

    def __init__(self, *args):
        self.args = args
        self.dependency = args[0]


class EmptyError(Exception):
    pass

class MissingFrames(Exception):
    """
    Less frames decoded than expected.
    """
    pass


def shrinkPath(path):
    """
    Shrink a full path to a shorter version.
    Used to handle ENAMETOOLONG
    """
    parts = list(os.path.split(path))
    length = len(parts[-1])
    target = 127
    if length <= target:
        target = pow(2, int(math.log(length, 2))) - 1

    name, ext = os.path.splitext(parts[-1])
    target -= len(ext) + 1

    # split on space, then reassemble
    words = name.split(' ')
    length = 0
    pieces = []
    for word in words:
        if length + 1 + len(word) <= target:
            pieces.append(word)
            length += 1 + len(word)
        else:
            break

    name = " ".join(pieces)
    # ext includes period
    parts[-1] = u'%s%s' % (name, ext)
    path = os.path.join(*parts)
    return path


def getRealPath(refPath, filePath):
    """
    Translate a .cue or .toc's FILE argument to an existing path.
    Does Windows path translation.
    Will look for the given file name, but with .flac and .wav as extensions.

    @param refPath:  path to the file from which the track is referenced;
                     for example, path to the .cue file in the same directory
    @type  refPath:  unicode

    @type  filePath: unicode
    """
    assert type(filePath) is unicode, "%r is not unicode" % filePath

    if os.path.exists(filePath):
        return filePath

    candidatePaths = []

    # .cue FILE statements can have Windows-style path separators, so convert
    # them as one possible candidate
    # on the other hand, the file may indeed contain a backslash in the name
    # on linux
    # FIXME: I guess we might do all possible combinations of splitting or
    #        keeping the slash, but let's just assume it's either Windows
    #        or linux
    # See https://thomas.apestaart.org/morituri/trac/ticket/107
    parts = filePath.split('\\')
    if parts[0] == '':
        parts[0] = os.path.sep
    tpath = os.path.join(*parts)

    for path in [filePath, tpath]:
        if path == os.path.abspath(path):
            candidatePaths.append(path)
        else:
            # if the path is relative:
            # - check relatively to the cue file
            # - check only the filename part relative to the cue file
            candidatePaths.append(os.path.join(
                os.path.dirname(refPath), path))
            candidatePaths.append(os.path.join(
                os.path.dirname(refPath), os.path.basename(path)))

    # Now look for .wav and .flac files, as .flac files are often named .wav
    for candidate in candidatePaths:
        noext, _ = os.path.splitext(candidate)
        for ext in ['wav', 'flac']:
            cpath = '%s.%s' % (noext, ext)
            if os.path.exists(cpath):
                return cpath

    raise KeyError("Cannot find file for %r" % filePath)


def getRelativePath(targetPath, collectionPath):
    """
    Get a relative path from the directory of collectionPath to
    targetPath.

    Used to determine the path to use in .cue/.m3u files
    """
    log.debug('common', 'getRelativePath: target %r, collection %r' % (
        targetPath, collectionPath))

    targetDir = os.path.dirname(targetPath)
    collectionDir = os.path.dirname(collectionPath)
    if targetDir == collectionDir:
        log.debug('common',
            'getRelativePath: target and collection in same dir')
        return os.path.basename(targetPath)
    else:
        rel = os.path.relpath(
            targetDir + os.path.sep,
            collectionDir + os.path.sep)
        log.debug('common',
            'getRelativePath: target and collection in different dir, %r' %
                rel)
        return os.path.join(rel, os.path.basename(targetPath))


class VersionGetter(object):
    """
    I get the version of a program by looking for it in command output
    according to a regexp.
    """

    def __init__(self, dependency, args, regexp, expander):
        """
        @param dependency: name of the dependency providing the program
        @param args:       the arguments to invoke to show the version
        @type  args:       list of str
        @param regexp:     the regular expression to get the version
        @param expander:   the expansion string for the version using the
                           regexp group dict
        """

        self._dep = dependency
        self._args = args
        self._regexp = regexp
        self._expander = expander

    def get(self):
        version = "(Unknown)"

        try:
            p = asyncsub.Popen(self._args,
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE, close_fds=True)
            p.wait()
            output = asyncsub.recv_some(p, e=0, stderr=1)
            vre = self._regexp.search(output)
            if vre:
                version = self._expander % vre.groupdict()
        except OSError, e:
            import errno
            if e.errno == errno.ENOENT:
                raise MissingDependencyException(self._dep)
            raise

        return version


def getRevision():
    """
    Get a revision tag for the current git source tree.

    Appends -modified in case there are local modifications.

    If this is not a git tree, return the top-level REVISION contents instead.

    Finally, return unknown.
    """
    topsrcdir = os.path.join(os.path.dirname(__file__), '..', '..')

    # only use git if our src directory looks like a git checkout
    # if you run git regardless, it recurses up until it finds a .git,
    # which may be higher than your current source tree
    if os.path.exists(os.path.join(topsrcdir, '.git')):

        status, describe = commands.getstatusoutput('git describe')
        if status == 0:
            if commands.getoutput('git diff-index --name-only HEAD --'):
                describe += '-modified'

            return describe

    # check for a top-level REIVISION file
    path = os.path.join(topsrcdir, 'REVISION')
    if os.path.exists(path):
        revision = open(path).read().strip()
        return revision

    return '(unknown)'
