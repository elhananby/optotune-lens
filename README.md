# optotune-lens

A robust, modern Python SDK for interacting with **Optotune electrically tunable lenses** over a serial (RS-232/USB COM port) interface. Supports both the **Lens Driver 4** (`Lens`) and the **ICC-1C** industrial controller (`ICC1C`).

---

## Features

- **Context Manager Support**: Safely and automatically open and close serial connections.
- **Robust Exception Hierarchy**: Specialized exceptions (`LensConnectionError`, `LensCRCError`, `LensTimeoutError`, etc.) replace generic Python `Exception`s.
- **Input Validation**: Safeguard hardware with diopter and current bounds checking prior to sending commands.
- **Logging Integration**: Uses Python's standard `logging` library instead of verbose print flags.
- **Lens Driver 4** (`Lens`): binary protocol with CRC-16 Modbus verification on all TX/RX commands, plus EEPROM read/write/dump access.
- **ICC-1C** (`ICC1C`): ASCII "Simple Mode" protocol; the controller does its own raw-current↔diopter conversion from the lens's onboard calibration.
- **Modern Packaging**: Conforms to modern PEP 517/518 build standards using `pyproject.toml`.

---

## Installation

### Prerequisites
- Python >= 3.8
- [`uv`](https://docs.astral.sh/uv/)

### Setting Up a Development Environment
From the root of the project, create the virtual environment and install the
package with its dev dependencies (`pytest`, etc.) from `uv.lock`:
```bash
uv sync --extra dev
```

Run any command inside that environment with `uv run`, e.g. `uv run pytest`
or `uv run python example.py`.

---

## Quick Start

### Basic Usage with Context Manager

```python
import logging
from optotune_lens import Lens, OperatingMode

# Set logging to see debug TX/RX logs
logging.basicConfig(level=logging.INFO)

# Use context manager to guarantee connection cleanup
with Lens(port='COM7') as lens:
    print(f"Connected to Lens Serial: {lens.lens_serial}")
    print(f"Firmware Version: {lens.firmware_version}")
    print(f"Current Temperature: {lens.get_temperature()} °C")
    
    # 1. Focal Power (Diopter) Mode Example
    min_fp, max_fp = lens.to_focal_power_mode()
    print(f"Focal Power Limits: {min_fp} to {max_fp} diopters")
    
    # Validate temperature limits (adjusts diopter range mapping)
    lens.set_temperature_limits(lower=20.0, upper=45.0)
    
    # Set optical power (raises LensValidationError if outside min_fp / max_fp)
    lens.set_diopter(3.0)
    lens.set_diopter(-0.2)
    
    # 2. Current Mode Example
    lens.to_current_mode()
    lens.set_current(100.0)  # set target current in mA
```

### ICC-1C Controller

```python
from optotune_lens import ICC1C

with ICC1C(port='COM7') as icc:
    print(f"Connected to: {icc.device_type} (Serial: {icc.device_serial})")
    print(f"Temperature: {icc.get_temperature()} °C")

    # Focal power mode — no explicit mode switch needed, SETFP is
    # always available; this just validates the lens has calibration data.
    icc.to_focal_power_mode()
    icc.set_diopter(3.0)  # raises LensValidationError if outside the lens's range

    # Current mode — SETCURRENT is independent of SETFP, no mode switch needed.
    icc.set_current(100.0)  # mA
```

---

## API Documentation

### Class: `Lens`

#### `__init__(port: str, debug: bool = False)`
Initializes the serial connection at 115200 baud, performs the handshake, and loads device metadata (Max Current, Serial, Firmware). If `debug=True`, sets the logger level to `DEBUG` and routes output to stdout.

#### `to_focal_power_mode() -> Tuple[float, float]`
Switches the lens to Focal Power mode (Mode 5) and updates/returns the diopter physical range `(min_diopter, max_diopter)`.

#### `to_current_mode()`
Switches the lens to Current mode (Mode 1).

#### `set_diopter(diopter: float)`
Sets the target diopter. Validates input against safety bounds.

#### `set_current(current: float)`
Sets the target current in mA. Validates against the device's maximum output current.

#### `get_temperature() -> float`
Reads the internal temperature sensor (resolution 0.0625 °C).

#### `set_temperature_limits(lower: float, upper: float) -> Tuple[int, float, float]`
Configures safety temperature limits. Returns new focal power limits at those temperatures.

#### `eeprom_dump() -> List[int]`
Dumps the complete 256-byte internal EEPROM contents.

#### `eeprom_print()`
Helper method to dump and pretty-print the EEPROM in a 16x16 hex grid.

### Class: `ICC1C`

#### `__init__(port: str, baudrate: int = 115200, debug: bool = False)`
Opens the serial connection, performs the `START` handshake, and confirms a lens is detected via `DETECTDEVICE`. The ICC-1C auto-detects baud rate, so `baudrate` is arbitrary.

#### `to_focal_power_mode()`
Validates the connected lens has focal power calibration data (`GETFPMIN` not `NO`). Simple Mode has no real mode-switch command — `SETFP`/`SETCURRENT` are independent and always available.

#### `to_current_mode()`
No-op compatibility shim; `SETCURRENT` is always available.

#### `set_diopter(diopter: float)` / `get_diopter() -> Optional[float]`
Sets/reads the target focal power in diopters. The device converts to/from raw current using the lens's own EEPROM calibration.

#### `set_current(current_mA: float)` / `get_current() -> float`
Sets/reads the target current in mA.

#### `get_temperature() -> float`
Reads the connected device's temperature sensor.

#### `set_temperature_limit(limit: float)`
Sets the operational temperature limit in Celsius.

**Note:** Pro Mode features (Smart Step, the signal generator, vectors) are not covered by this class — they're binary register-protocol only and are configured once via Optotune Cockpit, then persisted on the device across power cycles.

---

## Development and Testing

Unit tests are written with `pytest` and use a mock serial implementation.

### Running Tests
```bash
uv run pytest
```

---

## License

This project is licensed under the MIT License - see the LICENSE file for details.
