# -*- Mode: Python -*-
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

from morituri.extern.task import task

from morituri.common import logcommand, drive
from morituri.program import cdparanoia, device

class Analyze(logcommand.LogCommand):

    summary = "analyze caching behaviour of drive"

    def addOptions(self):
        self.parser.add_option('-d', '--device',
            action="store", dest="deviceName",
            help="CD-DA device")

    def handleOptions(self, options):
        if not options.deviceName:
            drives = drive.getAllDevicePaths()
            if not drives:
                self.error('No CD-DA drives found!')
                return 3

            # pick the first
            self.options.deviceName = drives[0]

        assert self.options.deviceName, 'Could not identify a device to use.'
        self.options.device = device.Device(self.options.deviceName)
        # this can be a symlink to another device, but Device() will take care of that

    def do(self, args):
        runner = task.SyncRunner()
        t = cdparanoia.AnalyzeTask(self.options.device)
        runner.run(t)

        if t.defeatsCache is None:
            self.stdout.write(
                'Cannot analyze the drive.  Is there a CD in it?\n')
            return
        if not t.defeatsCache:
            self.stdout.write(
                'cdparanoia cannot defeat the audio cache on this drive.\n')
        else:
            self.stdout.write(
                'cdparanoia can defeat the audio cache on this drive.\n')

        info = drive.getDeviceInfo(self.options.device)
        if not info:
            return

        self.stdout.write(
            'Adding drive cache behaviour to configuration file.\n')

        self.getRootCommand().config.setDefeatsCache(info[0], info[1], info[2],
            t.defeatsCache)


class List(logcommand.LogCommand):

    summary = "list drives"

    def do(self, args):
        paths = drive.getAllDevicePaths()

        if not paths:
            self.stdout.write('No drives found.\n')
            self.stdout.write('Create /dev/cdrom if you have a CD drive, \n')
            self.stdout.write('or install pycdio for better detection.\n')

            return

        try:
            import cdio as _
        except ImportError:
            self.stdout.write(
                'Install pycdio for vendor/model/release detection.\n')
            return

        for path in paths:
            vendor, model, release = drive.getDeviceInfo(path)
            self.stdout.write(
                "drive: %s, vendor: %s, model: %s, release: %s\n" % (
                path, vendor, model, release))

            try:
                offset = self.getRootCommand().config.getReadOffset(
                    vendor, model, release)
                self.stdout.write(
                    "       Configured read offset: %d\n" % offset)
            except KeyError:
                self.stdout.write(
                    "       No read offset found.  Run 'rip offset find'\n")

            try:
                defeats = self.getRootCommand().config.getDefeatsCache(
                    vendor, model, release)
                self.stdout.write(
                    "       Can defeat audio cache: %s\n" % defeats)
            except KeyError:
                self.stdout.write(
                    "       Unknown whether audio cache can be defeated. "
                    "Run 'rip drive analyze'\n")


        if not paths:
            self.stdout.write('No drives found.\n')


class Drive(logcommand.LogCommand):

    summary = "handle drives"

    subCommandClasses = [Analyze, List, ]
