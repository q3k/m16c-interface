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

import argparse
import logging
import sys

import adapter, serialio


def crack(args, s):
    # Run target clock at 3MHz.
    s.adapter.set_tclk(1)
    # Run serial clock at 1.5MHz.
    s.adapter.set_sclk(127)
    code = []
    while len(code) != 7:
        logging.info("Cracking byte {}/7...".format(len(code)+1, 7))
        byte_times = []
        for try_byte in range(256):
            samples = []
            for _ in range(args.samples):
                # Send code right-padded with 0xDE.
                bin_code = ''.join(chr(c) for c in code) + chr(try_byte)
                s.unlock(bin_code.ljust(7, '\xDE'))
                # Measure response time.
                samples.append(s.adapter.busy_timer())
            # Take median time.
            samples = sorted(samples)
            median = samples[args.samples/3]
            logging.debug("Code {}, times {}, median {}".format(try_byte,
                samples, median))
            byte_times.append(median)
        # For every byte apart from the last one, the correct byte results in
        # a longer busy time.
        correct = None
        if len(code) == 6:
            correct = byte_times.index(min(byte_times))
        else:
            correct = byte_times.index(max(byte_times))
        logging.info("Byte {}/7 -> {}".format(len(code)+1, correct))
        code.append(correct)
    bin_code = ''.join(chr(c) for c in code).encode('hex')
    logging.info("Finished. Code: {}, {}".format(code, bin_code))


def dump(args, s):
    # Run target clock at 6MHz.
    s.adapter.set_tclk(0)
    # Run target serial clock at 1.5MHz
    s.adapter.set_sclk(127)

    try:
        code = args.code.decode('hex')
    except TypeError:
        logging.fatal("Code must be in hexadecimal format.")
        return
    if len(code) != 7:
        logging.fatal("Code must be 7 bytes long.")
        return

    s.unlock(code)
    status = s.unlock_status()
    if status != serialio.UNLOCK_SUCCESSFUL:
        logging.fatal("Target did not unlock.")
        return
    logging.info("Target unlocked.")

    start = 0x0e00
    end = 0x0fff

    with open(args.output, 'w') as f:
        logging.info("Writing pages {:x}-{:x} to {}...".format(start, end,
            args.output))
        for page in range(start, end+1):
            logging.debug("Dumping {:x}00-{:x}ff...".format(page, page))
            data = s.read_page(page)
            f.write(data)

parser = argparse.ArgumentParser(
        description='Renesas M16C SerialIO Programmer.')
parser.add_argument('--port', '-p', help='Adapter serial port.',
        default='/dev/ttyUSB1')
parser.add_argument('--verbose', '-v', help='Increase output verbosity.',
        action='store_true')
parser.add_argument('--debug-protocol', '-d', help='Log protocol bytes.',
        action='store_true')
parser.add_argument('--debug-adapter', '-D', help='Log adapter bytes.',
        action='store_true')
parser.add_argument('--timestamps', '-t', help='Include timestamps in log.',
        action='store_true')
subparsers = parser.add_subparsers(help='Mode of operation.')

parser_crack = subparsers.add_parser('crack', help='Crack security PIN.')
parser_crack.add_argument('--samples', help='Samples per byte.', type=int,
        default=3)
parser_crack.set_defaults(func=crack)

parser_dump = subparsers.add_parser('dump', help='Dump flash memory.')
parser_dump.add_argument('--output', '-o', help='Output file.', type=str,
        required=True)
parser_dump.add_argument('--code', '-c', help='Unlock code.', type=str,
        required=True)
parser_dump.set_defaults(func=dump)


if __name__ == '__main__':
    args = parser.parse_args()

    fmt = '%(message)s'
    if args.timestamps:
        fmt = '%(asctime)-15s %(levelname)s %(message)s'
    if args.verbose:
        logging.basicConfig(level=logging.DEBUG, format=fmt)
    else:
        logging.basicConfig(level=logging.INFO, format=fmt)

    adapter_logger, protocol_logger = None, None
    if args.debug_adapter:
        adapter_logger = logging
    if args.debug_protocol:
        protocol_logger = logging

    a = adapter.Adapter(args.port, logger=adapter_logger)
    s = serialio.SerialIO(a, logger=protocol_logger)
    s.adapter.connect()
    logging.info("Connected to adapter version {}".format(s.adapter.version()))
    s.connect()
    logging.info("Connected to target version {}".format(s.version()))

    sys.exit(args.func(args, s) or 0)

