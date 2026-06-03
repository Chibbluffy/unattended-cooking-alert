"""
pi_sender_test.py - ThermalWatch Mock Sender

Sends fake temperature frames to the phone without requiring the camera.
Reads the same .env as pi_sender.py.

Run with: python3 pi_sender_test.py [--mode MODE]

Modes:
  hot       (default) Hot frame, no person. Phone should eventually trigger alarm.
  person    Hot frame with a person present. Phone should stay quiet / clear alarm.
  heartbeat No heat detected. Phone stays alive, any active alarm clears.
  scenario  Starts with heartbeats for 30s, then switches to hot-no-person frames
            so you can watch the full alarm cycle without touching anything.
"""

import argparse
import numpy as np
import os
import socket
import struct
import sys
import time
from dotenv import dotenv_values

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument(
    "--mode",
    choices=["hot", "person", "heartbeat", "scenario"],
    default="hot",
    help="What kind of data to send (default: hot)",
)
args = parser.parse_args()

# ── Load config ───────────────────────────────────────────────────────────────
_config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
try:
    config         = dotenv_values(_config_path)
    PHONE_IP       = config["PHONE_IP"]
    UDP_PORT       = int(config["UDP_PORT"])
    TEMP_THRESHOLD = float(config["TEMP_THRESHOLD"])
    SAMPLE_FPS     = float(config["SAMPLE_FPS"])
except KeyError as e:
    print(f"CRITICAL: Missing required key {e} in {_config_path}.", file=sys.stderr)
    print(f"  → Copy .env.example to .env and fill in all values.", file=sys.stderr)
    raise
except Exception as e:
    print(f"CRITICAL: Failed to load .env ({_config_path}): {e}", file=sys.stderr)
    print(f"  → Make sure .env exists in the same directory as this script.", file=sys.stderr)
    raise

FRAME_DELAY    = 1.0 / SAMPLE_FPS
FRAME_ROWS     = 192
FRAME_COLS     = 256
ROOM_TEMP      = 22.0
BURNER_TEMP    = TEMP_THRESHOLD + 50.0  # well above threshold
PERSON_TEMP    = 36.0                   # mid human-body range


def make_hot_frame():
    """Room temperature background with a small hot spot (burner), no person."""
    frame = np.full((FRAME_ROWS, FRAME_COLS), ROOM_TEMP, dtype=np.float32)
    # 10x10 hot spot in the centre - simulates a stove eye
    r, c = FRAME_ROWS // 2, FRAME_COLS // 2
    frame[r-5:r+5, c-5:c+5] = BURNER_TEMP
    return frame


def make_person_frame():
    """Hot spot plus a person-sized blob at body temperature."""
    frame = make_hot_frame()
    # 8x8 person blob in the upper-left area of the frame
    frame[20:28, 20:28] = PERSON_TEMP
    return frame


def send_frame(sock, addr, temp_array):
    rows, cols   = temp_array.shape
    header       = struct.pack(">HH", rows, cols)
    payload      = header + temp_array.tobytes()
    CHUNK        = 60000
    total_chunks = (len(payload) + CHUNK - 1) // CHUNK
    for i in range(total_chunks):
        chunk_header = struct.pack(">BB", i, total_chunks)
        sock.sendto(chunk_header + payload[i * CHUNK:(i + 1) * CHUNK], addr)
        time.sleep(0.001)


def main():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    addr = (PHONE_IP, UDP_PORT)

    print(f"Sending to {PHONE_IP}:{UDP_PORT} at {SAMPLE_FPS}fps  (Ctrl+C to stop)")
    print(f"TEMP_THRESHOLD={TEMP_THRESHOLD}°C  BURNER_TEMP={BURNER_TEMP}°C  PERSON_TEMP={PERSON_TEMP}°C")
    print()

    scenario_start = time.time()
    frame = 0

    try:
        while True:
            loop_start = time.time()
            frame += 1

            # In scenario mode, send heartbeats for the first 30s then switch to hot frames
            if args.mode == "scenario":
                elapsed = time.time() - scenario_start
                if elapsed < 30:
                    mode = "heartbeat"
                    remaining = int(30 - elapsed)
                    label = f"heartbeat ({remaining}s until hot phase)"
                else:
                    mode = "hot"
                    label = "hot (no person)"
            else:
                mode  = args.mode
                label = {
                    "hot":       "hot (no person)",
                    "person":    "hot + person",
                    "heartbeat": "heartbeat",
                }[mode]

            if mode == "heartbeat":
                sock.sendto(b"HEARTBEAT", addr)
            elif mode == "person":
                send_frame(sock, addr, make_person_frame())
            else:
                send_frame(sock, addr, make_hot_frame())

            print(f"  Frame {frame:4d}  [{label}]")
            time.sleep(max(0, FRAME_DELAY - (time.time() - loop_start)))

    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        sock.close()


if __name__ == "__main__":
    main()
