"""
phone_receiver.py - ThermalWatch Phone Side

Receives temperature frames from the Pi over UDP, detects whether a burner is
on and whether a person is present, and fires a Discord webhook alert plus a
spoken announcement if the stove is left unattended.

Run with: python3 phone_receiver.py
"""

import logging
import os
import socket
import struct
import subprocess
import sys
import time

import numpy as np
import requests
from dotenv import dotenv_values

# Load config
_config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
try:
    config              = dotenv_values(_config_path)
    UDP_PORT            = int(config["UDP_PORT"])
    INACTIVITY_TIMEOUT  = int(config["INACTIVITY_TIMEOUT"])
    DISCORD_WEBHOOK_URL = config["DISCORD_WEBHOOK_URL"]
    PERSON_TEMP_MIN     = float(config["PERSON_TEMP_MIN"])
    PERSON_TEMP_MAX     = float(config["PERSON_TEMP_MAX"])
    PERSON_MIN_PIXELS   = int(config["PERSON_MIN_PIXELS"])
    SPEAK_INTERVAL      = int(config.get("SPEAK_INTERVAL", "30"))
    ALERT_COOLDOWN      = int(config.get("ALERT_COOLDOWN", "300"))
except Exception as e:
    print(f"CRITICAL: Failed to load .env ({_config_path}): {e}", file=sys.stderr)
    raise

CHUNK_BUFFER_TTL = 10.0  # seconds before an incomplete/stale frame is discarded

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("thermalwatch")


def person_present(temp_array):
    """
    Detect whether a person is in frame by looking for a blob of pixels
    in the human body temperature range that meets a minimum size threshold.
    Tune PERSON_TEMP_MIN, PERSON_TEMP_MAX, and PERSON_MIN_PIXELS in .env.
    """
    mask = (temp_array >= PERSON_TEMP_MIN) & (temp_array <= PERSON_TEMP_MAX)
    return int(np.sum(mask)) >= PERSON_MIN_PIXELS


def speak_alert(text):
    """
    Speak the alert text aloud using Termux TTS (requires Termux:API +
    'pkg install termux-api'), falling back to espeak if available.
    Silently skips if neither is installed.
    """
    for cmd in [["termux-tts-speak", text], ["espeak", text]]:
        try:
            subprocess.run(cmd, timeout=30, check=False, capture_output=True)
            return
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue


def send_discord_alert(message):
    """Send a notification to Discord via webhook."""
    if not DISCORD_WEBHOOK_URL or "YOUR_WEBHOOK_HERE" in DISCORD_WEBHOOK_URL:
        print(f"  [Alert] Discord not configured - would have sent: {message}")
        return
    try:
        resp = requests.post(
            DISCORD_WEBHOOK_URL,
            json={"content": message},
            timeout=10,
        )
        if resp.status_code not in (200, 204):
            log.warning("Discord returned %d: %s", resp.status_code, resp.text[:200])
    except requests.RequestException as e:
        log.warning("Failed to send Discord alert: %s", e)


def reassemble_frame(chunks, total_chunks):
    """Reassemble a chunked UDP payload into a temperature array."""
    payload = b"".join(chunks[i] for i in range(total_chunks))
    if len(payload) < 4:
        raise ValueError(f"Payload too short: {len(payload)} bytes")
    rows, cols = struct.unpack(">HH", payload[:4])
    expected_bytes = rows * cols * 4  # float32 = 4 bytes each
    actual_bytes   = len(payload) - 4
    if actual_bytes != expected_bytes:
        raise ValueError(
            f"Size mismatch: expected {expected_bytes} bytes for "
            f"{rows}x{cols} array, got {actual_bytes}"
        )
    return np.frombuffer(payload[4:], dtype=np.float32).reshape((rows, cols))


def main():
    print("ThermalWatch - Phone Receiver starting...")
    print(f"  Listening on UDP port: {UDP_PORT}")
    print(f"  Inactivity timeout:    {INACTIVITY_TIMEOUT}s")
    print(f"  Person detection:      {PERSON_TEMP_MIN}-{PERSON_TEMP_MAX}C, "
          f"min {PERSON_MIN_PIXELS} pixels")

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("0.0.0.0", UDP_PORT))
    sock.settimeout(30)  # loop every 30s to check Pi offline status

    last_person_seen   = time.time()
    last_alert_sent    = 0.0
    last_spoken        = 0.0
    alarm_active       = False
    pi_last_seen       = time.time()
    alerted_pi_offline = False

    # chunk_buffer: { total_chunks: {"chunks": {index: bytes}, "timestamp": float} }
    # Keyed by total_chunks because at this resolution frames always produce the
    # same chunk count (4 chunks for a 192x256 float32 array). The TTL cleanup
    # above handles chunks that arrive but never complete due to packet loss.
    chunk_buffer = {}

    print("Listening...\n")

    while True:
        # Repeat the verbal alarm on every SPEAK_INTERVAL until a person is seen.
        # This runs before recvfrom so it fires even when frames are arriving normally.
        # speak_alert is blocking (~a few seconds), which is acceptable here.
        now = time.time()
        if alarm_active and (now - last_spoken) >= SPEAK_INTERVAL:
            speak_alert("Stove alert. Please check the stove.")
            last_spoken = now

        # Evict stale incomplete frames to prevent memory buildup from lost packets
        now = time.time()
        stale = [k for k, v in chunk_buffer.items()
                 if now - v["timestamp"] > CHUNK_BUFFER_TTL]
        for k in stale:
            del chunk_buffer[k]

        try:
            raw, _ = sock.recvfrom(65535)
            pi_last_seen       = time.time()
            alerted_pi_offline = False

            if raw == b"HEARTBEAT":
                # Pi is alive, nothing hot - stove is off, cancel any active alarm
                last_person_seen = time.time()
                alarm_active     = False
                continue

            if len(raw) < 3:
                log.warning("Received undersized packet (%d bytes), skipping", len(raw))
                continue

            chunk_index  = raw[0]
            total_chunks = raw[1]
            chunk_data   = raw[2:]

            if total_chunks == 0:
                log.warning("Received packet with total_chunks=0, skipping")
                continue
            if chunk_index >= total_chunks:
                log.warning(
                    "chunk_index %d >= total_chunks %d, skipping",
                    chunk_index, total_chunks,
                )
                continue

            if total_chunks not in chunk_buffer:
                chunk_buffer[total_chunks] = {"chunks": {}, "timestamp": time.time()}
            chunk_buffer[total_chunks]["chunks"][chunk_index] = chunk_data

            if len(chunk_buffer[total_chunks]["chunks"]) < total_chunks:
                continue  # still waiting on remaining chunks

            # All chunks received - reassemble and process
            try:
                temp_array = reassemble_frame(
                    chunk_buffer[total_chunks]["chunks"], total_chunks
                )
            except Exception as e:
                log.warning("Failed to reassemble frame: %s", e)
                del chunk_buffer[total_chunks]
                continue

            del chunk_buffer[total_chunks]

            max_temp = float(np.max(temp_array))

            if person_present(temp_array):
                last_person_seen = time.time()
                alarm_active     = False
                print(f"  Person detected ({max_temp:.1f}C max) - alarm cleared.")
            else:
                inactive_for = time.time() - last_person_seen
                print(
                    f"  No person ({max_temp:.1f}C max) - "
                    f"inactive {inactive_for:.0f}s / {INACTIVITY_TIMEOUT}s"
                )
                if inactive_for >= INACTIVITY_TIMEOUT:
                    now = time.time()
                    if not alarm_active:
                        # First trigger - activate the alarm
                        minutes = int(inactive_for // 60)
                        discord_msg = (
                            f"⚠️ **Stove Alert** - The stove appears to be on "
                            f"({max_temp:.0f}C detected) but no one has been "
                            f"in the kitchen for {minutes} minute(s). "
                            f"Please check on the stove!"
                        )
                        spoken_msg = (
                            f"Stove alert. The stove has been on for {minutes} "
                            f"minutes with no one nearby. Please check the stove."
                        )
                        send_discord_alert(discord_msg)
                        speak_alert(spoken_msg)
                        alarm_active    = True
                        last_spoken     = time.time()  # refresh after blocking speak
                        last_alert_sent = time.time()
                    elif (now - last_alert_sent) >= ALERT_COOLDOWN:
                        # Alarm already active - repeat Discord at cooldown rate
                        minutes = int(inactive_for // 60)
                        discord_msg = (
                            f"⚠️ **Stove Alert** - Still no one in the kitchen "
                            f"({minutes} minute(s), {max_temp:.0f}C). "
                            f"Please check on the stove!"
                        )
                        send_discord_alert(discord_msg)
                        last_alert_sent = now

        except socket.timeout:
            pi_offline_for = time.time() - pi_last_seen
            if pi_offline_for > 60 and not alerted_pi_offline:
                discord_msg = (
                    f"⚠️ **ThermalWatch offline** - No signal from the Pi for "
                    f"{int(pi_offline_for)}s. The monitoring system may be down."
                )
                spoken_msg = (
                    f"Warning. ThermalWatch has been offline for "
                    f"{int(pi_offline_for)} seconds. The monitoring system may be down."
                )
                send_discord_alert(discord_msg)
                speak_alert(spoken_msg)
                alerted_pi_offline = True
                last_alert_sent    = time.time()

        except Exception as e:
            log.error("Unexpected error in receive loop: %s", e, exc_info=True)


if __name__ == "__main__":
    main()
