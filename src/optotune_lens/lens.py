"""Core interface and implementation for the Optotune Lens driver."""

import struct
import logging
from enum import IntEnum
from typing import NamedTuple, Tuple, List, Optional, Union

import serial

from .exceptions import (
    LensError,
    LensConnectionError,
    LensTimeoutError,
    LensCRCError,
    LensCommandError,
    LensValidationError,
)
from .utils import crc_16

logger = logging.getLogger("optotune_lens")


class OperatingMode(IntEnum):
    """Lens driver operating modes."""
    CURRENT = 1
    FOCAL_POWER = 5


class FirmwareVersion(NamedTuple):
    """Firmware version tuple with helper string representation."""
    major: int
    minor: int
    build: int
    patch: int

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.build}.{self.patch}"


class Lens:
    """Python interface for an Optotune electrically tunable lens.
    
    This class handles serial communication, error checking (CRC-16), and
    mode/parameter configuration.
    """

    def __init__(self, port: str, debug: bool = False) -> None:
        """Initialize the serial connection and query hardware status.
        
        Args:
            port: Serial port name (e.g. 'COM7', '/dev/ttyUSB0').
            debug: If True, log detailed TX/RX hex dumps to stdout.
            
        Raises:
            LensConnectionError: If connection or handshake fails.
        """
        self.debug = debug
        if debug:
            logger.setLevel(logging.DEBUG)
            if not logger.handlers:
                handler = logging.StreamHandler()
                handler.setFormatter(logging.Formatter(
                    '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
                ))
                logger.addHandler(handler)

        self.min_diopter: Optional[float] = None
        self.max_diopter: Optional[float] = None
        self.max_output_current: float = 0.0

        try:
            logger.info("Connecting to Optotune lens on %s...", port)
            self.connection = serial.Serial(port, 115200, timeout=1)
            self.connection.reset_input_buffer()
            self.connection.reset_output_buffer()

            self.connection.write(b'Start')
            handshake = self.connection.readline()
            if handshake != b'Ready\r\n':
                raise LensConnectionError(
                    f"Lens Driver did not reply to handshake. Expected b'Ready\\r\\n', got {handshake!r}"
                )

            self.firmware_type: str = self.get_firmware_type()
            self.firmware_version: FirmwareVersion = self.get_firmware_version()

            self.device_id: str = self.get_device_id()
            self.max_output_current = self.get_max_output_current()
            
            # Set default temperature limits and fetch initial diopter bounds
            self.set_temperature_limits(20.0, 40.0)

            self.mode: Optional[OperatingMode] = None
            self.refresh_active_mode()

            self.lens_serial: str = self.get_lens_serial_number()

            logger.info(
                "Optotune initialization complete: Serial %s, Firmware Type %s (%s), Max Current %.1f mA",
                self.lens_serial, self.firmware_type, self.firmware_version, self.max_output_current
            )
        except Exception as e:
            if hasattr(self, 'connection') and self.connection:
                self.connection.close()
            if not isinstance(e, LensError):
                raise LensConnectionError(f"Failed to initialize lens on port {port}: {e}") from e
            raise

    def __enter__(self) -> 'Lens':
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    def close(self) -> None:
        """Close the serial connection to the lens."""
        if hasattr(self, 'connection') and self.connection and self.connection.is_open:
            logger.info("Closing connection to Optotune lens.")
            self.connection.close()

    def send_command(self, command: Union[bytes, str], reply_fmt: Optional[str] = None) -> Optional[Tuple]:
        """Send a command to the lens and optionally unpack the response.
        
        Args:
            command: The command payload (bytes or ASCII string).
            reply_fmt: Optional format string for struct.unpack of the payload.
            
        Returns:
            The unpacked response tuple, or None if reply_fmt is not specified.
            
        Raises:
            LensConnectionError: If serial writing/reading fails.
            LensTimeoutError: If read operation times out.
            LensCRCError: If response checksum validation fails.
            LensCommandError: If the response is malformed or invalid.
        """
        if isinstance(command, str):
            command = command.encode('ascii')
        
        # Calculate and append CRC-16 Modbus checksum
        command_with_crc = command + struct.pack('<H', crc_16(command))
        
        if logger.isEnabledFor(logging.DEBUG):
            tx_hex = ' '.join(f'{c:02x}' for c in command_with_crc)
            logger.debug("TX: %-50s | %r", tx_hex, command_with_crc)

        try:
            self.connection.write(command_with_crc)
        except serial.SerialException as e:
            raise LensConnectionError(f"Failed to write to serial port: {e}") from e

        if reply_fmt is not None:
            response_size = struct.calcsize(reply_fmt)
            expected_len = response_size + 4  # size + 2 (CRC) + 2 (\r\n)

            try:
                response = self.connection.read(expected_len)
            except serial.SerialException as e:
                raise LensConnectionError(f"Failed to read from serial port: {e}") from e

            if logger.isEnabledFor(logging.DEBUG):
                rx_hex = ' '.join(f'{c:02x}' for c in response)
                logger.debug("RX: %50s | %r", rx_hex, response)

            if len(response) < expected_len:
                raise LensTimeoutError(
                    f"Timeout reading from lens. Expected {expected_len} bytes, received {len(response)} bytes"
                )

            try:
                data, crc, newline = struct.unpack(f'<{response_size}sH2s', response)
            except struct.error as e:
                raise LensCommandError(f"Failed to unpack response wrapper: {e}") from e

            if crc != crc_16(data):
                raise LensCRCError(
                    f"Response CRC check failed. Got {crc:04X}, expected {crc_16(data):04X}"
                )
            if newline != b'\r\n':
                raise LensCommandError(f"Response did not end with CRLF. Got {newline!r}")

            try:
                return struct.unpack(reply_fmt, data)
            except struct.error as e:
                raise LensCommandError(f"Failed to unpack payload with format {reply_fmt}: {e}") from e
        return None

    def get_max_output_current(self) -> float:
        """Query maximum output current in mA."""
        res = self.send_command('CrMA\x00\x00', '>xxxh')
        if res is None:
            raise LensCommandError("No response received for maximum output current query")
        return res[0] / 100.0

    def get_firmware_type(self) -> str:
        """Query firmware type character."""
        res = self.send_command('H', '>xs')
        if res is None:
            raise LensCommandError("No response received for firmware type query")
        return res[0].decode('ascii')

    def get_firmware_branch(self) -> int:
        """Query firmware branch ID."""
        res = self.send_command('F', '>xB')
        if res is None:
            raise LensCommandError("No response received for firmware branch query")
        return res[0]

    def get_device_id(self) -> str:
        """Query hardware device ID."""
        res = self.send_command('IR\x00\x00\x00\x00\x00\x00\x00\x00', '>xx8s')
        if res is None:
            raise LensCommandError("No response received for device ID query")
        return res[0].decode('ascii').rstrip('\x00').strip()

    def get_firmware_version(self) -> FirmwareVersion:
        """Query firmware version information."""
        res = self.send_command(b'V\x00', '>xBBHH')
        if res is None:
            raise LensCommandError("No response received for firmware version query")
        return FirmwareVersion(*res)

    def get_lens_serial_number(self) -> str:
        """Query serial number of the lens."""
        res = self.send_command('X', '>x8s')
        if res is None:
            raise LensCommandError("No response received for lens serial number query")
        return res[0].decode('ascii').rstrip('\x00').strip()

    def eeprom_write_byte(self, address: int, byte: int) -> int:
        """Write a single byte to EEPROM address.
        
        Args:
            address: Address index (0 to 255).
            byte: Byte value to write (0 to 255).
            
        Returns:
            The error code returned by the device.
        """
        if not (0 <= address <= 255):
            raise LensValidationError(f"EEPROM address {address} is out of bounds [0, 255]")
        if not (0 <= byte <= 255):
            raise LensValidationError(f"EEPROM byte value {byte} is out of bounds [0, 255]")
            
        res = self.send_command(b'Zw' + struct.pack('BB', address, byte), '>xB')
        if res is None:
            raise LensCommandError("No response received for EEPROM write")
        return res[0]

    def eeprom_dump(self) -> List[int]:
        """Read all 256 bytes from EEPROM.
        
        Returns:
            A list containing the 256 bytes of the EEPROM.
        """
        dump = []
        for i in range(256):
            res = self.send_command(b'Zr' + struct.pack('B', i), '>xB')
            if res is None:
                raise LensCommandError(f"No response received during EEPROM read at address {i}")
            dump.append(res[0])
        return dump

    def eeprom_print(self) -> None:
        """Print the complete EEPROM contents in a 16x16 hex grid format."""
        eeprom = self.eeprom_dump()
        print('===============================================')
        print(f'EEPROM of lens number {self.lens_serial}')
        print('===============================================')
        for i in range(16):
            row_bytes = eeprom[i * 16 : i * 16 + 16]
            print(' '.join(f'{byte:02x}' for byte in row_bytes))
        print('===============================================')

    def get_temperature(self) -> float:
        """Read current temperature in Celsius."""
        res = self.send_command(b'TCA', '>xxxh')
        if res is None:
            raise LensCommandError("No response received for temperature query")
        return res[0] * 0.0625

    def set_temperature_limits(self, lower: float, upper: float) -> Tuple[int, float, float]:
        """Set temperature limits and return limits in diopters.
        
        Args:
            lower: Lower temperature limit in Celsius.
            upper: Upper temperature limit in Celsius.
            
        Returns:
            A tuple of (error, min_diopter, max_diopter).
        """
        res = self.send_command(
            b'PwTA' + struct.pack('>hh', int(upper * 16), int(lower * 16)), 
            '>xxBhh'
        )
        if res is None:
            raise LensCommandError("No response received for temperature limits change")
            
        error, max_fp, min_fp = res
        if self.firmware_type == 'A':
            self.min_diopter = min_fp / 200.0 - 5
            self.max_diopter = max_fp / 200.0 - 5
        else:
            self.min_diopter = min_fp / 200.0
            self.max_diopter = max_fp / 200.0
            
        return error, self.min_diopter, self.max_diopter

    def get_current(self) -> float:
        """Read current applied current in mA."""
        res = self.send_command(b'Ar\x00\x00', '>xh')
        if res is None:
            raise LensCommandError("No response received for current read")
        return res[0] * self.max_output_current / 4095.0

    def set_current(self, current: float) -> None:
        """Set output current in mA.
        
        Args:
            current: Current value in mA.
            
        Raises:
            LensValidationError: If not in current mode or value is out of bounds.
        """
        if self.mode != OperatingMode.CURRENT:
            raise LensValidationError("Cannot set current when not in current mode")
            
        if not (-self.max_output_current <= current <= self.max_output_current):
            raise LensValidationError(
                f"Current {current} mA is out of valid range [-{self.max_output_current}, {self.max_output_current}]"
            )
            
        raw_current = int(current * 4095.0 / self.max_output_current)
        self.send_command(b'Aw' + struct.pack('>h', raw_current))

    def get_diopter(self) -> float:
        """Read current focal power in diopters."""
        res = self.send_command(b'PrDA\x00\x00\x00\x00', '>xxh')
        if res is None:
            raise LensCommandError("No response received for diopter read")
        raw_diopter = res[0]
        return raw_diopter / 200.0 - 5 if self.firmware_type == 'A' else raw_diopter / 200.0

    def set_diopter(self, diopter: float) -> None:
        """Set focal power in diopters.
        
        Args:
            diopter: Diopter value (m^-1).
            
        Raises:
            LensValidationError: If not in focal power mode or value is out of bounds.
        """
        if self.mode != OperatingMode.FOCAL_POWER:
            raise LensValidationError("Cannot set focal power when not in focal power mode")
            
        if self.min_diopter is not None and self.max_diopter is not None:
            if not (self.min_diopter <= diopter <= self.max_diopter):
                raise LensValidationError(
                    f"Diopter {diopter} is out of valid range [{self.min_diopter}, {self.max_diopter}]"
                )
                
        raw_diopter = int((diopter + 5) * 200.0 if self.firmware_type == 'A' else diopter * 200.0)
        self.send_command(b'PwDA' + struct.pack('>h', raw_diopter) + b'\x00\x00')

    def to_focal_power_mode(self) -> Tuple[float, float]:
        """Switch device to focal power mode (Mode 5).
        
        Returns:
            A tuple of (min_diopter, max_diopter).
        """
        res = self.send_command('MwCA', '>xxxBhh')
        if res is None:
            raise LensCommandError("No response received when switching to focal power mode")
            
        error, max_fp_raw, min_fp_raw = res
        if error != 0:
            logger.warning("Switching to focal power mode returned error code: %d", error)
            
        min_fp = min_fp_raw / 200.0
        max_fp = max_fp_raw / 200.0
        if self.firmware_type == 'A':
            min_fp -= 5.0
            max_fp -= 5.0

        self.refresh_active_mode()
        self.min_diopter = min_fp
        self.max_diopter = max_fp
        return min_fp, max_fp

    def to_current_mode(self) -> None:
        """Switch device to current mode (Mode 1)."""
        self.send_command('MwDA', '>xxx')
        self.refresh_active_mode()

    def refresh_active_mode(self) -> OperatingMode:
        """Query active mode from the device and update self.mode.
        
        Returns:
            The active OperatingMode.
        """
        res = self.send_command('MMA', '>xxxB')
        if res is None:
            raise LensCommandError("No response received for active mode query")
        try:
            self.mode = OperatingMode(res[0])
        except ValueError:
            logger.error("Unknown operating mode value %s returned by device", res[0])
            raise LensCommandError(f"Unknown operating mode value {res[0]}")
        return self.mode
