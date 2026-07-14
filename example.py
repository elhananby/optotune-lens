"""Example script demonstrating the use of the modernized optotune_lens package."""

import logging
import sys

from optotune_lens import Lens, LensError

# Setup standard logging to stdout
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout
)

def main():
    # Use COM7 or adjust for Linux (e.g. '/dev/ttyUSB0')
    port = 'COM7' if sys.platform == 'win32' else '/dev/ttyACM0'
    
    print(f"Attempting connection to lens on {port}...")
    
    try:
        # Use context manager for automatic port cleanup
        with Lens(port, debug=False) as lens:
            print(f"Connection Successful!")
            print(f"Firmware Type: {lens.firmware_type}")
            print(f"Firmware Version: {lens.firmware_version}")
            print(f"Device ID: {lens.device_id}")
            print(f"Lens Serial: {lens.lens_serial}")
            print(f"Temperature: {lens.get_temperature():.2f} °C")

            print("\n--- Focal Power Mode ---")
            min_fp, max_fp = lens.to_focal_power_mode()
            print(f"Focal Power Limits: {min_fp} to {max_fp} diopters")
            
            min_fp, max_fp = lens.set_temperature_limits(20.0, 45.0)
            print(f"Updated safety temp limits (20-45C).")
            print(f"New Focal Power Limits: {min_fp} to {max_fp} diopters")
            
            # Setting diopter values
            print("Setting diopter to 3.0...")
            lens.set_diopter(3.0)
            print("Setting diopter to -0.2...")
            lens.set_diopter(-0.2)

            print("\n--- Current Mode ---")
            lens.to_current_mode()
            print("Switched to current mode.")
            print("Setting current to 100.0 mA...")
            lens.set_current(100.0)
            
            print("\nDemo complete!")
            
    except LensError as e:
        print(f"\nLens Error encountered: {e}", file=sys.stderr)
    except Exception as e:
        print(f"\nUnexpected Error: {e}", file=sys.stderr)

if __name__ == '__main__':
    main()
