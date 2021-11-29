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

"""The main state machine of the adapter."""
__author__ = "Serge 'q3k' Bazanski <serge@bazanski.pl>"

import sys

from migen import *
from migen.genlib.fifo import SyncFIFOBuffered
from migen.build.generic_platform import Subsignal, Pins, IOStandard
from migen.build.platforms import icestick

import uart

class Top(Module):
    # Board clock frequency.
    CLKFREQ = 12000000
    # Host UART baud rate.
    BAUDRATE = 1200000

    def __init__(self, platform):
        # Instantiate and connect UART cores to host.
        self.submodules.uart_rx = uart.RXFIFO(self.CLKFREQ, self.BAUDRATE)
        self.submodules.uart_tx = uart.TXFIFO(self.CLKFREQ, self.BAUDRATE)
        serial = platform.request('serial')
        self.comb += [
            serial.tx.eq(self.uart_tx.tx),
            self.uart_rx.rx.eq(serial.rx),
        ]

        # Heartbeat LED.
        led = platform.request('user_led')
        counter = Signal(max=12000000)
        self.sync += If(counter == 11999999,
            counter.eq(0),
            led.eq(~led),
        ).Else(
            counter.eq(counter + 1),
        )

        target = platform.request('sio')
        # Register signals from target because metastability.
        target_txd = Signal()
        target_busy = Signal()
        self.sync += [
            target_txd.eq(target.txd),
            target_busy.eq(target.busy),
        ]

        # More debug LEDs.
        self.comb += [
            platform.request('user_led').eq(target.rxd),
            platform.request('user_led').eq(target.txd),
            platform.request('user_led').eq(target.busy),
        ]

        # Input/output FIFOs.
        self.submodules.txbuffer = SyncFIFOBuffered(8, 512)
        self.submodules.rxbuffer = SyncFIFOBuffered(8, 512)


        # Dispatch and response flops for host communication.
        request = Signal(8)
        response = Signal(8)
        # Generic counter used by a bunch of states.
        # TODO: share the logic that populates this for sending/receiving
        # words.
        counter = Signal(max=120000)

        # Target CLK divider.
        tclk_divider = Signal(max=120, reset=4)
        tclk_counter = Signal(max=121)
        self.sync += [
            If(tclk_counter == tclk_divider,
                tclk_counter.eq(0),
                target.tclk.eq(~target.tclk),
            ).Else(
                tclk_counter.eq(tclk_counter + 1),
            )
        ]

        # Target serial CLK divider, used by the *_EDGE states in the FSM.
        sclk_divider = Signal(max=1024, reset=1023)

        # Target busy timer.
        timer = Signal(32)
        timer_running = Signal(reset=0)
        last_busy = Signal()
        self.sync += last_busy.eq(target_busy)
        self.sync += \
            If(~timer_running,
                If((~last_busy) & target_busy,
                    timer_running.eq(1),
                    timer.eq(0),
                )
            ).Elif(~target_busy,
                timer_running.eq(0),
            ).Else(
                timer.eq(timer + 1),
            )

        
        # Main state machine.
        self.submodules.fsm = FSM(reset_state='IDLE')
        self.fsm.act('IDLE',
            If(self.uart_rx.readable,
                NextState('DISPATCH'),
                NextValue(request, self.uart_rx.dout),
            ),
        )
        self.fsm.act('DISPATCH',
            Case(request, {
                # Get API version of bitstream.
                ord('v'): [
                    NextState('RESPOND_BYTE'),
                    NextValue(response, ord('0')),
                ],
                # Flush both FIFOs.
                ord('f'): [
                    NextState('FIFO_FLUSH'),
                ],
                # Reset target.
                ord('r'): [
                    NextState('RESET_TARGET'),
                    NextValue(target.rst, 0),
                    NextValue(counter, 119999),
                ],
                # Write byte to FIFO.
                ord('w'): [
                    NextState('FIFO_WRITE'),
                ],
                # Perform transaction with target.
                ord('W'): [
                    NextState('SEND_START'),
                ],
                # Read bytes from FIFO.
                ord('R'): [
                    NextState('FIFO_READ_START'),
                    NextValue(counter, 3),
                ],
                # Get timer value.
                ord('t'): [
                    NextState('GET_TIMER'),
                    NextValue(counter, 0),
                ],
                # Get timer status.
                ord('T'): [
                    NextState('RESPOND_BYTE'),
                    If(timer_running,
                        NextValue(response, ord('r'))
                    ).Else(
                        NextValue(response, ord('s'))
                    )
                ],
                # Set target clock.
                ord('s'): [
                    NextState('SET_TCLK'),
                ],
                # Set target serial clock.
                ord('S'): [
                    NextState('SET_SCLK'),
                    NextValue(counter, 1),
                ],
                # Default handler.
                'default': [
                    NextState('RESPOND_BYTE'),
                    NextValue(response, ord('?')),
                ],
            })
        )
        self.fsm.act('RESET_TARGET',
            If(counter == 0,
                NextValue(target.rst, 1),
                NextValue(target.sclk, 1),
                NextValue(response, ord('.')),
                NextState('RESPOND_BYTE'),
            ).Else(
                NextValue(counter, counter-1),
            )
        )
        self.fsm.act('GET_TIMER',
            If(counter == 3,
                NextState('IDLE'),
            ),
            NextValue(counter, counter+1),
        )
        self.fsm.act('FIFO_WRITE',
            If(self.uart_rx.readable,
                If(self.txbuffer.writable,
                    NextValue(response, ord('.')),
                    NextState('RESPOND_BYTE'),
                ).Else(
                    NextValue(response, ord('!')),
                    NextState('RESPOND_BYTE'),
                )
            )
        )
        self.fsm.act('SET_TCLK',
            If(self.uart_rx.readable,
                NextValue(tclk_divider, self.uart_rx.dout),
                NextValue(response, ord('.')),
                NextState('RESPOND_BYTE'),
            )
        )
        self.fsm.act('SET_SCLK',
            If(self.uart_rx.readable,
                NextValue(sclk_divider, (sclk_divider >> 8) | (self.uart_rx.dout << 8)),
                If(counter == 0,
                    NextValue(response, ord('.')),
                    NextState('RESPOND_BYTE'),
                ).Else(
                    NextValue(counter, counter-1),
                )
            )
        )

        # Transaction signals.
        # Byte to be sent to target.
        send_byte = Signal(8)
        # Byte being received from target.
        receive_byte = Signal(8)
        # Index into both send and receive bytes.
        bit_index = Signal(max=8)
        # Downounter for clock rise/fall edges, set to sclk.
        bit_counter = Signal(max=1024)
        # Rising/falling edge over, move to next state.
        bit_strobe = Signal()
        self.comb += bit_strobe.eq(bit_counter == 0)
        next_bit = Signal()

        self.fsm.act('SEND_START',
            NextState('SEND_PREPARE'),
            NextValue(bit_index, 0),
        )
        # Prepare next byte to send or finish transaction.
        self.fsm.act('SEND_PREPARE',
            If(self.txbuffer.readable,
                NextValue(send_byte, self.txbuffer.dout),
                NextState('SEND_WAIT'),
            ).Else(
                NextValue(response, ord('.')),
                NextState('RESPOND_BYTE'),
            )
        )

        # Wait for target to not be busy.
        self.fsm.act('SEND_WAIT',
            If(~target_busy,
                NextValue(bit_counter, sclk_divider),
                NextState('SEND_FALLING'),
            )
        )

        # Downcount bit_counter, send data to target.
        self.fsm.act('SEND_FALLING',
            If(bit_counter == 0,
                NextValue(target.sclk, 0),
                NextState('SEND_RISING'),
                NextValue(bit_counter, sclk_divider),
                NextValue(target.rxd, (send_byte >> bit_index) & 1),
            ).Else(
                NextValue(bit_counter, bit_counter-1),
            )
        )
        # Downcount bit_counter, receive data from target.
        self.fsm.act('SEND_RISING',
            If(bit_counter == 0,
                NextValue(receive_byte, (target_txd << 7) | (receive_byte >> 1)),
                NextValue(target.sclk, 1),
                If(bit_index == 7,
                    NextValue(bit_index, 0),
                    NextState('SEND_WRITEBACK'),
                ).Else(
                    NextValue(bit_index, bit_index+1),
                    NextState('SEND_FALLING'),
                    NextValue(bit_counter, sclk_divider),
                )
            ).Else(
                NextValue(bit_counter, bit_counter-1),
            )
        )
        # Write received byte to read FIFO.
        self.fsm.act('SEND_WRITEBACK',
            NextState('SEND_PREPARE')
        )

        # Downcounter for requested bytes to read from FIFO.
        fifo_read_counter = Signal(32)

        # Set downcounter based on host request.
        self.fsm.act('FIFO_READ_START',
            If(self.uart_rx.readable,
                If(counter == 0,
                    NextState('FIFO_READ'),
                ).Else(
                    NextValue(counter, counter-1)
                ),
                NextValue(fifo_read_counter, (fifo_read_counter >> 8) | (self.uart_rx.dout << 24))
            )
        )

        # Downcount fifo_read_counter, send FIFO bytes to host.
        self.fsm.act('FIFO_READ',
            If(fifo_read_counter == 0,
                NextState('IDLE'),
            ).Else(
                NextValue(fifo_read_counter, fifo_read_counter-1),
            )
        )
        # Whether the read FIFO should emit a byte - somewhat of a hack.
        fifo_read = Signal()
        self.comb += fifo_read.eq(self.fsm.ongoing('FIFO_READ') & (fifo_read_counter != 0))

        self.fsm.act('FIFO_FLUSH',
            If((~self.rxbuffer.readable) & (~self.txbuffer.readable),
                NextValue(response, ord('.')),
                NextState('RESPOND_BYTE'),
            )
        )

        # Enables and data connections for FIFOs.
        self.comb += [
            self.txbuffer.we.eq(
                self.fsm.ongoing('FIFO_WRITE') & self.uart_rx.readable
            ),
            self.txbuffer.re.eq(
                self.fsm.ongoing('SEND_PREPARE') |
                self.fsm.ongoing('FIFO_FLUSH')
            ),
            self.txbuffer.din.eq(self.uart_rx.dout),

            self.rxbuffer.we.eq(self.fsm.ongoing('SEND_WRITEBACK')),
            self.rxbuffer.re.eq(
                fifo_read |
                self.fsm.ongoing('FIFO_FLUSH')
            ),
            self.rxbuffer.din.eq(receive_byte),
        ]

        # Generic 1-byte response state.
        self.fsm.act('RESPOND_BYTE',
            If(self.uart_tx.writable,
                NextState('IDLE'),
            ),
        )

        # Host UART enables.
        self.comb += [
            self.uart_rx.re.eq(
                self.fsm.ongoing('IDLE') |
                self.fsm.ongoing('FIFO_WRITE') |
                self.fsm.ongoing('SET_TCLK') |
                self.fsm.ongoing('SET_SCLK') |
                self.fsm.ongoing('FIFO_READ_START')
            ),
            self.uart_tx.we.eq(
                self.fsm.ongoing('RESPOND_BYTE') |
                self.fsm.ongoing('GET_TIMER') |
                fifo_read
            ),
            If(self.fsm.ongoing('RESPOND_BYTE'),
                self.uart_tx.din.eq(response),
            ).Elif(self.fsm.ongoing('GET_TIMER'),
                self.uart_tx.din.eq(timer >> (counter * 8)),
            ).Elif(fifo_read,
                If(self.rxbuffer.readable,
                    self.uart_tx.din.eq(self.rxbuffer.dout),
                ).Else(
                    self.uart_tx.din.eq(0xff),
                ),
            )
        ]

        # Expose Host UART on debug pins.
        self.comb += [
            platform.request('debug').eq(self.uart_tx.tx),
            platform.request('debug').eq(self.uart_rx.rx),
        ]


def main():
    plat = icestick.Platform()
    debugpins = [119, 118, 117, 116, 115, 114, 113, 112]
    plat.add_extension([
        ('sio', 0,
            Subsignal('rst', Pins('48')),
            Subsignal('txd', Pins('56')),
            Subsignal('rxd', Pins('60')),
            Subsignal('sclk', Pins('61')),
            Subsignal('busy', Pins('62')),
            Subsignal('tclk', Pins('47')),
            IOStandard('LVCMOS33'),
        ),
    ] + [
        ('debug', i, Pins(str(p)), IOStandard('LVCMOS33')) for i, p in enumerate(debugpins)
    ])
    # Randomize seed because it doesn't get routed with the default of 1.
    plat.toolchain.pnr_opt = "-q -r"
    plat.build(Top(plat))
    plat.create_programmer().flash(0, 'build/top.bin')


if __name__ == '__main__':
    sys.exit(main() or 0)
