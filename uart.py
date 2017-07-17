from migen import Module, Signal, If, FSM, NextState, Cat, NextValue
from migen.genlib.fifo import SyncFIFO

class RX(Module):
    def __init__(self, clk_freq, baud_rate):
        self.data = Signal(8)
        self.ready = Signal()
        self.ack = Signal()
        self.error = Signal()
        self.rx = Signal(reset=1)

        divisor = clk_freq // baud_rate

        rx_counter = Signal(max=divisor)
        self.rx_strobe = Signal()
        self.comb += self.rx_strobe.eq(rx_counter == 0)
        self.sync += \
                If(rx_counter == 0,
                    rx_counter.eq(divisor - 1)
                ).Else(
                    rx_counter.eq(rx_counter - 1)
                )

        self.rx_bitno = Signal(3)
        self.submodules.rx_fsm = FSM(reset_state='IDLE')
        self.rx_fsm.act('IDLE',
            If(~self.rx,
                NextValue(rx_counter, divisor // 2),
                NextState('START')
            )
        )
        self.rx_fsm.act('START',
            If(self.rx_strobe,
                NextState('DATA')
            )
        )
        self.rx_fsm.act('DATA',
            If(self.rx_strobe,
                NextValue(self.data, Cat(self.data[1:8], self.rx)),
                NextValue(self.rx_bitno, self.rx_bitno + 1),
                If(self.rx_bitno == 7,
                    NextState('STOP')
                )
            )
        )
        self.rx_fsm.act('STOP',
            If(self.rx_strobe,
                If(~self.rx,
                    NextState('ERROR')
                ).Else(
                    NextState('FULL'),
                )
            )
        )
        self.rx_fsm.act('FULL',
            self.ready.eq(1),
            If(self.ack,
                NextState('IDLE')
            ).Elif(~self.rx,
                NextState('ERROR')
            )
        )
        self.rx_fsm.act('ERROR',
            self.error.eq(1)
        )

class RXFIFO(Module):
    def __init__(self, clk_freq, baud_rate):
        self.submodules.rxcore = RX(clk_freq, baud_rate)
        self.submodules.fifo = SyncFIFO(8, 1024)
        self.comb += [
            self.fifo.din.eq(self.rxcore.data)
        ]
        self.submodules.fsm = FSM(reset_state='IDLE')
        self.fsm.act('IDLE',
            If(self.rxcore.ready,
                If(self.fifo.writable,
                    self.fifo.we.eq(1),
                ),
                self.rxcore.ack.eq(1),
                NextState('READING'),
            ).Else(
                self.fifo.we.eq(0),
            )
        )
        self.fsm.act('READING',
            self.fifo.we.eq(0),
            self.rxcore.ack.eq(0),
            If(~self.rxcore.ready,
                NextState('IDLE'),
            ),
        )
        self.dout = self.fifo.dout
        self.re = self.fifo.re
        self.readable = self.fifo.readable
        self.rx = self.rxcore.rx

        self.io = { self.dout, self.re, self.readable, self.rx }


class TXFIFO(Module):
    def __init__(self, clk_freq, baud_rate):
        divisor = clk_freq // baud_rate

        self.submodules.fifo = SyncFIFO(8, 1024)
        
        self.din = self.fifo.din
        self.we = self.fifo.we
        self.writable = self.fifo.writable
        self.tx = Signal()
        self.io = { self.din, self.we, self.fifo.writable, self.tx }

        # strobe_counter counts down from divisor to 0, resets automatically
        # or when strobe-start is asserted.
        strobe_counter = Signal(max=divisor)
        strobe_start = Signal()
        strobe = Signal()
        self.comb += strobe.eq(strobe_counter == 0)
        self.sync += (
            If(strobe | strobe_start,
                strobe_counter.eq(divisor - 1),
            ).Else(
                strobe_counter.eq(strobe_counter-1)
            )
        )
        
        # Main bit sender FSM.
        bit_counter = Signal(max=8)
        tx_data = Signal(8)
        self.submodules.fsm = FSM(reset_state='IDLE')
        self.fsm.act('IDLE',
            If(self.fifo.readable,
                NextState('START'),
                NextValue(tx_data, self.fifo.dout),
            )
        )
        self.fsm.act('START',
            If(strobe,
                NextState('DATA'),
                NextValue(bit_counter, 0),
            ),
        )
        self.fsm.act('DATA',
            If(strobe,
                If(bit_counter == 7,
                    NextState('STOP'),
                ).Else(
                    NextValue(bit_counter, bit_counter+1)
                )
            )
        )
        self.fsm.act('STOP',
            If(strobe,
                NextState('IDLE'),
            ),
        )

        self.comb += [
            # FIFO readout.
            self.fifo.re.eq(self.fsm.ongoing('IDLE')),
            # Keep resetting the counter when in IDLE.
            strobe_start.eq(self.fsm.ongoing('IDLE')),
            # TX line logic.
            If(self.fsm.ongoing('START'),
                self.tx.eq(0),
            ).Elif(self.fsm.ongoing('DATA'),
                self.tx.eq((tx_data >> bit_counter) & 1),
            ).Else(
                self.tx.eq(1),
            )
        ]


from migen import ClockDomain, run_simulation

class _TestPads(Module):
    def __init__(self):
        self.rx = Signal(reset=1)
        self.tx = Signal()
        self.io = { self.rx, self.tx }


def _test_tx_fifo(dut, divisor):
    # Give core time to reset.
    for _ in range(16):
        yield

    # push some bytes to the fifo.
    def _bytes(bb):
        yield dut.fifo.we.eq(1)
        for b in bb:
            yield dut.fifo.din.eq(b)
            yield
        yield dut.fifo.we.eq(0)
    yield from _bytes([0xde, 0xad, 0xbe, 0xef])

    for _ in range(700):
        yield

def _test_loopback(dut, divisor):
    for _ in range(16):
        yield
    # push some bytes to the fifo.
    text = 'Migen is weird.'
    def _bytes(bb):
        yield dut.tx.fifo.we.eq(1)
        for b in bb:
            yield dut.tx.fifo.din.eq(ord(b))
            yield
        yield dut.tx.fifo.we.eq(0)
    yield from _bytes(text)

    # See if data has made it.
    received = []
    yield dut.rx.re.eq(1)
    for _ in text:
        while (yield dut.rx.readable) == 0:
            yield
        data = (yield dut.rx.dout)
        received.append(data)
        yield
    received = ''.join(chr(c) for c in received)
    print('Received: "{}"'.format(received))
    assert received == text



def _test_rx(dut, divisor):
    def tick(cb=None):
        for _ in range(divisor):
            if cb is not None:
                yield from cb()
            else:
                yield
    def bit(d, cb=None):
        yield dut.rx.eq(d)
        yield from tick(cb)
    def bits(d, cb=None):
        for dd in d:
            yield from bit(dd, cb)
    def byte(d, cb=None):
        dd = [int(c) for c in ('{:08b}'.format(d))[::-1]]
        yield from bit(0, cb)
        yield from bits(dd, cb)
        yield from bit(1, cb)
    def ack():
        yield dut.ack.eq(1)
        yield
        yield dut.ack.eq(0)

    # Give the receive some time to reset.
    yield from bits([1, 1, 1, 1])
    assert (yield dut.ready) == 0

    # Send a valid byte, expect result.
    yield from byte(0x55)
    yield from tick()
    assert (yield dut.ready) == 1
    assert (yield dut.data) == 0x55
    yield from ack()

    # Measure latency, in cycles, of ready
    yield from byte(0x55)
    for latency in range(10):
        if (yield dut.ready) == 1:
            break
        yield
    else:
        raise Exception('ready latency exceeds 10 clock cycles')
    print('ready latency is {} cycles'.format(latency))
    yield from ack()

    # Send a string od bytes continually, make sure we don't loose any.
    # Since the way generators are used in Migen is weird, we can't really
    # have two concurrent generators block on event changes. So we have to
    # apply some hacks.
    out = []
    last_ready = [False,]
    def getbyte():
        if (yield dut.ready) == 1:
            if not last_ready[-1]:
                out.append((yield dut.data))
                yield from ack()
                last_ready.append(True)
            else:
                yield
        else:
            last_ready.append(False)
            yield

    yield from tick()
    text = 'Lorem ipsum dolor sit amet'
    print('Sending "{}" to RX'.format(text))
    for c in text:
        yield from byte(ord(c), getbyte)
    received = ''.join(chr(c) for c in out)
    print('Received: "{}"'.format(received))
    assert received == text


def _test_rx_fifo(dut, divisor):
    def tick(cb=None):
        for _ in range(divisor):
            if cb is not None:
                yield from cb()
            else:
                yield
    def bit(d, cb=None):
        yield dut.rx.eq(d)
        yield from tick(cb)
    def bits(d, cb=None):
        for dd in d:
            yield from bit(dd, cb)
    def byte(d, cb=None):
        dd = [int(c) for c in ('{:08b}'.format(d))[::-1]]
        yield from bit(0, cb)
        yield from bits(dd, cb)
        yield from bit(1, cb)
    def ack():
        yield dut.ack.eq(1)
        yield
        yield dut.ack.eq(0)

    # Give the receive some time to reset.
    yield from bits([1, 1, 1, 1])

    # Send some data to the RX FIFO.
    text = 'Lorem ipsum dolor sit amet'
    print('Sending "{}" to RXFIFO'.format(text))
    for c in text:
        yield from byte(ord(c))

    # See if data has made it.
    received = []
    yield dut.re.eq(1)
    for _ in text:
        assert (yield dut.readable) == 1
        yield
        data = (yield dut.dout)
        received.append(data)
    received = ''.join(chr(c) for c in received)
    print('Received: "{}"'.format(received))
    assert received == text


from migen.fhdl import verilog

def test_tx():
    # Real values divided by 100 to make for a faster test.
    clk_freq = 12000000//100
    baud_rate = 921600//100
    dut = TXFIFO(clk_freq=clk_freq, baud_rate=baud_rate)
    run_simulation(dut, _test_tx_fifo(dut, clk_freq//baud_rate), vcd_name='vcd/uart-tx-fifo.vcd')

def test_rx():
    # Real values divided by 100 to make for a faster test.
    clk_freq = 12000000//100
    baud_rate = 921600//100
    dut = RX(clk_freq=clk_freq, baud_rate=baud_rate)
    dut.clock_domains.cd_sys = ClockDomain('sys')
    run_simulation(dut, _test_rx(dut, clk_freq//baud_rate), vcd_name='vcd/uart-rx.vcd')

    dut = RXFIFO(clk_freq=clk_freq, baud_rate=baud_rate)
    run_simulation(dut, _test_rx_fifo(dut, clk_freq//baud_rate), vcd_name='vcd/uart-rx-fifo.vcd')

def test_loopback():
    clk_freq = 12000000//100
    baud_rate = 921600//100
    class _Top(Module):
        def __init__(self):
            self.submodules.rx = RXFIFO(clk_freq=clk_freq, baud_rate=baud_rate)
            self.submodules.tx = TXFIFO(clk_freq=clk_freq, baud_rate=baud_rate)
            self.comb += self.rx.rx.eq(self.tx.tx)
    dut = _Top()
    run_simulation(dut, _test_loopback(dut, clk_freq//baud_rate), vcd_name='vcd/uart-loopback.vcd')

import sys

def verilog_gen():
    clk_freq = 12000000
    baud_rate = 921600
    vtop = RXFIFO(clk_freq=clk_freq, baud_rate=baud_rate)
    with open('verilog/uart.v', 'w') as f:
        f.write(str(verilog.convert(vtop, vtop.io)))

if __name__ == '__main__':
    if len(sys.argv) < 2:
        sys.argv += ['test_tx', 'test_rx', 'test_loopback']

    actions = {
        'test_tx': test_tx,
        'test_rx': test_rx,
        'test_loopback': test_loopback,
        'verilog': verilog,
    }

    for a in sys.argv[1:]:
        actions[a]()
