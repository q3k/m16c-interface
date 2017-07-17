import sys

from migen import *
from migen.genlib.fifo import SyncFIFO
from migen.build.generic_platform import Subsignal, Pins, IOStandard
from migen.build.platforms import icestick

import uart

class Top(Module):
    CLKFREQ = 12000000
    BAUDRATE = 1200000

    def __init__(self, platform):
        self.submodules.uart_rx = uart.RXFIFO(self.CLKFREQ, self.BAUDRATE)
        self.submodules.uart_tx = uart.TXFIFO(self.CLKFREQ, self.BAUDRATE)
        serial = platform.request('serial')
        self.comb += [
            serial.tx.eq(self.uart_tx.tx),
            self.uart_rx.rx.eq(serial.rx),
        ]

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

        self.comb += [
            platform.request('user_led').eq(target.rxd),
            platform.request('user_led').eq(target.txd),
            platform.request('user_led').eq(target.busy),
        ]

        self.submodules.txbuffer = SyncFIFO(8, 512)
        self.submodules.rxbuffer = SyncFIFO(8, 512)

        request = Signal(8)
        response = Signal(8)
        counter = Signal(max=120000)

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

        self.submodules.fsm = FSM(reset_state='IDLE')
        self.fsm.act('IDLE',
            If(self.uart_rx.readable,
                NextState('DISPATCH'),
                NextValue(request, self.uart_rx.dout),
            ),
        )
        self.fsm.act('DISPATCH',
            Case(request, {
                ord('v'): [
                    NextState('RESPOND'),
                    NextValue(response, ord('0')),
                ],
                ord('f'): [
                    NextState('FLUSH'),
                ],
                ord('r'): [
                    NextState('RESET_TARGET'),
                    NextValue(target.rst, 0),
                    NextValue(counter, 119999),
                ],
                ord('w'): [
                    NextState('STUFF_WRITE'),
                ],
                ord('W'): [
                    NextState('SEND_START'),
                ],
                ord('R'): [
                    NextState('READBACK'),
                ],
                ord('t'): [
                    NextState('TIMER'),
                    NextValue(counter, 0),
                ],
                ord('T'): [
                    NextState('RESPOND'),
                    If(timer_running,
                        NextValue(response, ord('r'))
                    ).Else(
                        NextValue(response, ord('s'))
                    )
                ],
                ord('s'): [
                    NextState('SET_TCLK'),
                ],
                'default': [
                    NextState('RESPOND'),
                    NextValue(response, ord('?')),
                ],
            })
        )
        self.fsm.act('RESET_TARGET',
            If(counter == 0,
                NextValue(target.rst, 1),
                NextValue(target.sclk, 1),
                NextValue(response, ord('.')),
                NextState('RESPOND'),
            ).Else(
                NextValue(counter, counter-1),
            )
        )
        self.fsm.act('TIMER',
            If(counter == 3,
                NextState('IDLE'),
            ),
            NextValue(counter, counter+1),
        )
        self.fsm.act('STUFF_WRITE',
            If(self.uart_rx.readable,
                If(self.txbuffer.writable,
                    NextValue(response, ord('.')),
                    NextState('RESPOND'),
                ).Else(
                    NextValue(response, ord('!')),
                    NextState('RESPOND'),
                )
            )
        )
        self.fsm.act('SET_TCLK',
            If(self.uart_rx.readable,
                NextValue(tclk_divider, self.uart_rx.dout),
                NextValue(response, ord('.')),
                NextState('RESPOND'),
            )
        )

        send_byte = Signal(8)
        receive_byte = Signal(8)
        bit_index = Signal(max=8)
        bit_counter = Signal(max=1024)
        bit_strobe = Signal()
        next_bit = Signal()
        self.comb += bit_strobe.eq(bit_counter == 0)

        self.fsm.act('SEND_START',
            NextState('SEND_PREPARE'),
            NextValue(bit_index, 0),
        )
        self.fsm.act('SEND_PREPARE',
            If(self.txbuffer.readable,
                NextValue(send_byte, self.txbuffer.dout),
                NextState('SEND_WAIT'),
            ).Else(
                NextValue(response, ord('.')),
                NextState('RESPOND'),
            )
        )

        self.fsm.act('SEND_WAIT',
            If(~target_busy,
                NextValue(bit_counter, 1023),
                NextState('SEND_FALLING'),
            )
        )
        self.fsm.act('SEND_FALLING',
            If(bit_counter == 0,
                NextValue(target.sclk, 0),
                NextState('SEND_RISING'),
                NextValue(bit_counter, 1023),
                NextValue(target.rxd, (send_byte >> bit_index) & 1),
            ).Else(
                NextValue(bit_counter, bit_counter-1),
            )
        )
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
                    NextValue(bit_counter, 1023),
                )
            ).Else(
                NextValue(bit_counter, bit_counter-1),
            )
        )
        self.fsm.act('SEND_WRITEBACK',
            NextState('SEND_PREPARE')
        )
        self.fsm.act('READBACK',
            If(self.rxbuffer.readable,
                NextValue(response, self.rxbuffer.dout),
            ).Else(
                NextValue(response, ord('!')),
            ),
            NextState('RESPOND'),
        )

        self.fsm.act('FLUSH',
            If((~self.rxbuffer.readable) & (~self.txbuffer.readable),
                NextValue(response, ord('.')),
                NextState('RESPOND'),
            )
        )

        self.comb += [
            self.txbuffer.we.eq(
                self.fsm.ongoing('STUFF_WRITE') & self.uart_rx.readable
            ),
            self.txbuffer.re.eq(
                self.fsm.ongoing('SEND_PREPARE') |
                self.fsm.ongoing('FLUSH')
            ),
            self.txbuffer.din.eq(self.uart_rx.dout),

            self.rxbuffer.we.eq(self.fsm.ongoing('SEND_WRITEBACK')),
            self.rxbuffer.re.eq(
                self.fsm.ongoing('READBACK') |
                self.fsm.ongoing('FLUSH')
            ),
            self.rxbuffer.din.eq(receive_byte),
        ]
        self.fsm.act('RESPOND',
            If(self.uart_tx.writable,
                NextState('IDLE'),
            ),
        )
        self.comb += [
            self.uart_rx.re.eq(
                self.fsm.ongoing('IDLE') |
                self.fsm.ongoing('STUFF_WRITE') |
                self.fsm.ongoing('SET_TCLK')
            ),
            self.uart_tx.we.eq(
                self.fsm.ongoing('RESPOND') |
                self.fsm.ongoing('TIMER')
            ),
            If(self.fsm.ongoing('RESPOND'),
                self.uart_tx.din.eq(response),
            ).Elif(self.fsm.ongoing('TIMER'),
                self.uart_tx.din.eq(timer >> (counter * 8)),
            ),
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
    plat.build(Top(plat))
    plat.create_programmer().flash(0, 'build/top.bin')


if __name__ == '__main__':
    sys.exit(main() or 0)
