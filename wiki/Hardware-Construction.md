# Receiver Hardware Setup

The receiver setup is similar to that of the DAQ side, but omitting the GPS and CAN boards. Additionally, rather than connecting to the puck aerial mounted in the sidepod, the receiver connects via two adapters (tiny to medium, medium to large) to the long white cylindrical antenna with model number starting with OMB. This gets a signal within line-of-sight most reliably. As of FS26, from the stands I was able to get reliable signal in the close half of the course. Increasing range would be good for future progress. Please update this wiki if so.

## GPIO Setup

The LR1121 support layer binds the radio context to these pins:

| Signal | GPIO |
| --- | --- |
| RESET | GPIO 8 |
| BUSY | GPIO 9 |
| CLK | GPIO 10 |
| MOSI | GPIO 11 |
| MISO | GPIO 12 |
| CS | GPIO 13 |
| IRQ | GPIO 14 |
| LED | GPIO 25 |