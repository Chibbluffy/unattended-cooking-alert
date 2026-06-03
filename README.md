# ThermalWatch

An open-source stove monitor for elderly or forgetful family members. Uses a TOPDON TC001 thermal camera connected to a Raspberry Pi Zero W to detect when a gas or electric stove burner is left on unattended, then sends a Discord alert and speaks an announcement through the phone.

The Pi reads raw thermal frames from the camera and forwards anything above a temperature threshold to a phone over UDP. The phone handles all detection logic (burner on? person present? how long unattended?) and fires the alert. Nothing runs in the cloud. Everything stays on your local network.

## How It Works

```
TC001 thermal camera (USB)
        |
Raspberry Pi Zero W  [pi_files/]
  - reads raw frames at 2fps
  - checks if any pixel exceeds threshold (default 100C)
  - if hot: sends temperature array to phone over UDP
  - if not hot: sends lightweight heartbeat so phone knows Pi is alive
        | (local WiFi only)
Android phone running Termux  [phone_files/]
  - receives temperature frames
  - detects burner on (high temp region)
  - detects person present (human-temperature blob)
  - if burner on + no person for 5 minutes: Discord alert + audible alarm
  - audible alarm repeats every 30 seconds until someone comes into view
  - alarm stops immediately when a person is detected
  - if Pi goes offline: Discord alert
```

Design principles:
- Event-driven - no data sent when nothing is hot
- Silent during normal operation
- SD card friendly - logs go to RAM, swap disabled, filesystem writes minimized
- No cloud dependency - everything runs locally; Discord is the only outbound call

## Hardware

- Raspberry Pi Zero W
- TOPDON TC001 thermal camera (~$150-180)
- Micro USB OTG adapter (to connect the TC001 to the Pi's USB port)
- MicroSD card (8GB+)
- Reliable 5V/2A micro USB power supply (quality matters for always-on use)
- Android phone with Termux installed
- Both devices on the same WiFi network

> The TC001 plugs into the Pi via OTG adapter. Connect to the port labeled **USB**, not **PWR IN**. The Pi Zero W has two micro USB ports - this is a common mistake.

## Setup

1. Set up the Pi: [`pi_files/README.md`](pi_files/README.md)
2. Set up the phone: [`phone_files/README.md`](phone_files/README.md)
3. Make sure both devices are on the same WiFi network and their `UDP_PORT` values match

## Credits

- TC001 frame format reverse-engineered by [LeoDJ](https://github.com/LeoDJ/P2Pro-Viewer) (originally for the InfiRay P2 Pro)
- Python implementation reference: [PyThermalCamera](https://github.com/leswright1977/PyThermalCamera) by Les Wright

## License

MIT - use it, modify it, share it.
