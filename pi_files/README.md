# ThermalWatch — Pi Setup

The Pi side reads raw thermal frames from the TOPDON TC001 camera and forwards anything above the temperature threshold to the phone over UDP. During normal operation it is completely silent — nothing is logged, nothing is written to disk.

---

## Hardware

- Raspberry Pi Zero W
- TOPDON TC001 thermal camera
- Micro USB OTG adapter
- MicroSD card (8GB+)
- Reliable 5V/2A micro USB power supply

> Connect the TC001 to the port labeled **USB**, not **PWR IN**. The Pi Zero W has two micro USB ports — this is a common mistake.

---

## OS

**Raspberry Pi OS Lite, 32-bit (Bookworm)**

Flash with the official [Raspberry Pi Imager](https://www.raspberrypi.com/software/). Before writing, use the Imager's customisation settings to pre-configure:
- WiFi SSID and password
- SSH enabled
- Username and password
- Hostname (e.g. `thermalpi`)

This means you never need a monitor or keyboard — just power it on and SSH in.

Assign a static IP to the Pi via your router's DHCP reservation so the address never changes.

---

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
```bash
sudo nano /etc/fstab
```
Find the root mount line and add `noatime` to its options:
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

---

## Install Dependencies

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3-pip python3-opencv v4l-utils ffmpeg
pip3 install python-dotenv numpy
```

---

## Configuration

Edit `config.env` before deploying:

| Setting | Default | Description |
|---|---|---|
| `PHONE_IP` | `192.168.1.105` | Static IP of the phone on your network |
| `UDP_PORT` | `5000` | Must match `UDP_PORT` in phone's `config.env` |
| `TEMP_THRESHOLD` | `100` | °C — frames above this are sent to the phone |
| `SAMPLE_FPS` | `2` | Frames per second to sample from camera |
| `LOG_FILE` | `/tmp/thermalwatch.log` | Log path — `/tmp` is RAM, change to persist |

---

## Deploy

Copy files to the Pi:
```bash
scp pi_sender.py config.env pi@YOUR_PI_IP:~/thermalwatch/
```

Plug in the TC001 via OTG adapter and verify it's detected:
```bash
v4l2-ctl --list-devices
```

Note the device index. If it's not `0`, update the `open_camera(device_index=0)` call in `pi_sender.py`.

Run manually to test:
```bash
python3 ~/thermalwatch/pi_sender.py
```

---

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
```

Check it's running:
```bash
sudo systemctl status thermalwatch
```

---

## Logging

The script is silent during normal operation. Errors are written to `LOG_FILE` (default: `/tmp/thermalwatch.log` in RAM).

**What gets logged:**
- Config file missing or unreadable (stderr, since log isn't set up yet)
- Camera fails to open
- 10+ consecutive frame read failures
- Temperature data extraction failure
- UDP send failure
- Any unexpected crash (with full stack trace)

**Check the log:**
```bash
cat /tmp/thermalwatch.log
```

**To persist logs across reboots** when debugging, change in `config.env`:
```env
LOG_FILE=/home/pi/thermalwatch/errors.log
```
