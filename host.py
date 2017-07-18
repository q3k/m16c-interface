import struct
import sys
import time

import serial

s = serial.Serial('/dev/ttyUSB1', 1200000, timeout=3)

def flush():
    """Flush FPGA FIFO buffers."""
    s.write('f')
    if s.read() != '.':
        raise Exception('Synchronization error.')

def blocks(data, size=64):
    for i in range(0, len(data), size):
        yield data[i:i+size]

def transaction(buf, want):
    """Perform a Serial I/O transaction to the target MCU."""
    #print '->', buf.encode('hex')
    flush()
    cmdlen = len(buf)
    buf += '\xff' * want
    for block in blocks(buf):
        for c in block:
            s.write('w' + c)
        d = s.read(len(block))
        if d != '.' * len(block):
            raise Exception('Synchronization error: {}'.format(d))
    s.write('W')
    if s.read() != '.':
        raise Exception('Synchronization error.')

    s.write('R' + struct.pack('<I', cmdlen))
    d = s.read(cmdlen)

    out = ""
    s.write('R' + struct.pack('<I', want))
    out = s.read(want)

    #print '<-', out.encode('hex')
    return out

def version():
    """Get version of FPGA bitstream."""
    s.write('v')
    return int(s.read())

def reset():
    """Reset the target MCU."""
    s.write('r')
    if s.read() != '.':
        raise Exception('Synchronization error.')

def timer():
    while True:
        s.write('T')
        if s.read() == 's':
            break
    s.write('t')
    return struct.unpack('<I', s.read(4))[0]

def set_tclk(val):
    s.write('s' + chr(val))
    if s.read() != '.':
        raise Exception('Synchronization error.')

if version() != 0:
    raise Exception('Invalid version.')
print 'Connected to programmer.'

reset()
print 'Reset target.'

set_tclk(4)

sys.exit(0)


version = transaction('fb'.decode('hex'), 8)
print 'Version:', version

status = transaction('\x70', 2)
print 'Lock status:', (ord(status[1]) >> 2) & 3

#code = []
#while len(code) != 7:
#    tries = {}
#    for i in range(256):
#        times = []
#        repeat = 3
#        for j in range(repeat):
#            until = ''.join(chr(c) for c in code)
#            rest = '\xde' * (6 - len(code))
#            dat = 'f5dfff0f07'.decode('hex') + until + chr(i) + rest
#            transaction(dat, 0)
#            times.append(timer())
#        median = sorted(times)[repeat/2]
#        print '{:02x} {}'.format(i, median)
#        tries[i] = median
#
#    longest = 0
#    longest_b = None
#    for b, t in tries.iteritems():
#        if len(code) == 6:
#            if t < longest or longest == 0:
#                longest = t
#                longest_b = b
#        else:
#            if t > longest:
#                longest = t
#                longest_b = b
#    
#    code.append(longest_b)
#    print code

transaction('f5dfff0f07'.decode('hex') + ''.join(chr(c) for c in [77, 44, 232, 97, 25, 125, 196]), 0)

status = transaction('\x70', 2)
print 'Lock status:', (ord(status[1]) >> 2) & 3

print 'Dumping...'
with open('out.bin', 'w') as f:
    for i in range(0x0e00, 0x1000):
        sys.stdout.write('{:04x}00-{:04x}ff...\r'.format(i, i))
        sys.stdout.flush()
        page = transaction('\xff' + struct.pack('<H', i), 256)
        f.write(page)
        time.sleep(0.01)
    print 'Done.'

#transaction('FA08002E71336b6368756a75'.decode('hex'), 0)


version = transaction('\xfb', 8)
print 'Version:', version

