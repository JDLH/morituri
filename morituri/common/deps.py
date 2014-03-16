# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

import os
import urllib
import platform
import sys

from morituri.extern.deps import deps


class DepsHandler(deps.DepsHandler):

    def __init__(self, name='morituri'):
        deps.DepsHandler.__init__(self, name)

        self.add(GStPython())
        self.add(CDDB())
        self.add(SetupTools())
        if platform.system() == "Darwin":
            self.add(LibCDIO())
        self.add(PyCDIO())

    def report(self, summary):
        reporter = os.environ.get('EMAIL_ADDRESS', None)
        get = "summary=%s" % urllib.quote(summary)
        if reporter:
            get += "&reporter=%s" % urllib.quote(reporter)
        return 'http://thomas.apestaart.org/morituri/trac/newticket?' + get


class GStPython(deps.Dependency):
    module = 'gst'
    name = "GStreamer Python bindings"
    homepage = "http://gstreamer.freedesktop.org"

    def Fedora_install(self, distro):
        return self.Fedora_yum('gstreamer-python')

    #def Ubuntu_install(self, distro):
    #    pass

    def Darwin_install(self, distro):
        return self.Darwin_macports('gstreamer010-gst-plugins-good %s-gst-python' % self.Pytag())


class CDDB(deps.Dependency):
    module = 'CDDB'
    name = "python-CDDB"
    homepage = "http://cddb-py.sourceforge.net/"

    def validate(self):
        try:
            import CDDB
            return None  # success
        except:
            (_,e,_) = sys.exc_info()
            try:
                return e.args[0]
            except:
                return "Error importing %s, details unknown." % self.module

    def Fedora_install(self, distro):
        return self.Fedora_yum('python-CDDB')

    def Ubuntu_install(self, distro):
        return self.Ubuntu_apt('python-cddb')

    def Darwin_install(self, distro):
        return (self.Darwin_prefix+"1. Download CDDB-1.4.tar.gz from %s\n"
                "2. Extract archive\n"
                "3. type command: cd CDDB-1.4/\n"
                "4. type command: sudo python setup.py install ") \
                % (self.module, "setup.py", self.homepage)


class SetupTools(deps.Dependency):
    module = 'pkg_resources'
    name = "python-setuptools"
    homepage = "http://pypi.python.org/pypi/setuptools"

    def Fedora_install(self, distro):
        return self.Fedora_yum('python-setuptools')

    def Darwin_install(self, distro):
        return self.Darwin_macports('gstreamer010-gst-plugins-good %s-gst-python' % self.Pytag())


class LibCDIO(deps.Dependency):
    module = 'libcdio'
    name = "Compact Disc Input and Control Library"
    homepage = "http://www.gnu.org/software/libcdio/"

    def Darwin_install(self, distro):
        return self.Darwin_macports('libcdio')


class PyCDIO(deps.Dependency):

    module = 'pycdio'
    name = "pycdio"
    homepage = "http://www.gnu.org/software/libcdio/"
    egg = 'pycdio'

    def Fedora_install(self, distro):
        return self.Fedora_yum('pycdio')

    def Darwin_install(self, distro):
        return self.Darwin_pip('pycdio')

    def validate(self):
        version = self.version()
        if version == '0.18':
            return '''pycdio 0.18 does not work.
See http://savannah.gnu.org/bugs/?38185'''
