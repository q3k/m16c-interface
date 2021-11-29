Renesas M16C programmer
=======================

This is the code for a Renesas M16C SerialIO programmer, based on an iCEStick FPGA devboard and Python host software.

Its most interesting feature is being able to crack the security PIN of the bootloader using a simple timing attack on the busy line.

To build and connect the adapter to the target, see adapter/README.md.

To run the host software to dump the target flash, see host/README.md.

Supported targets
-----------------

The following targets are know to work with this project:

| Device      | Can dump flash memory | Can recover PIN | Tested by     |
|-------------|-----------------------|-----------------|---------------|
| M306K9FCLRP | YES                   | YES             | q3k, joegrand |

License
-------

All the code in this repository is licensed under a BSD-style 2-clause license.
