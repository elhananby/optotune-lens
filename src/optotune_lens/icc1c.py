"""Core interface and implementation for the Optotune ICC-1C controller.

Talks the controller's ASCII "Simple Mode" protocol (RS-232-style,
CR/LF-terminated commands). Unlike the Lens Driver 4, the ICC-1C converts
between raw current and diopters itself using the connected lens's onboard
EEPROM calibration, so no host-side scaling is needed here.
"""

import logging
from typing import Optional

import serial

from .exceptions import (
    LensError,
    LensConnectionError,
    LensTimeoutError,
    LensCommandError,
    LensValidationError,
)

logger = logging.getLogger("optotune_lens.icc1c")


class ICC1C:
    """Python interface for an Optotune ICC-1C controller (Simple Mode protocol).

    This class handles serial communication and reply-status checking. It
    does not cover Pro Mode (binary register protocol) features such as
    Smart Step, the signal generator, or vectors — those are configured
    once via Optotune Cockpit and persisted on the device.
    """

    def __init__(self, port: str, baudrate: int = 115200, debug: bool = False) -> None:
        """Open the serial connection and query hardware status.

        Args:
            port: Serial port name (e.g. 'COM7', '/dev/ttyUSB0').
            baudrate: Baud rate. The ICC-1C auto-detects the baud rate on
                receiving the handshake command, so this is arbitrary.
            debug: If True, log detailed TX/RX dumps to stdout.

        Raises:
            LensError: If the serial connection, handshake, or device
                detection fail.
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

        try:
            logger.info("Connecting to ICC-1C on %s...", port)
            self.connection = serial.Serial(port, baudrate, timeout=1)
            self.connection.reset_input_buffer()
            self.connection.reset_output_buffer()

            reply = self.send_command("START")
            if reply != "OK":
                raise LensConnectionError(
                    f"ICC-1C did not reply OK to handshake. Got {reply!r}"
                )

            self.device_type: str = self.send_command("DETECTDEVICE")
            if self.device_type in ("NO", "ERROR"):
                raise LensConnectionError("ICC-1C did not detect a connected lens")

            self.device_serial: Optional[str] = self.get_device_serial_number()

            logger.info(
                "ICC-1C initialization complete: Device %s, Serial %s",
                self.device_type, self.device_serial
            )
        except Exception as e:
            if hasattr(self, 'connection') and self.connection:
                self.connection.close()
            if not isinstance(e, LensError):
                raise LensConnectionError(f"Failed to initialize ICC-1C on port {port}: {e}") from e
            raise

    def __enter__(self) -> 'ICC1C':
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    def close(self) -> None:
        """Close the serial connection to the controller."""
        if hasattr(self, 'connection') and self.connection and self.connection.is_open:
            logger.info("Closing connection to ICC-1C.")
            self.connection.close()

    def send_command(self, command: str) -> str:
        """Send an ASCII Simple Mode command and return the decoded reply line.

        Args:
            command: The command, without the CR/LF terminator (e.g. 'GETFP').

        Returns:
            The reply line, decoded and stripped of the CR/LF terminator.

        Raises:
            LensConnectionError: If serial writing/reading fails.
            LensTimeoutError: If no CR/LF-terminated reply is received before
                the read times out.
        """
        line = (command + "\r\n").encode('ascii')

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("TX: %r", line)

        try:
            self.connection.write(line)
        except serial.SerialException as e:
            raise LensConnectionError(f"Failed to write to serial port: {e}") from e

        buf = b""
        try:
            while not buf.endswith(b"\r\n"):
                chunk = self.connection.read(1)
                if not chunk:
                    break
                buf += chunk
        except serial.SerialException as e:
            raise LensConnectionError(f"Failed to read from serial port: {e}") from e

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("RX: %r", buf)

        if not buf.endswith(b"\r\n"):
            raise LensTimeoutError(f"Timeout waiting for reply to {command!r}, got {buf!r}")

        return buf.decode('ascii').strip()

    def _send_set_command(self, command: str) -> None:
        """Send a Simple Mode command that returns an OK/NO/OL/OU/ERROR status.

        Raises:
            LensValidationError: If the device rejects the command because
                the parameter hit its lower (OL) or upper (OU) limit.
            LensCommandError: If the device rejects the command for any
                other reason (NO) or the command is unavailable (ERROR).
        """
        reply = self.send_command(command)
        if reply == "OK":
            return
        if reply in ("OL", "OU"):
            raise LensValidationError(f"Command {command!r} rejected: {reply} (parameter out of range)")
        raise LensCommandError(f"Command {command!r} rejected: {reply}")

    def get_device_serial_number(self) -> Optional[str]:
        """Query the serial number of the connected lens, if detected."""
        reply = self.send_command("GETDEVICESN")
        return None if reply == "NO" else reply

    def to_focal_power_mode(self) -> None:
        """Validate that the connected lens supports focal power mode.

        Simple Mode has no explicit mode-switch command — SETFP/SETCURRENT
        are independent, always-available commands. This only checks that
        the device reports usable focal power limits.

        Raises:
            LensCommandError: If the connected lens has no EEPROM/focal
                power calibration data.
        """
        if self.send_command("GETFPMIN") == "NO":
            raise LensCommandError(
                "Connected lens does not support focal power mode (no EEPROM detected?)"
            )

    def to_current_mode(self) -> None:
        """No-op compatibility shim; SETCURRENT is always available."""
        return None

    def set_current(self, current_mA: float) -> None:
        """Set output current in mA.

        Raises:
            LensValidationError: If the value is out of the device's or
                connected lens's current limits.
        """
        self._send_set_command(f"SETCURRENT={current_mA}")

    def get_current(self) -> float:
        """Read the active output current in mA."""
        return float(self.send_command("GETCURRENT"))

    def set_diopter(self, diopter: float) -> None:
        """Set focal power in diopters.

        Raises:
            LensValidationError: If the value is out of the connected
                lens's focal power range.
        """
        self._send_set_command(f"SETFP={diopter}")

    def get_diopter(self) -> Optional[float]:
        """Read the active focal power in diopters, or None if no lens is detected."""
        reply = self.send_command("GETFP")
        return None if reply == "NO" else float(reply)

    def get_diopter_min(self) -> Optional[float]:
        """Read the lower focal power limit of the connected lens, or None if undetected."""
        reply = self.send_command("GETFPMIN")
        return None if reply == "NO" else float(reply)

    def get_diopter_max(self) -> Optional[float]:
        """Read the upper focal power limit of the connected lens, or None if undetected."""
        reply = self.send_command("GETFPMAX")
        return None if reply == "NO" else float(reply)

    def get_temperature(self) -> float:
        """Read the current temperature of the connected device in Celsius."""
        return float(self.send_command("GETTEMP"))

    def set_temperature_limit(self, limit: float) -> None:
        """Set the operational temperature limit in Celsius."""
        self._send_set_command(f"SETTEMPLIM={limit}")
