# Copyright (c) 2017, Serge 'q3k' Bazanski <serge@bazanski.pl>
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are
# met:
#
# 1. Redistributions of source code must retain the above copyright notice,
#    this list of conditions and the following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright
#    notice, this list of conditions and the following disclaimer in the
#    documentation and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.

"""Implementation of the Renesas Standard Serial I/O protocol."""
__author__ = "Serge 'q3k' Bazanski <serge@bazanski.pl>"


import struct


class SerialIOException(Exception):
    pass

UNLOCK_NOT_ATTEMPTED = 0
UNLOCK_FAILED = 1
UNLOCK_SUCCESSFUL = 3


class SerialIO(object):
    CMD_UNLOCK = '\xF5\xDF\xFF\x0F\x07'
    CMD_VERSION = '\xFB'
    CMD_READ = '\xFF'

    def __init__(self, adapter, logger=None):
        self.adapter = adapter
        self.logger = logger

    def _log(self, msg):
        if self.logger is None:
            return
        self.logger.info(msg)

    def _execute(self, cmd, return_bytes):
        self._log("FPGA -> M16C {}, {}".format(
            cmd.encode('hex'), return_bytes))
        res = self.adapter.execute(cmd, return_bytes)
        self._log("FPGA <- M16C {}".format(res.encode('hex')))
        return res

    def version(self):
        return self._execute(self.CMD_VERSION, 8)

    def connect(self):
        self.adapter.connect()
        self.adapter.reset_target()
        v = self.version()
        if not v.startswith('VER'):
            raise SerialIOException('Invalid version: {}'
                    .format(v.encode('hex')))

    def unlock(self, code):
        self._execute(self.CMD_UNLOCK + code, 0)

    def unlock_status(self):
        status = self._execute('\x70', 2)
        return (ord(status[1]) >> 2) & 3
    
    def read_page(self, page):
        return self._execute(self.CMD_READ + struct.pack('<H', page), 256)
    

