"""
pi_sender.py - ThermalWatch Pi Side
Reads raw frames from the TOPDON TC001 thermal camera,
checks if any pixel exceeds the temperature threshold,
and sends qualifying frames to the phone over UDP.

Run with: python3 pi_sender.py

Logging: WARNING and above only - written to LOG_FILE set in .env.
         Default is /tmp/thermalwatch.log (RAM via tmpfs - no SD card writes).
         Normal frame processing is completely silent.
         To check logs: cat /tmp/thermalwatch.log
         To debug actively, change LOG_FILE in .env to a persistent path.
"""

import cv2
import numpy as np
import socket
import time
import os
import struct
import logging
import sys
from dotenv import dotenv_values

# ── Load config ───────────────────────────────────────────────────────────────
# Config must load before logging is set up (we need LOG_FILE from it).
# If config fails we have no log file yet, so fall back to stderr.
_config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
try:
    config         = dotenv_values(_config_path)
    PHONE_IP       = config["PHONE_IP"]
    UDP_PORT       = int(config["UDP_PORT"])
    TEMP_THRESHOLD = float(config["TEMP_THRESHOLD"])
    SAMPLE_FPS     = float(config["SAMPLE_FPS"])
    LOG_FILE       = config.get("LOG_FILE", "/tmp/thermalwatch.log")
except Exception as e:
    print(f"CRITICAL: Failed to load .env ({_config_path}): {e}", file=sys.stderr)
    raise

FRAME_DELAY = 1.0 / SAMPLE_FPS

# ── Logging setup ─────────────────────────────────────────────────────────────
# Only WARNING, ERROR, CRITICAL are written - INFO/DEBUG suppressed entirely.
# Default log path is /tmp (RAM via tmpfs) so normal operation never touches
# the SD card. Change LOG_FILE in .env to persist logs when debugging.
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("thermalwatch")

# TC001 raw frame dimensions.
# The camera presents as 256x384 YUYV.
# Top 192 rows = thermal image, bottom 192 rows = encoded temperature data.
RAW_WIDTH      = 256
RAW_HEIGHT     = 384
THERMAL_HEIGHT = 192


def open_camera(device_index=0):
    """Open the TC001 and configure it for raw YUYV capture."""
    cap = cv2.VideoCapture(device_index, cv2.CAP_V4L2)
    cap.set(cv2.CAP_PROP_CONVERT_RGB, 0)  # keep raw bytes, no RGB conversion
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, RAW_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, RAW_HEIGHT)
    if not cap.isOpened():
        log.error(
            "Could not open camera at /dev/video%d - "
            "run 'v4l2-ctl --list-devices' to find the correct index.",
            device_index,
        )
        raise RuntimeError(f"Could not open camera at /dev/video{device_index}.")
    return cap


def extract_temperature_array(raw_frame):
    """
    The TC001 raw frame is 256x384 YUYV (2 bytes per pixel).
    The bottom 192 rows contain raw temperature data encoded as 16-bit values.
    Each 16-bit value / 64 - 273.15 gives temperature in Celsius.
    Credit: LeoDJ / Les Wright (PyThermalCamera) for reverse engineering this.
    """
    temp_raw = raw_frame[THERMAL_HEIGHT:, :, :]
    # np.ascontiguousarray ensures the slice is C-contiguous before reinterpreting
    # bytes as uint16 - slices from OpenCV frames can be non-contiguous.
    temp_u16 = np.ascontiguousarray(temp_raw).view(np.uint16).reshape((THERMAL_HEIGHT, RAW_WIDTH))
    return (temp_u16 / 64.0) - 273.15


def send_frame(sock, addr, temp_array):
    """
    Serialize the temperature array and send it to the phone over UDP.
    Chunked into 60KB pieces to stay safely under UDP size limits.
    Header: 2 unsigned shorts (rows, cols).
    Each chunk prefixed with: chunk_index (1 byte), total_chunks (1 byte).
    """
    rows, cols   = temp_array.shape
    header       = struct.pack(">HH", rows, cols)
    payload      = header + temp_array.astype(np.float32).tobytes()
    CHUNK        = 60000
    total_chunks = (len(payload) + CHUNK - 1) // CHUNK

    if total_chunks > 255:
        log.error(
            "Frame too large to fit in 255 chunks (%d bytes) - skipping send",
            len(payload),
        )
        return

    for i in range(total_chunks):
        try:
            chunk_header = struct.pack(">BB", i, total_chunks)
            sock.sendto(chunk_header + payload[i * CHUNK:(i + 1) * CHUNK], addr)
            time.sleep(0.001)  # avoid flooding the send buffer
        except OSError as e:
            log.error("Failed to send frame chunk %d/%d: %s", i + 1, total_chunks, e)


def main():
    try:
        cap = open_camera(device_index=0)
    except RuntimeError:
        return  # already logged inside open_camera

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    addr = (PHONE_IP, UDP_PORT)

    # Log only after N consecutive failures - avoids log spam from single blips
    MAX_CONSECUTIVE_FAILURES = 10
    consecutive_failures     = 0

    try:
        while True:
            loop_start = time.time()

            ret, raw_frame = cap.read()

            if not ret or raw_frame is None:
                consecutive_failures += 1
                if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                    log.warning(
                        "Camera read failed %d times in a row - attempting reopen.",
                        consecutive_failures,
                    )
                    cap.release()
                    time.sleep(3)  # give USB time to settle after disconnect
                    try:
                        cap = open_camera(device_index=0)
                        consecutive_failures = 0
                        log.warning("Camera reopened successfully.")
                    except RuntimeError:
                        log.error("Camera reopen failed - will retry in 10s.")
                        time.sleep(10)
                else:
                    time.sleep(1)
                continue

            consecutive_failures = 0  # successful read - reset silently

            try:
                temp_array = extract_temperature_array(raw_frame)
            except Exception as e:
                log.error("Failed to extract temperature data from frame: %s", e)
                continue

            if float(np.max(temp_array)) >= TEMP_THRESHOLD:
                send_frame(sock, addr, temp_array)  # hot - send, no logging
            else:
                try:
                    sock.sendto(b"HEARTBEAT", addr)  # quiet - heartbeat only
                except OSError as e:
                    log.error("Failed to send heartbeat: %s", e)

            time.sleep(max(0, FRAME_DELAY - (time.time() - loop_start)))

    except KeyboardInterrupt:
        pass
    except Exception as e:
        log.critical("Unexpected error in main loop: %s", e, exc_info=True)
    finally:
        cap.release()
        sock.close()


if __name__ == "__main__":
    main()
