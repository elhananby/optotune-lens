"""Example script demonstrating IccLens usage with an ICC-1C controller.

Requires real ICC-1C hardware connected over serial (or Ethernet) — this script is not part of
the automated test suite (see tests/test_icc.py for the hardware-free unit tests, which use a
fake board instead).
"""

import logging
import sys
import time

from optotune_lens import IccLens, LensError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout
)


def main():
    port = 'COM12' if sys.platform == 'win32' else '/dev/ttyUSB0'

    print(f"Attempting connection to ICC-1C on {port}...")

    try:
        with IccLens.connect('icc1c', port=port, verbose=False) as lens:
            print("Connection successful!")
            print(f"Firmware version: {lens.firmware_version}")
            print(f"Board serial number: {lens.serial_number}")

            channel = lens.channels[0]
            print(f"Lens serial number: {channel.serial_number}")
            print(f"Temperature: {channel.get_temperature():.2f} degC")

            print("\n--- Focal power mode ---")
            print("Setting diopter to 3.0...")
            channel.set_diopter(3.0)
            print("Setting diopter to -0.2...")
            channel.set_diopter(-0.2)

            print("\n--- Current mode ---")
            print("Setting current to 0.1 A...")
            channel.set_current(0.1)
            print("Setting current to 0.0 A...")
            channel.set_current(0.0)

            print("\n--- Signal generator ---")
            print("Running a 5 Hz, 0.2 A sinusoid for 3 seconds...")
            channel.run_waveform(shape=0, frequency=5.0, amplitude=0.2)
            time.sleep(3)
            channel.stop_waveform()

            print("\nDemo complete!")

    except LensError as e:
        print(f"\nLens error encountered: {e}", file=sys.stderr)


if __name__ == '__main__':
    main()
