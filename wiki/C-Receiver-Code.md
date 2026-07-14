# C Receiver Code

`FS26-RCV.c` is the Pico-side program that listens for telemetry over the LR1121 radio and prints one formatted status block per good packet.

## Main flow

1. Initialize stdio and the LR1121 radio.
2. Configure the radio for continuous RX.
3. Wait for a packet.
4. Validate the packet size and magic value.
5. Print the decoded telemetry fields in a consistent text layout.

## Packet handling

The code reads the radio buffer into `rx_buffer`, then interprets it as a `combined_telemetry_packet_t` when enough bytes have arrived.

Important checks:

- `rx_length` must be at least `sizeof(combined_telemetry_packet_t)`.
- `packet->magic` must equal `TELEMETRY_MAGIC`.
- If either check fails, the packet is ignored.

## Printed output

Successful packets are printed as a box with these sections:

- GPS position and motion
- Engine and drivetrain data
- Fuel, oil, brake, and battery values
- Wheel speeds
- Lateral acceleration and heading
- Transmission counters and radio quality (`RSSI`, `SNR`)

The Python dashboard depends on these labels, so the wording should stay stable unless the parser is updated too.

## Receive mode

The receiver uses the LR1121 RTC-step RX API for continuous mode. That avoids the overflow problem that happens when the continuous receive constant is passed through the millisecond wrapper.

## Practical rule

If you change the C print format, update the Python parser at the same time. If you change the packet structure, update the transmitter, receiver, and dashboard together.