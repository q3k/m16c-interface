Adapter implementation on iCEStick
==================================

You'll need an iCEStick, the icestorm toolchain (yosys, arachne, icestorm) and python 3.5.

    python3.5 -m venv venv
    venv/bin/pip install -r requirements.txt

Run top.py to build and flash the RTL onto the iCEStick.

    venv/bin/python top.py

Connection to target
--------------------

The target Renesas microcotntroller should be connected to the following iCEStick pins:

 - Reset: 48
 - TXD: 56
 - RXD: 60
 - SCLK: 61
 - Busy: 62
 - Xin: 47
 - Xout: disconnected

The target should be run at 3v3. It can be powered from the built-in regulator on the iCEStick.

Protocol & Architecture
-----------------------

The adapter uses a simple/simplistic serial-based protocol. See the state machine in main.py. It does not implement any application layer code for the Simple Serial I/O - that is done by the host software.

The main component of the logic are two FIFOs for command input and data results, and a state machine to read/write data to those FIFOs from UART, and to perform a Serial I/O transaction with the target.
