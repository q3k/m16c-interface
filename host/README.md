Host software
=============

You'll need Python 2.7 and pyserial.

Run `main.py --help` to see available options.

This expects the adapter to be present under /dev/ttyUSB1. If that's not true for your setup, use the -p option.

PIN Cracking
------------

Connect the target and run the 'crack' command.

    q3k@anathema ~/Projects/renesasif/host $ sudo python2 main.py crack
    Connected to adapter version 0
    Connected to target version VER.1.01
    Cracking byte 1/7...
    [...]
    Finished. Code: [77, ...], 4ddeadbeefcafe

You'll have to powercycle the target, otherwise it won't unlock, even with the correct code.

Flash dumping
-------------

Connect the target and run the 'dump' command.

    q3k@anathema ~/Projects/renesasif/host $ sudo python2 main.py dump -o /tmp/bin.bin -c 4ddeadbeefcafe
    Connected to adapter version 0
    Connected to target version VER.1.01
    Target unlocked.
    Writing pages e00-fff to /tmp/bin.bin...
    q3k@anathema ~/Projects/renesasif/host $ strings /tmp/bin.bin | grep -i tosh
    (C)Copyright 2002 Toshiba Corporation. All Rights Reserved.


