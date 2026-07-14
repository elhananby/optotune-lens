# optotune-lens

A robust, modern Python SDK for interacting with **Optotune electrically tunable lenses**: the
Lens Driver 4/4i over its native serial protocol (`Lens`), and the ICC-4C/ECC-1C/ICC-1C controller
family via Optotune's vendored `optoICC` SDK (`IccLens`).

---

## Features

- **Context Manager Support**: Safely and automatically open and close serial connections.
- **Robust Exception Hierarchy**: Specialized exceptions (`LensConnectionError`, `LensCRCError`, `LensTimeoutError`, etc.) replace generic Python `Exception`s.
- **Input Validation**: Safeguard hardware with diopter and current bounds checking prior to sending commands.
- **Logging Integration**: Uses Python's standard `logging` library instead of verbose print flags.
- **CRC-16 Modbus Verification**: Automatic checksum computation and verification on all TX/RX commands.
- **EEPROM Access**: Methods to read, write, and display the internal 256-byte EEPROM.
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

---

## API Documentation

### Class: `Lens`

#### `__init__(port: str, debug: bool = False, temp_limits: Tuple[float, float] = (20.0, 40.0))`
Initializes the serial connection at 115200 baud, performs the handshake, and loads device metadata (Max Current, Serial, Firmware). Note that connecting **writes `temp_limits` to the device** — the hardware only reports its focal power range in response to a temperature-limit command — so pass your own `(lower, upper)` limits if the 20–40 °C defaults are not appropriate. If `debug=True`, sets the logger level to `DEBUG` and routes output to stdout.

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

#### `set_temperature_limits(lower: float, upper: float) -> Tuple[float, float]`
Configures safety temperature limits. Returns the new `(min_diopter, max_diopter)` focal power
limits at those temperatures. Raises `LensCommandError` if the device reports an error.

#### `eeprom_dump() -> List[int]`
Dumps the complete 256-byte internal EEPROM contents.

#### `eeprom_print()`
Helper method to dump and pretty-print the EEPROM in a 16x16 hex grid.

---

## ICC-4C / ECC-1C / ICC-1C Support (`IccLens`)

Unlike the LD4/`Lens` class above, the ICC-4C, ECC-1C, and ICC-1C controllers are driven by
Optotune's own vendored `optoICC`/`optoKummenberg` SDK (wheels vendored under `wheels/`, installed
automatically via `uv sync`), rather than a hand-rolled protocol. `IccLens`/`IccChannel` wrap that
SDK with the same ergonomics as `Lens` (context manager, `LensError` exceptions), and work
identically regardless of which of the three board types is connected — the underlying SDK's
`Board -> channel[] -> System` shape is the same across all of them.

> **Hardware note**: as of this writing, only the Lens Driver 4 (`/dev/optotune_ld`) is physically
> available for testing. `IccLens`'s test suite (`tests/test_icc.py`) uses a fake board object and
> passes, but the real hardware code path (`IccLens.connect(...)`) has not been verified against
> actual ICC-1C/ICC-4C/ECC-1C hardware. In particular, the analog-input LUT type code for focal
> power (`1`, taken from the SDK's `SetLUTtype` documentation; the ICC-1C manual does not list
> register codes) should be double-checked the first time `configure_analog_input` is used with
> `unit='focal_power'` on a real controller.

```python
from optotune_lens import IccLens

with IccLens.connect('icc1c', port='COM12') as lens:
    print(f"Firmware version: {lens.firmware_version}")

    channel = lens.channels[0]  # ICC-4C exposes lens.channels[0..3]
    print(f"Lens serial number: {channel.serial_number}")
    print(f"Temperature: {channel.get_temperature()} °C")

    channel.set_diopter(3.0)      # switches to focal-power mode and sets it
    channel.set_current(0.1)      # switches to current mode and sets it (amperes)

    # Drive a waveform via the signal generator
    channel.run_waveform(shape=0, frequency=5.0, amplitude=0.2)
    channel.stop_waveform()

    # Or configure an external analog voltage input with a linear LUT mapping
    channel.configure_analog_input(voltage_range=[0, 10], value_range=[-2, 3], unit='focal_power')
```

`controller` in `IccLens.connect(controller, ...)` is one of `'icc4c'`, `'ecc1c'`, or `'icc1c'`. See
`examples/icc1c_example.py` for a full walkthrough (requires real hardware to run).

---

## Development and Testing

Unit tests are written with `pytest`. `Lens` tests use a mock serial implementation;
`IccLens` tests use a fake `optoICC` board object (see "Hardware note" above).

### Running Tests
```bash
uv run pytest
```

---

## License

This project is licensed under the MIT License - see the LICENSE file for details.
