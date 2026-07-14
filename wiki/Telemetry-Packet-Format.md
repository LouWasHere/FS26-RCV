# Telemetry Packet Format

The receiver expects one combined telemetry packet with a fixed payload size of 60 bytes.

## Packet identity

- `magic` must equal `0x46533236`, which is the ASCII encoding of `FS26`.
- The radio payload length is configured as `PAYLOAD_LENGTH = 60`.
- The receiver treats any packet with the wrong magic value as invalid.

## Field order

The packed structure is laid out in this order:

1. `magic`
2. GPS data: `latitude`, `longitude`, `gps_speed_kph`, `altitude`, `satellites`, `fix_valid`
3. Engine data: `rpm`, `engine_temp`, `tps`
4. Pressure and electrical data: `oil_pressure`, `fuel_pressure`, `brake_pressure`, `battery_voltage`
5. Wheel speeds: `wheel_speed_fr`, `wheel_speed_fl`, `wheel_speed_rr`, `wheel_speed_rl`
6. Dynamics: `g_force_lateral`, `heading`
7. Metadata: `tx_count`, `can_frame_count`

## Why the packing matters

The C receiver casts the raw radio buffer directly into the packed structure, so field sizes and ordering must match the transmitter exactly. Any layout change requires updating both the transmitter and the dashboard parser.