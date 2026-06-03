# ThermalWatch - Phone Setup

The phone receives temperature frames from the Pi over UDP and handles all detection logic: is the burner on? is a person present? how long have they been gone? It fires a Discord alert and plays an audible alarm if the stove is left unattended. The alarm stops immediately when a person is detected. A Discord-only alert fires if the Pi goes offline.

For an overview of how the system works, see the [main README](../README.md).

## Requirements

- Android phone
- Termux (from [F-Droid](https://f-droid.org/) - **not the Play Store version**, which is outdated)
- Termux:API from F-Droid (required for verbal alerts)
- Termux:Boot from F-Droid (optional, for auto-start on reboot)
- Static IP assigned to the phone via your router's DHCP reservation

## Install Dependencies

In Termux:
```bash
pkg update && pkg upgrade
pkg install python termux-api sox
pip install -r requirements.txt
```

- `termux-api` provides `termux-tts-speak` for the spoken part of the alarm
- `sox` provides the `play` command used to generate the audible beep sequence

If either is missing, that part of the alert silently fails — Discord notifications always fire regardless.

## Configuration

Copy the example config and fill in your values:
```bash
cp .env.example .env
nano .env
```

Settings:

| Setting | Default | Description |
|---|---|---|
| `UDP_PORT` | `5000` | Must match `UDP_PORT` in pi_files/.env |
| `INACTIVITY_TIMEOUT` | `300` | Seconds of no person before alert fires (300 = 5 min) |
| `DISCORD_WEBHOOK_URL` | *(unset)* | Your Discord webhook URL |
| `PERSON_TEMP_MIN` | `28` | Lower bound of human body temp range in Celsius |
| `PERSON_TEMP_MAX` | `40` | Upper bound of human body temp range in Celsius |
| `PERSON_MIN_PIXELS` | `30` | Minimum pixel blob size to count as a person |
| `SPEAK_INTERVAL` | `30` | Seconds between audible alarm repeats while stove is unattended |
| `ALERT_COOLDOWN` | `300` | Seconds between repeated Discord messages |
| `ALERT_SCRIPT` | *(unset)* | Path to alert script; defaults to `alert.py` in the same directory |
| `LOG_FILE` | *(unset)* | Log file path for warnings/errors; defaults to stderr if unset |

## Set Up Discord Webhook

1. Open Discord and go to a server you control (or create one just for alerts)
2. Pick a channel, then go to **Edit Channel > Integrations > Webhooks > New Webhook**
3. Click **Copy Webhook URL**
4. Paste it into `.env` as `DISCORD_WEBHOOK_URL`

## Deploy

Copy files to the phone (via SSH, USB, or any file transfer app):
```bash
mkdir ~/thermalwatch
# copy phone_receiver.py, alert.py, .env.example, and requirements.txt into ~/thermalwatch/
cp ~/thermalwatch/.env.example ~/thermalwatch/.env
# then edit .env with your Discord webhook URL
```

Run manually to test:
```bash
python3 ~/thermalwatch/phone_receiver.py
```

You should see it print startup info and then `Listening...`. Run with `--debug` to see live activity (heartbeats, frames, person detection) in the terminal. When an alert fires, the phone will play a beep alarm sequence followed by a spoken message, and you will receive a Discord notification.

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

## Android Background Process Note

Android 12+ aggressively kills background scripts. If the receiver stops running unexpectedly, see:
[termux.xyz/how-to-fix-termux-error-process-completed-signal-9-press-enter](https://termux.xyz/how-to-fix-termux-error-process-completed-signal-9-press-enter/)

## How Person Detection Works

The receiver looks for a blob of pixels in the human body temperature range (`PERSON_TEMP_MIN` to `PERSON_TEMP_MAX`, default 28-40C) that meets a minimum size (`PERSON_MIN_PIXELS`, default 30 pixels). If that blob is present, a person is considered in frame and the inactivity timer resets. Any active alarm stops immediately when a person is detected.

This is a simple heuristic that works well for a fixed-angle kitchen camera with a clear view of the cooking area.

Tuning tips:
- If the person is not being detected, lower `PERSON_TEMP_MIN` slightly
- If warm objects cause false detections, raise `PERSON_MIN_PIXELS`
- If alerts fire too quickly or too slowly, adjust `INACTIVITY_TIMEOUT`

## How Alerts Work

**Stove alert** fires when:
1. The Pi sends a hot frame (a pixel exceeded the temperature threshold), AND
2. No person is detected in that frame, AND
3. This has been the case for `INACTIVITY_TIMEOUT` seconds

On first trigger: a Discord message is sent and `alert.py` is launched in the background — it plays a 520 Hz square wave alarm in the T-3 fire alarm pattern, then speaks the alert. The alarm repeats every `SPEAK_INTERVAL` seconds (default 30s) until a person comes into view or the stove cools down. When a person is detected, the alarm process is killed immediately. Discord follow-up messages are sent at most once every `ALERT_COOLDOWN` seconds (default 5 min) to avoid spam.

**Pi offline alert** fires when no message (frame or heartbeat) is received from the Pi for 60 seconds. Sends a Discord notification only. This catches power outages, crashes, or a disconnected camera.
