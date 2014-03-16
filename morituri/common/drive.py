# -*- Mode: Python; test-case-name: morituri.test.test_common_drive -*-
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
import time

from morituri.common import log
from morituri.program import device as deviceModule


def _listify(listOrString):
    if type(listOrString) == str:
        return [listOrString, ]

    return listOrString


def getAllDevicePaths():
    try:
        # see https://savannah.gnu.org/bugs/index.php?38477
        return [str(dev) for dev in _getAllDevicePathsPyCdio()]
    except ImportError:
        log.info('drive', 'Cannot import pycdio')
        return _getAllDevicePathsStatic()


def _getAllDevicePathsPyCdio():
    import pycdio
    import cdio

    # using FS_AUDIO here only makes it list the drive when an audio cd
    # is inserted
    # ticket 102: this cdio call returns a list of str, or a single str
    return _listify(cdio.get_devices_with_cap(pycdio.FS_MATCH_ALL, False))


def _getAllDevicePathsStatic():
    ret = []

    for c in ['/dev/cdrom', '/dev/cdrecorder', '/dev/rdisk1']:
        if os.path.exists(c):
            ret.append(c)

    return ret


def getDeviceInfo(device):
    try:
        import cdio
    except ImportError:
        return None

    if isinstance(device, deviceModule.Device):
        path = device.getName()
    else:
        path = device

    # On Darwin (Mac OS X), sometimes libcdio will lose access to CD drive,
    # if it has just been busy with another task. os.stat(path) tests for
    # this. If stat returns an OSError #2, the CD drive is inaccessible for now.
    # On my system, 0.5 seconds wait is long enough for the drive to reappear.
    # But we have a few longer delays in reserve.

    delays = [0.5, 2, 10]  # seconds to wait after each failed attempt
    while True:
        try:
            os.stat(path)  # sometimes cdio loses access to device on Darwin
            break  # if no exception, then device is available
        except OSError:
            # print 'getDeviceInfo: os.stat(%s) failed' % path,
            if len(delays) == 0:
                # print 'returning None from getDeviceInfo()'
                return None
            # print 'waiting for %f seconds' % delays[0],
            time.sleep(delays[0])
            delays = delays[1:]
            # print 'and trying os.stat() again.'

    deviceCDIO = cdio.Device(path)
    _, vendor, model, release = deviceCDIO.get_hwinfo()

    return (vendor, model, release)
