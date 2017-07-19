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

"""Implementation of adapter protocol."""
__author__ = "Serge 'q3k' Bazanski <serge@bazanski.pl>"

import logging
import struct
import sys
import time

import serial


class AdapterException(Exception):
    pass


class Adapter(object):
    TIMEOUT = 3.0

    def __init__(self, port, baud_rate=1200000, logger=None):
        self.serial = serial.Serial(port, baud_rate, timeout=self.TIMEOUT)
        self.logger = logger

    def _log(self, msg):
        if self.logger is None:
            return
        self.logger.info(msg)

    def _write(self, data):
        self._log("Host -> FPGA {}".format(`data`))
        return self.serial.write(data)

    def _read(self, l):
        data = self.serial.read(l)
        self._log("Host <- FPGA {}".format(`data`))
        return data

    def _read_byte(self):
        res = self._read(1)
        if not res:
            raise AdapterException("Timed out.")
        return res

    def _read_word(self):
        try:
            data, = struct.unpack('<I', self._read(4))
            return data
        except struct.error:
            raise AdapterException("Timed out.")

    def connect(self):
        """Ensures the adapter is connected."""
        version = self.version()
        if version != 0:
            raise AdapterException("Unexpected adapter version: {}"
                    .format(version))

    def version(self):
        """Returns version of FPGA bitstream API."""
        self._write('v')
        data = self._read(1)
        if not data:
            return AdapterException("Adapter did not respond with version.")
        try:
            return int(data)
        except ValueError:
            raise AdapterException("Invalid adapter version: {:02x}"
                    .format(ord(data)))

    def _check_ack(self):
        """Checks the adapter returned an ACK."""
        if self._read(1) != '.':
            raise AdapterException("No ACK from adapter.")

    def reset_target(self):
        """Resets the target MCU."""
        self._write('r')
        return self._check_ack()
    
    def flush(self):
        """Flushes (drops) the adapter FIFOs."""
        self._write('f')
        return self._check_ack()
    
    def busy_timer(self):
        """Waits until the busy timer stops running, returns it value."""
        while True:
            self._write('T')
            if self._read_byte() == 's':
                break
        self._write('t')
        return self._read_word()

    def _fifo_read(self, count):
        self._write('R' + struct.pack('<I', count))
        data = self._read(count)
        if len(data) != count:
            raise AdapterException("Adapter stopped responding.")
        return data

    def execute(self, command, result_size):
        """
        Executes a command via Standard Serial I/O.
        
        Args:
            command: String containing command bytes.
            result_size: Size of the result to read.
        
        Returns:
            String containing result_size bytes.
        
        Raises:
            AdapterException: If there was an issue with the adapter.
        """
        self.flush()
        # We need to fill the FIFO with the command + enough 0xFFs to read the
        # resulting data.
        data = command + ('\xff' * result_size)
        # Send 64 bytes at a time and batch read acks (for speed):
        for i in range(0, len(data), 64):
            block = data[i:i+64]
            buf = ''.join("w" + c for c in block)
            self._write(buf)
            acks = self._read(len(block))
            if any(a != '.' for a in acks):
                raise AdapterException("No ACK from adapter.")

        # Tell adapter to perform transaction.
        self._write('W')
        self._check_ack()

        # Read back all the bytes that we received when transmitting the
        # command and throw them away.
        self._fifo_read(len(command))

        # Return response bytes.
        return self._fifo_read(result_size)

    def set_tclk(self, val):
        """Sets target clock counter.

        Sample values:
           0: 6 MHz
           1: 3 MHz
           2: 2 MHz
           3: 1.5 MHz
           4: 1.2 Mhz
           11: 500 KHz
        """

        self._write('s' + chr(val))
        self._check_ack()

    def set_sclk(self, val):
        """Sets adapter serial clock counter."""
        self._write('S' + struct.pack('<H', val))
        self._check_ack()

