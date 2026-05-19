"""
phone_receiver.py — ThermalWatch Phone Side
Receives temperature frames from the Pi over UDP,
detects whether a burner is on and whether a person is present,
and fires a Discord webhook alert if the stove is left unattended.

Run with: python3 phone_receiver.py
"""

import socket
import numpy as np
import struct
import time
import requests
import os
from dotenv import dotenv_values

# ── Load config ───────────────────────────────────────────────────────────────
_config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.env")
config = dotenv_values(_config_path)

UDP_PORT            = int(config["UDP_PORT"])
INACTIVITY_TIMEOUT  = int(config["INACTIVITY_TIMEOUT"])
DISCORD_WEBHOOK_URL = config["DISCORD_WEBHOOK_URL"]
PERSON_TEMP_MIN     = float(config["PERSON_TEMP_MIN"])
PERSON_TEMP_MAX     = float(config["PERSON_TEMP_MAX"])
PERSON_MIN_PIXELS   = int(config["PERSON_MIN_PIXELS"])

# How long to wait between repeated alerts — avoids spamming Discord
ALERT_COOLDOWN = 300  # 5 minutes


def person_present(temp_array):
    """
    Detect whether a person is in frame.
    Looks for a blob of pixels in the human body temperature range
    that meets a minimum size threshold.
    Tune PERSON_TEMP_MIN, PERSON_TEMP_MAX, and PERSON_MIN_PIXELS
    in config.env to match your environment.
    """
    mask = (temp_array >= PERSON_TEMP_MIN) & (temp_array <= PERSON_TEMP_MAX)
    return int(np.sum(mask)) >= PERSON_MIN_PIXELS


def send_discord_alert(message):
    """Send a notification to Discord via webhook."""
    if "YOUR_WEBHOOK_HERE" in DISCORD_WEBHOOK_URL:
        print(f"  [Alert] Discord webhook not configured — would have sent: {message}")
        return

    try:
        resp = requests.post(DISCORD_WEBHOOK_URL, json={"content": message}, timeout=10)
        if resp.status_code not in (200, 204):
            print(f"  [Alert] Discord returned {resp.status_code}: {resp.text}")
    except requests.RequestException as e:
        print(f"  [Alert] Failed to send Discord alert: {e}")


def reassemble_frame(chunks, total_chunks):
    """Reassemble chunked UDP payload into a temperature array."""
    payload  = b"".join(chunks[i] for i in range(total_chunks))
    rows, cols = struct.unpack(">HH", payload[:4])
    data     = np.frombuffer(payload[4:], dtype=np.float32).reshape((rows, cols))
    return data


def main():
    print("ThermalWatch — Phone Receiver starting...")
    print(f"  Listening on UDP port: {UDP_PORT}")
    print(f"  Inactivity timeout:    {INACTIVITY_TIMEOUT}s")
    print(f"  Person detection:      {PERSON_TEMP_MIN}–{PERSON_TEMP_MAX}°C, "
          f"min {PERSON_MIN_PIXELS} pixels")

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", UDP_PORT))
    sock.settimeout(30)  # loop anyway every 30s to check Pi status

    # State tracking
    last_person_seen   = time.time()
    last_alert_sent    = 0
    pi_last_seen       = time.time()
    alerted_pi_offline = False

    # Buffer for reassembling chunked frames: { total_chunks: { index: bytes } }
    chunk_buffer = {}

    print("Listening...\n")

    while True:
        try:
            raw, _ = sock.recvfrom(65535)
            pi_last_seen       = time.time()
            alerted_pi_offline = False

            # ── Heartbeat ─────────────────────────────────────────────────────
            if raw == b"HEARTBEAT":
                # Pi is alive, nothing hot — reset inactivity timer
                last_person_seen = time.time()
                continue

            # ── Chunked frame ─────────────────────────────────────────────────
            chunk_index  = raw[0]
            total_chunks = raw[1]
            chunk_data   = raw[2:]

            if total_chunks not in chunk_buffer:
                chunk_buffer[total_chunks] = {}
            chunk_buffer[total_chunks][chunk_index] = chunk_data

            if len(chunk_buffer[total_chunks]) == total_chunks:
                temp_array = reassemble_frame(chunk_buffer[total_chunks], total_chunks)
                chunk_buffer.clear()

                max_temp = float(np.max(temp_array))

                # ── Person detection ──────────────────────────────────────────
                if person_present(temp_array):
                    last_person_seen = time.time()
                    print(f"  Person detected ({max_temp:.1f}°C max) — timer reset.")
                else:
                    inactive_for = time.time() - last_person_seen
                    print(f"  No person ({max_temp:.1f}°C max) — "
                          f"inactive {inactive_for:.0f}s / {INACTIVITY_TIMEOUT}s")

                    if inactive_for >= INACTIVITY_TIMEOUT:
                        if (time.time() - last_alert_sent) >= ALERT_COOLDOWN:
                            minutes = int(inactive_for // 60)
                            msg = (
                                f"⚠️ **Stove Alert** — The stove appears to be on "
                                f"({max_temp:.0f}°C detected) but no one has been "
                                f"in the kitchen for {minutes} minute(s). "
                                f"Please check on the stove!"
                            )
                            send_discord_alert(msg)
                            last_alert_sent = time.time()

        except socket.timeout:
            pi_offline_for = time.time() - pi_last_seen
            if pi_offline_for > 60 and not alerted_pi_offline:
                msg = (
                    f"⚠️ **ThermalWatch offline** — No signal from the Pi for "
                    f"{int(pi_offline_for)}s. The monitoring system may be down."
                )
                send_discord_alert(msg)
                alerted_pi_offline = True
                last_alert_sent    = time.time()


if __name__ == "__main__":
    main()
