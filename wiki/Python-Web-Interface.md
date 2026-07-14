# Python Web Interface

`fs26_interface.py` is a Dash app that turns the receiver’s serial output into a live telemetry dashboard.

## What it reads

The app listens to the Pico over serial and parses the receiver’s formatted log lines.

It looks for:

- GPS position and speed lines
- Engine and drivetrain lines
- Pressure and voltage lines
- Wheel speed lines
- Dynamics and link-quality lines

When the app sees the radio quality line, it stores a complete sample and appends it to the live buffers.

## How the data is stored

The dashboard keeps two layers of state:

- `latest` holds the most recent value for each field.
- `telemetry_data` stores a bounded history for plots and replay.

That split lets the UI show both the current reading and the recent trend without needing to re-parse the serial stream.

## Dashboard layout

The page is organized into a small set of sections:

- Connection status
- GPS
- Engine and drivetrain
- Pressures
- Wheel speeds
- Dynamics and radio

Below the cards, the app draws:

- A track map from latitude and longitude history
- A speed chart
- A radio quality chart for RSSI and SNR

## Replay and recording

The UI can record samples to CSV and replay them later.

- Recording writes the current snapshot into a timestamped file in `recordings/`.
- Replay loads a CSV, restores the buffered history, and steps through rows at the selected speed.

## Parser contract

The parser expects the receiver’s labels to stay consistent, especially the GPS, engine, pressure, wheel, dynamics, and RSSI/SNR lines. If the C output changes, this file is the first place that needs an update.