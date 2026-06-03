"""
pi_sender.py - ThermalWatch Pi Side
Reads raw frames from the TOPDON TC001 thermal camera,
checks if any pixel exceeds the temperature threshold,
and sends qualifying frames to the phone over UDP.

Run with: python3 pi_sender.py
          python3 pi_sender.py --debug   # live output to stderr

Logging: WARNING and above only - written to LOG_FILE set in .env.
         Default is /tmp/thermalwatch.log (RAM via tmpfs - no SD card writes).
         Normal frame processing is completely silent.
         To check logs: cat /tmp/thermalwatch.log
         To debug actively, run with --debug or change LOG_FILE in .env.
"""

import argparse
import cv2
import numpy as np
import socket
import time
import os
import struct
import logging
import sys
from dotenv import dotenv_values

parser = argparse.ArgumentParser()
parser.add_argument("--debug", action="store_true", help="Print debug logs to stderr")
args = parser.parse_args()

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
    CAMERA_INDEX   = int(config.get("CAMERA_INDEX", "0"))
    LOG_FILE       = config.get("LOG_FILE", "/tmp/thermalwatch.log")
except KeyError as e:
    print(f"CRITICAL: Missing required key {e} in {_config_path}.", file=sys.stderr)
    print(f"  → Copy .env.example to .env and fill in all values.", file=sys.stderr)
    raise
except Exception as e:
    print(f"CRITICAL: Failed to load .env ({_config_path}): {e}", file=sys.stderr)
    print(f"  → Make sure .env exists in the same directory as this script.", file=sys.stderr)
    raise

FRAME_DELAY = 1.0 / SAMPLE_FPS

# ── Logging setup ─────────────────────────────────────────────────────────────
# WARNING+ always goes to both stderr and LOG_FILE.
# --debug additionally lowers the stderr level to DEBUG.
_fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

log = logging.getLogger("thermalwatch")
log.setLevel(logging.DEBUG if args.debug else logging.WARNING)

_stderr_handler = logging.StreamHandler(sys.stderr)
_stderr_handler.setLevel(logging.DEBUG if args.debug else logging.WARNING)
_stderr_handler.setFormatter(_fmt)
log.addHandler(_stderr_handler)

_file_handler = logging.FileHandler(LOG_FILE)
_file_handler.setLevel(logging.WARNING)
_file_handler.setFormatter(_fmt)
log.addHandler(_file_handler)

# TC001 raw frame dimensions.
# The camera presents as 256x384 YUYV.
# Top 192 rows = thermal image, bottom 192 rows = encoded temperature data.
RAW_WIDTH      = 256
RAW_HEIGHT     = 384
THERMAL_HEIGHT = 192

# How many consecutive read failures before attempting a camera reopen.
# Single-frame blips are common and not worth logging; sustained failure means
# the camera was disconnected or crashed.
MAX_CONSECUTIVE_FAILURES = 10


def open_camera(device_index=0):
    """Open the TC001 and configure it for raw YUYV capture."""
    log.debug("Opening camera at /dev/video%d ...", device_index)
    cap = cv2.VideoCapture(device_index, cv2.CAP_V4L2)
    log.debug("VideoCapture() returned - setting properties")
    cap.set(cv2.CAP_PROP_CONVERT_RGB, 0)  # keep raw bytes, no RGB conversion
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, RAW_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, RAW_HEIGHT)
    if not cap.isOpened():
        log.error(
            "Could not open camera at /dev/video%d.\n"
            "  → Run 'v4l2-ctl --list-devices' to confirm the TC001 is detected.\n"
            "  → If it shows a different index, set CAMERA_INDEX in .env to match.\n"
            "  → If it's not listed at all, check the USB/OTG connection and try replugging.",
            device_index,
        )
        raise RuntimeError(f"Could not open camera at /dev/video{device_index}.")
    log.debug("Camera opened successfully")
    return cap


def extract_temperature_array(raw_frame):
    """
    The TC001 raw frame is 256x384 YUYV (2 bytes per pixel).
    The bottom 192 rows contain raw temperature data encoded as 16-bit values.
    Each 16-bit value / 64 - 273.15 gives temperature in Celsius.
    Credit: LeoDJ / Les Wright (PyThermalCamera) for reverse engineering this.
    """
    if raw_frame.shape != (RAW_HEIGHT, RAW_WIDTH, 2):
        raise ValueError(
            f"Unexpected frame shape {raw_frame.shape} - "
            f"expected ({RAW_HEIGHT}, {RAW_WIDTH}, 2). "
            f"Camera may not be in YUYV mode or dimensions changed."
        )
    temp_raw = raw_frame[THERMAL_HEIGHT:, :, :]
    # np.ascontiguousarray ensures the slice is C-contiguous before reinterpreting
    # bytes as uint16 - slices from OpenCV frames can be non-contiguous.
    temp_u16 = np.ascontiguousarray(temp_raw).view(np.uint16).reshape((THERMAL_HEIGHT, RAW_WIDTH))
    return (temp_u16.astype(np.float32) / 64.0) - 273.15


def send_frame(sock, addr, temp_array):
    """
    Serialize the temperature array and send it to the phone over UDP.
    Chunked into 60KB pieces to stay safely under UDP size limits.
    Protocol: chunk_index (1 byte) | total_chunks (1 byte) | data
    Returns True on success, False if any chunk failed (partial send aborted).
    """
    rows, cols   = temp_array.shape
    header       = struct.pack(">HH", rows, cols)
    payload      = header + temp_array.tobytes()
    CHUNK        = 60000
    total_chunks = (len(payload) + CHUNK - 1) // CHUNK

    if total_chunks > 255:
        log.error(
            "Frame too large to fit in 255 chunks (%d bytes) - skipping send",
            len(payload),
        )
        return False

    for i in range(total_chunks):
        try:
            chunk_header = struct.pack(">BB", i, total_chunks)
            sock.sendto(chunk_header + payload[i * CHUNK:(i + 1) * CHUNK], addr)
            time.sleep(0.001)  # avoid flooding the send buffer
        except OSError as e:
            log.error(
                "Failed to send frame chunk %d/%d: %s - aborting frame",
                i + 1, total_chunks, e,
            )
            return False

    return True


def main():
    log.debug(
        "Config loaded: PHONE_IP=%s UDP_PORT=%d TEMP_THRESHOLD=%.1f "
        "SAMPLE_FPS=%.1f CAMERA_INDEX=%d LOG_FILE=%s",
        PHONE_IP, UDP_PORT, TEMP_THRESHOLD, SAMPLE_FPS, CAMERA_INDEX, LOG_FILE,
    )

    try:
        cap = open_camera(device_index=CAMERA_INDEX)
    except RuntimeError:
        return  # already logged inside open_camera

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    addr = (PHONE_IP, UDP_PORT)
    log.debug("UDP socket ready, sending to %s:%d", PHONE_IP, UDP_PORT)

    consecutive_failures = 0
    frame_count          = 0

    log.debug("Entering main loop (FRAME_DELAY=%.3fs)", FRAME_DELAY)
    try:
        while True:
            loop_start = time.time()

            log.debug("Reading frame %d ...", frame_count + 1)
            ret, raw_frame = cap.read()
            log.debug("cap.read() returned: ret=%s, frame=%s", ret, "ok" if raw_frame is not None else "None")

            if not ret or raw_frame is None:
                consecutive_failures += 1
                log.debug("Frame read failed (consecutive=%d)", consecutive_failures)
                if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                    log.warning(
                        "Camera read failed %d times in a row - attempting reopen.",
                        consecutive_failures,
                    )
                    cap.release()
                    time.sleep(3)  # give USB time to settle after disconnect
                    try:
                        cap = open_camera(device_index=CAMERA_INDEX)
                        consecutive_failures = 0
                        log.warning("Camera reopened successfully.")
                    except RuntimeError:
                        log.error("Camera reopen failed - will retry in 10s.")
                        time.sleep(10)
                else:
                    time.sleep(1)
                continue

            consecutive_failures = 0
            frame_count += 1

            try:
                temp_array = extract_temperature_array(raw_frame)
            except Exception as e:
                log.error("Failed to extract temperature data from frame: %s", e)
                continue

            max_temp = float(np.max(temp_array))
            log.debug("Frame %d: max_temp=%.1f°C threshold=%.1f°C", frame_count, max_temp, TEMP_THRESHOLD)

            if max_temp >= TEMP_THRESHOLD:
                log.debug("Hot frame - sending to phone")
                send_frame(sock, addr, temp_array)
            else:
                log.debug("Cool frame - sending heartbeat")
                try:
                    sock.sendto(b"HEARTBEAT", addr)
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
