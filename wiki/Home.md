# FS26 Receiver Wiki

This wiki is a short guide to the receiver side of the FS26 telemetry stack.

## Pages

- [Telemetry packet format](Telemetry-Packet-Format.md)
- [C receiver code](C-Receiver-Code.md)
- [Python web interface](Python-Web-Interface.md)

## What lives where

- The C receiver in `FS26-RCV.c` listens for one packed 60-byte telemetry frame and prints it as a structured status block.
- The Python dashboard in `fs26_interface.py` reads those printed lines, stores the latest values, and renders the live cards, map, and graphs.
- The packet layout is shared between both sides, so the field order and sizes must stay aligned.