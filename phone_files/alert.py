#!/usr/bin/env python3
"""
alert.py - ThermalWatch Audible Alert

Plays a 520 Hz square wave alarm (T-3 fire alarm pattern) followed by a
spoken message via Termux TTS. Requires SoX ('pkg install sox') and
Termux:API ('pkg install termux-api').

Run directly:
    python3 alert.py
    python3 alert.py "Hey, you left the stove on!"
"""

import subprocess
import sys
import time

MESSAGE = "The stove is still on. Please check the stove."
CYCLES  = 2


def beep_chord(duration=2.0):
    """Play a 520 Hz + 1040 Hz square wave chord."""
    subprocess.run(
        ["play", "-n", "synth", str(duration), "square", "520", "square", "1040"],
        stderr=subprocess.DEVNULL,
    )


def t3_pattern():
    """Play T-3 fire alarm pattern: 3 short beeps then a pause."""
    for _ in range(3):
        subprocess.run(
            ["play", "-n", "synth", "0.5", "square", "520"],
            stderr=subprocess.DEVNULL,
        )
        time.sleep(0.5)
    time.sleep(1)


def speak(message):
    """Speak the message via Termux TTS."""
    subprocess.run(["termux-tts-speak", message])


def run_alert(message=MESSAGE, cycles=CYCLES):
    for _ in range(cycles):
        beep_chord()
        time.sleep(0.3)
        t3_pattern()
    speak(message)
    for _ in range(cycles):
        beep_chord()
        time.sleep(0.3)
        t3_pattern()


if __name__ == "__main__":
    msg = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else MESSAGE
    run_alert(message=msg)
