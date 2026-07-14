"""Unified wrapper around Optotune's optoICC SDK for the ICC-4C, ECC-1C, and ICC-1C controllers.

Unlike the Lens Driver 4/4i (see lens.py), these controllers are driven by Optotune's own
vendored optoICC/optoKummenberg packages rather than a hand-rolled serial protocol. The three
board types (ICC4cBoard, ECC1cBoard, ICC1cBoard) expose nearly identical objects
(board.channel[i].StaticInput/TemperatureManager/DeviceEEPROM/SignalGenerator/Analog), so a
single IccLens/IccChannel pair covers all three rather than one wrapper class per controller.
"""

import logging
import socket
from enum import Enum
from typing import List, Optional, Sequence, Union

import serial
import optoICC
from optoICC.tools.list_comports import get_icc4c_port
from optoKummenberg.tools.definitions import UnitType, WaveformShape

from .exceptions import LensConnectionError, LensValidationError

logger = logging.getLogger("optotune_lens")


class IccControllerType(str, Enum):
    """Supported optoICC controller families."""
    ICC4C = "icc4c"
    ECC1C = "ecc1c"
    ICC1C = "icc1c"


class IccChannel:
    """Wraps a single optoICC channel (StaticInput/TemperatureManager/DeviceEEPROM/etc)."""

    def __init__(self, raw_channel) -> None:
        self._ch = raw_channel

    @staticmethod
    def _validate_range(register: dict, value: float) -> None:
        register_range = register.get('range')
        if register_range is None:
            return
        lo, hi = register_range
        if not (lo <= value <= hi):
            raise LensValidationError(f"Value {value} is out of valid range [{lo}, {hi}]")

    def set_current(self, current: float) -> None:
        """Set static output current in amperes."""
        self._validate_range(self._ch.StaticInput.current, current)
        self._ch.StaticInput.SetAsInput()
        self._ch.StaticInput.SetCurrent(current)

    def get_current(self) -> float:
        """Read the static output current in amperes."""
        return self._ch.StaticInput.GetCurrent()

    def set_diopter(self, diopter: float) -> None:
        """Set focal power in diopters.

        Note: this validates against the generic firmware-level range for this register,
        not per-lens calibrated bounds (which require reading LensCompensation/DeviceEEPROM
        data specific to the attached lens).
        """
        self._validate_range(self._ch.StaticInput.focal_power, diopter)
        self._ch.StaticInput.SetAsInput()
        self._ch.StaticInput.SetFocalPower(diopter)

    def get_diopter(self) -> float:
        """Read the current focal power in diopters."""
        return self._ch.StaticInput.GetFocalPower()

    def get_temperature(self) -> float:
        """Read the device temperature in degrees Celsius."""
        return self._ch.TemperatureManager.GetDeviceTemperature()

    @property
    def serial_number(self) -> str:
        """Serial number of the device (lens) connected to this channel."""
        return self._ch.DeviceEEPROM.GetSerialNumber().decode('ascii').rstrip('\x00').strip()

    def eeprom_dump(self) -> List[int]:
        """Read the full contents of the connected device's EEPROM."""
        size = self._ch.DeviceEEPROM.GetEEPROMSize()
        return list(self._ch.DeviceEEPROM.GetEEPROM(0, size))

    def run_waveform(self, shape: Union[WaveformShape, int], frequency: float, amplitude: float,
                      unit: Union[UnitType, int] = UnitType.CURRENT, offset: float = 0.0,
                      phase: float = 0.0, cycles: int = -1) -> None:
        """Configure and start the signal generator on this channel.

        cycles=-1 (default) loops indefinitely until stop_waveform() is called.
        """
        sig_gen = self._ch.SignalGenerator
        sig_gen.SetUnit(unit)
        sig_gen.SetShape(shape)
        sig_gen.SetFrequency(frequency)
        sig_gen.SetAmplitude(amplitude)
        sig_gen.SetOffset(offset)
        sig_gen.SetPhase(phase)
        sig_gen.SetCycles(cycles)
        sig_gen.SetAsInput()
        sig_gen.Run()

    def stop_waveform(self) -> None:
        """Stop the signal generator on this channel."""
        self._ch.SignalGenerator.Stop()

    def configure_analog_input(self, voltage_range: Sequence[float], value_range: Sequence[float],
                                unit: str) -> None:
        """Configure the analog voltage input with a linear voltage-to-value mapping.

        Parameters
        ----------
        voltage_range : sequence of float
            Input voltages [V] defining the lookup table, e.g. [0, 10].
        value_range : sequence of float
            Corresponding output values (amperes or diopters, per `unit`) for each voltage,
            e.g. [-2, 3] for diopters.
        unit : 'current' or 'focal_power'
            Which quantity `value_range` is expressed in.
        """
        # LUT type codes come from the SDK's Analog.SetLUTtype docstring
        # ("0 = current, 1 = focal power" in optoKummenberg/registers/InputStage.py).
        # Note this is a different code space from UnitType (where FP == 3), and it has
        # not yet been verified on real hardware -- see the README hardware note.
        lut_types = {'current': 0, 'focal_power': 1}
        if unit not in lut_types:
            raise LensValidationError(f"Unknown analog input unit {unit!r}; expected 'current' or 'focal_power'")
        analog = self._ch.Analog
        analog.SetLUTtype(lut_types[unit])
        analog.SetLUTvoltages(list(voltage_range))
        analog.SetLUTvalues(list(value_range))
        analog.SetAsInput()


class IccLens:
    """User-facing wrapper around an optoICC ICC-4C/ECC-1C/ICC-1C board.

    Use `IccLens.connect(...)` to open a real hardware connection. The plain constructor
    `IccLens(board, controller)` takes an already-connected board object (real or a test fake)
    and is intended for testing without hardware.
    """

    _CONNECT_FUNCS = {
        IccControllerType.ICC4C: optoICC.connect,
        IccControllerType.ECC1C: optoICC.connectEcc,
        IccControllerType.ICC1C: optoICC.connectIcc1c,
    }

    def __init__(self, board, controller: Union[IccControllerType, str]) -> None:
        self._board = board
        self.controller = IccControllerType(controller)
        self.channels = [IccChannel(ch) for ch in board.channel]

    @classmethod
    def connect(cls, controller: Union[IccControllerType, str], port: Optional[str] = None,
                ip_address: Optional[str] = None, verbose: bool = False) -> 'IccLens':
        """Open a real connection to an ICC-4C/ECC-1C/ICC-1C board.

        Raises
        ------
        LensValidationError
            If `ip_address` is given for controller='ecc1c' (Ethernet is not supported by the
            ECC-1C board class in this SDK version).
        LensConnectionError
            If no port/device can be found or the connection attempt fails.
        """
        controller = IccControllerType(controller)

        if ip_address is not None and controller == IccControllerType.ECC1C:
            raise LensValidationError("ECC-1C does not support Ethernet connections in this SDK version")

        if ip_address is None and port is None:
            port = get_icc4c_port()
            if port is None:
                raise LensConnectionError(f"No {controller.value.upper()} device found on any serial port")

        kwargs = {'verbose': verbose}
        if ip_address is not None:
            kwargs['ip_address'] = ip_address
        else:
            kwargs['port'] = port

        try:
            board = cls._CONNECT_FUNCS[controller](**kwargs)
        except (serial.SerialException, socket.error, ConnectionError) as e:
            raise LensConnectionError(
                f"Failed to connect to {controller.value} on {ip_address or port}: {e}"
            ) from e

        logger.info("Connected to %s on %s", controller.value, ip_address or port)
        return cls(board, controller)

    def __enter__(self) -> 'IccLens':
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    def close(self) -> None:
        """Disconnect from the board."""
        if getattr(self._board, 'Connection', None) is not None:
            logger.info("Closing connection to %s.", self.controller.value)
            self._board.Connection.disconnect()

    @property
    def firmware_version(self) -> str:
        """Board firmware version as 'major.minor.revision'."""
        major = self._board.Status.GetFirmwareVersionMajor()
        minor = self._board.Status.GetFirmwareVersionMinor()
        revision = self._board.Status.GetFirmwareVersionRevision()
        return f"{major}.{minor}.{revision}"

    @property
    def serial_number(self) -> str:
        """Board (not device/lens) serial number."""
        return self._board.EEPROM.GetSerialNumber().decode('ascii').rstrip('\x00').strip()
