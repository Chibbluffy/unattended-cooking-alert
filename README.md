# ThermalWatch 🔥

An open-source stove monitoring system for elderly or forgetful family members. Uses a TOPDON TC001 thermal camera connected to a Raspberry Pi Zero W to detect when a gas or electric stove burner is left on unattended, then sends an alert via Discord.

The Pi does one job: read raw thermal frames from the camera and forward anything above a temperature threshold to a phone over UDP. The phone does all the detection logic — burner on? person present? how long unattended? — and fires the alert. Nothing runs in the cloud. Everything stays on your local network.

---

## How It Works

```
TC001 thermal camera (USB)
        ↓
Raspberry Pi Zero W  [/pi]
  • reads raw frames at 2fps
  • checks if any pixel exceeds threshold (default 100°C)
  • if hot: sends temperature array to phone over UDP
  • if not: sends lightweight heartbeat so phone knows Pi is alive
        ↓ (local WiFi only)
Android phone running Termux  [/phone]
  • receives temperature frames
  • detects burner on (high temp region)
  • detects person present (human-temperature blob)
  • if burner on + no person for 5 minutes → Discord alert
  • if Pi goes offline → Discord alert
```

**Design principles:**
- Event-driven — no data sent when nothing is hot
- Silent during normal operation — the Pi logs nothing unless something goes wrong
- SD card friendly — logs go to RAM by default, swap disabled, filesystem writes minimized
- No cloud dependency — everything runs locally, Discord is the only outbound call and only fires on alerts

---

## Hardware Required

- Raspberry Pi Zero W
- TOPDON TC001 thermal camera (~$150–180)
- Micro USB OTG adapter (to connect TC001 to the Pi's USB port)
- MicroSD card (8GB+)
- Reliable 5V/2A micro USB power supply (quality matters for always-on use)
- Android phone with Termux installed (the processing device)
- Both devices on the same WiFi network

> **Note:** The TC001 plugs into the Pi via OTG adapter. Connect to the port labeled **USB**, not **PWR IN**. The Pi has two micro USB ports — this is a common gotcha.

---

## Repository Structure

```
thermalwatch/
├── README.md               # you are here
├── pi/
│   ├── README.md           # Pi setup and deployment guide
│   ├── config.env          # Pi configuration
│   └── pi_sender.py        # runs on the Raspberry Pi Zero W
└── phone/
    ├── README.md           # Phone setup and deployment guide
    ├── config.env          # Phone configuration
    └── phone_receiver.py   # runs on the Android phone in Termux
```

---

## Quick Start

1. **Set up the Pi** — see [`/pi/README.md`](pi/README.md)
2. **Set up the phone** — see [`/phone/README.md`](phone/README.md)
3. **Configure Discord** — create a webhook in any Discord server/channel you control and paste the URL into `phone/config.env`
4. Make sure both devices are on the same WiFi network and their configs agree on `UDP_PORT`

---

## How Person Detection Works

The phone looks for a blob of pixels in the human body temperature range (`PERSON_TEMP_MIN` to `PERSON_TEMP_MAX`, default 28–40°C) that meets a minimum size (`PERSON_MIN_PIXELS`, default 30 pixels). If that blob is present, a person is considered in frame and the inactivity timer resets.

This is a simple heuristic that works well for a fixed-angle kitchen camera with a clear view of the cooking area. Tune `PERSON_TEMP_MIN`, `PERSON_TEMP_MAX`, and `PERSON_MIN_PIXELS` in `phone/config.env` based on your specific environment.

---

## Credit

- TC001 frame format reverse-engineered by [LeoDJ](https://github.com/LeoDJ/P2Pro-Viewer) (originally for the InfiRay P2 Pro)
- Python implementation reference: [PyThermalCamera](https://github.com/leswright1977/PyThermalCamera) by Les Wright

---

## License

MIT — use it, modify it, share it.
