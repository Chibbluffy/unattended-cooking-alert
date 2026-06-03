# ThermalWatch - Pi Setup

The Pi reads raw thermal frames from the TOPDON TC001 camera and forwards anything above the temperature threshold to the phone over UDP. During normal operation it is completely silent - nothing is logged, nothing is written to disk.

For hardware requirements and an overview of how the system works, see the [main README](../README.md).

## OS

**Raspberry Pi OS Lite, 32-bit (Bookworm)**

Flash with the official [Raspberry Pi Imager](https://www.raspberrypi.com/software/). Before writing, use the Imager's customisation settings to pre-configure:
- WiFi SSID and password
- SSH enabled
- Username and password
- Hostname (e.g. `thermalpi`)

This way you never need a monitor or keyboard - just power it on and SSH in.

Assign a static IP to the Pi via your router's DHCP reservation so the address never changes.

## Reduce SD Card Wear

For an always-on device, reducing writes to the SD card extends its life significantly. Do all of these before deploying.

**Redirect logs to RAM:**
```bash
sudo nano /etc/systemd/journald.conf
```
Set:
```
Storage=volatile
RuntimeMaxUse=20M
```
```bash
sudo systemctl restart systemd-journald
```

**Mount `/tmp` as RAM:**
```bash
sudo nano /etc/fstab
```
Add:
```
tmpfs /tmp tmpfs defaults,noatime,nosuid,size=30m 0 0
```

**Disable access-time writes on the root filesystem:**

Find the root mount line in `/etc/fstab` and add `noatime` to its options:
```
PARTUUID=xxxxxxxx  /  ext4  defaults,noatime  0  1
```

**Disable swap:**
```bash
sudo dphys-swapfile swapoff
sudo dphys-swapfile uninstall
sudo systemctl disable dphys-swapfile
```

**Disable unneeded services:**
```bash
sudo systemctl disable bluetooth
sudo systemctl disable avahi-daemon
sudo systemctl disable triggerhappy
```

**Reboot to apply:**
```bash
sudo reboot
```

## Install Dependencies

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3-pip python3-opencv v4l-utils ffmpeg
pip3 install -r requirements.txt
```

## Configuration

Copy the example config and fill in your values:
```bash
cp .env.example .env
nano .env
```

Settings:

| Setting | Default | Description |
|---|---|---|
| `PHONE_IP` | `192.168.1.105` | Static IP of the phone on your network |
| `UDP_PORT` | `5000` | Must match `UDP_PORT` in phone_files/.env |
| `CAMERA_INDEX` | `0` | V4L2 device index - run `v4l2-ctl --list-devices` to find it |
| `TEMP_THRESHOLD` | `100` | Celsius - frames above this are sent to the phone |
| `SAMPLE_FPS` | `2` | Frames per second to sample from the camera |
| `LOG_FILE` | `/tmp/thermalwatch.log` | Log path - /tmp is RAM, change to persist |

## Deploy

Copy files to the Pi:
```bash
scp pi_sender.py pi_sender_test.py .env.example requirements.txt pi@YOUR_PI_IP:~/thermalwatch/
```

Then on the Pi:
```bash
cp ~/thermalwatch/.env.example ~/thermalwatch/.env
nano ~/thermalwatch/.env
```

Plug in the TC001 via OTG adapter and verify it's detected:
```bash
v4l2-ctl --list-devices
```

If the device index isn't `0`, set `CAMERA_INDEX` in `.env` to match.

Run manually to test:
```bash
python3 ~/thermalwatch/pi_sender.py
```

## Run on Boot

Create `/etc/systemd/system/thermalwatch.service`:
```ini
[Unit]
Description=ThermalWatch Sender
After=network.target

[Service]
ExecStart=/usr/bin/python3 /home/pi/thermalwatch/pi_sender.py
WorkingDirectory=/home/pi/thermalwatch
Restart=always
RestartSec=10
User=pi

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl enable thermalwatch
sudo systemctl start thermalwatch
sudo systemctl status thermalwatch
```

## Testing Without the Camera

`pi_sender_test.py` sends mock temperature frames to the phone using the same `.env`, so you can test the full pipeline without the TC001 connected.

```bash
# hot stove, no person - phone should trigger alarm after INACTIVITY_TIMEOUT
python3 pi_sender_test.py

# hot stove with a person present - phone should stay quiet
python3 pi_sender_test.py --mode person

# no heat detected - phone stays alive, clears any active alarm
python3 pi_sender_test.py --mode heartbeat

# full cycle: 30s of heartbeats, then hot frames until Ctrl+C
python3 pi_sender_test.py --mode scenario
```

## Logging

During normal operation, warnings and errors go to both stderr and `LOG_FILE` (default: `/tmp/thermalwatch.log` in RAM). To also see debug output while the script is running:

```bash
python3 pi_sender.py --debug
```

What gets logged:
- Config file missing or unreadable (stderr only, log path not yet known)
- Camera fails to open
- 10+ consecutive frame read failures
- Temperature data extraction failure
- UDP send failure
- Any unexpected crash (with full stack trace)

**Check the log:**
```bash
cat /tmp/thermalwatch.log
```

To persist logs across reboots, set in `.env`:
```env
LOG_FILE=/home/pi/thermalwatch/errors.log
```
