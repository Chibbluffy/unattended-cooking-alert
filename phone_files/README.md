# ThermalWatch — Phone Setup

The phone side receives temperature frames from the Pi over UDP and handles all detection logic — is the burner on? is a person present? how long have they been gone? It fires a Discord alert if the stove is left unattended, and a separate alert if the Pi itself goes offline.

---

## Requirements

- Android phone
- Termux (installed from [F-Droid](https://f-droid.org/) — **not the Play Store version**, which is outdated and unmaintained)
- Termux:Boot from F-Droid (optional, for auto-start on reboot)
- Static IP assigned to the phone via your router's DHCP reservation

---

## Install Dependencies

In Termux:
```bash
pkg update && pkg upgrade
pkg install python
pip install opencv-python numpy requests python-dotenv
```

---

## Configuration

Edit `config.env` before deploying:

| Setting | Default | Description |
|---|---|---|
| `UDP_PORT` | `5000` | Must match `UDP_PORT` in pi's `config.env` |
| `INACTIVITY_TIMEOUT` | `300` | Seconds before alert fires (300 = 5 min) |
| `DISCORD_WEBHOOK_URL` | *(unset)* | Your Discord webhook URL |
| `PERSON_TEMP_MIN` | `28` | °C — lower bound of human body temp range |
| `PERSON_TEMP_MAX` | `40` | °C — upper bound of human body temp range |
| `PERSON_MIN_PIXELS` | `30` | Minimum pixel blob size to count as a person |

**Tuning tips:**
- If your person isn't being detected, lower `PERSON_TEMP_MIN` slightly
- If warm objects cause false detections, raise `PERSON_MIN_PIXELS`
- If alerts fire too quickly or too slowly, adjust `INACTIVITY_TIMEOUT`

---

## Set Up Discord Webhook

1. Open Discord and go to a server you control (or create one just for alerts)
2. Pick a channel → **Edit Channel → Integrations → Webhooks → New Webhook**
3. Click **Copy Webhook URL**
4. Paste it into `config.env` as `DISCORD_WEBHOOK_URL`

---

## Deploy

Copy files to the phone (via SSH, USB, or any file transfer app):
```bash
mkdir ~/thermalwatch
# copy phone_receiver.py and config.env into ~/thermalwatch/
```

Run manually to test:
```bash
python3 ~/thermalwatch/phone_receiver.py
```

You should see it print startup info and then `Listening...`. When the Pi sends a heartbeat or frame, it will print activity to the console.

---

## Run on Boot (Termux:Boot)

Install **Termux:Boot** from F-Droid, then:

```bash
mkdir -p ~/.termux/boot
nano ~/.termux/boot/start_thermalwatch.sh
```

Add:
```bash
#!/data/data/com.termux/files/usr/bin/bash
sleep 15  # give WiFi time to connect after reboot
python3 ~/thermalwatch/phone_receiver.py
```

Make it executable:
```bash
chmod +x ~/.termux/boot/start_thermalwatch.sh
```

---

## Android Background Process Note

Android 12+ aggressively kills background scripts. If the receiver stops running unexpectedly, follow the fix at:
[termux.xyz/how-to-fix-termux-error-process-completed-signal-9-press-enter](https://termux.xyz/how-to-fix-termux-error-process-completed-signal-9-press-enter/)

---

## How Alerts Work

**Stove alert** — fires when:
1. The Pi sends a frame (meaning a pixel exceeded the temperature threshold), AND
2. No person is detected in that frame, AND
3. This has been the case for `INACTIVITY_TIMEOUT` seconds

Repeated alerts are sent no more than once every 5 minutes to avoid Discord spam.

**Pi offline alert** — fires when no message (frame or heartbeat) is received from the Pi for 60 seconds. This catches power outages, crashes, or disconnected cameras.
