"""Unit tests for the optotune_lens package using a mock serial implementation."""

import struct
import pytest
from unittest.mock import MagicMock, patch

import serial

from optotune_lens import (
    Lens,
    OperatingMode,
    FirmwareVersion,
    LensConnectionError,
    LensTimeoutError,
    LensCRCError,
    LensValidationError,
    LensCommandError,
    crc_16,
)


def test_crc_16():
    """Test standard CRC-16 Modbus computation."""
    assert crc_16(b"Start") == 0xA5EA
    assert crc_16(b"\x00A") == 0x30C0
    assert crc_16(b"") == 0x0000


class MockSerial:
    """A mock implementation of serial.Serial to simulate lens communication."""

    def __init__(self, port, baudrate, timeout=1):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.is_open = True
        self.write_buffer = b""
        self.read_buffer = b""
        self.current_mode = 1  # 1 = CURRENT, 5 = FOCAL_POWER

        # Mock responses registry
        # Maps raw command bytes (excluding CRC) to the expected raw response data (excluding CRC/CRLF)
        self.responses = {
            # Handshake
            b"Start": b"Ready\r\n",
            # H: Firmware type
            b"H": b"\x00A",
            # V\x00: Firmware version
            b"V\x00": b"\x00\x02\x05\x00\x0a\x00\x1f",
            # IR...: Device ID
            b"IR\x00\x00\x00\x00\x00\x00\x00\x00": b"\x00\x00MYDEVICE",
            # CrMA\x00\x00: Max current (29000 -> 290.0 mA)
            b"CrMA\x00\x00": b"\x00\x00\x00\x71\x48",
            # PwTA...: Set temp limits (upper=40*16=640, lower=20*16=320)
            b"PwTA" + struct.pack(">hh", 40 * 16, 20 * 16): b"\x00\x00\x00\x05\xd0\x01\x90",
            # PwTA...: Set temp limits (upper=45*16=720, lower=20*16=320)
            b"PwTA" + struct.pack(">hh", 45 * 16, 20 * 16): b"\x00\x00\x00\x05\xd0\x01\x90",
            # X: Lens serial
            b"X": b"\x0012345678",
            # TCA: Temperature (25.5 C -> 25.5 * 16 = 408)
            b"TCA": b"\x00\x00\x00\x01\x98",
            # MwCA: Switch to focal power mode (returns error=0, max_fp=1000, min_fp=-200)
            b"MwCA": b"\x00\x00\x00\x00\x03\xe8\xff\x38",
            # MwDA: Switch to current mode
            b"MwDA": b"\x00\x00\x00",
            # Aw...: Set current
            b"Aw" + struct.pack(">h", 1412): None,  # (100.0 mA -> raw 1412)
            # PwDA...: Set diopter (3.0 -> raw 600 if type 'A' otherwise raw 600)
            b"PwDA" + struct.pack(">h", 1600) + b"\x00\x00": None,  # type 'A': (3.0 + 5) * 200 = 1600
        }

    @property
    def in_waiting(self):
        return len(self.read_buffer)

    def reset_input_buffer(self):
        pass

    def reset_output_buffer(self):
        pass

    def close(self):
        self.is_open = False

    def write(self, data):
        self.write_buffer += data
        
        # Process the written data
        # Handshake is unique: it does not have CRC
        if data == b"Start":
            self.read_buffer += b"Ready\r\n"
            return len(data)

        # Check for CRC-16
        if len(data) < 2:
            return len(data)

        payload = data[:-2]
        received_crc, = struct.unpack('<H', data[-2:])
        
        if received_crc != crc_16(payload):
            # CRC is invalid, simulate silence or error response
            return len(data)

        # Handle state changes based on commands written
        if payload == b"MwCA":
            self.current_mode = 5
        elif payload == b"MwDA":
            self.current_mode = 1

        # Find mock response
        if payload == b"MMA":
            resp_payload = struct.pack(">xxxB", self.current_mode)
        elif payload in self.responses:
            resp_payload = self.responses[payload]
        else:
            resp_payload = None

        if resp_payload is not None:
            # Format of reply: payload + CRC-16(payload) + \r\n
            if b"\r\n" in resp_payload and payload == b"Start":
                self.read_buffer += resp_payload
            else:
                crc_val = crc_16(resp_payload)
                self.read_buffer += resp_payload + struct.pack('<H', crc_val) + b"\r\n"
        return len(data)

    def read(self, size):
        chunk = self.read_buffer[:size]
        self.read_buffer = self.read_buffer[size:]
        return chunk

    def readline(self):
        if b"\n" in self.read_buffer:
            idx = self.read_buffer.index(b"\n") + 1
            chunk = self.read_buffer[:idx]
            self.read_buffer = self.read_buffer[idx:]
            return chunk
        chunk = self.read_buffer
        self.read_buffer = b""
        return chunk


@patch("serial.Serial", new=MockSerial)
def test_lens_init_and_properties():
    """Test successful initialization and property loading."""
    with Lens("COM_MOCK") as lens:
        assert lens.lens_serial == "12345678"
        assert lens.firmware_type == "A"
        assert isinstance(lens.firmware_version, FirmwareVersion)
        assert lens.firmware_version.major == 2
        assert lens.firmware_version.minor == 5
        assert lens.firmware_version.build == 10
        assert lens.firmware_version.patch == 31
        assert str(lens.firmware_version) == "2.5.10.31"
        assert lens.device_id == "MYDEVICE"
        assert lens.max_output_current == 290.0
        assert lens.mode == OperatingMode.CURRENT


@patch("serial.Serial")
def test_lens_handshake_fails(mock_serial):
    """Test that connection fails if handshake does not match."""
    mock_instance = MagicMock()
    mock_instance.readline.return_value = b"WrongResponse\r\n"
    mock_serial.return_value = mock_instance

    with pytest.raises(LensConnectionError) as exc_info:
        Lens("COM_MOCK")
    assert "did not reply to handshake" in str(exc_info.value)


@patch("serial.Serial", new=MockSerial)
def test_lens_get_temperature():
    """Test temperature reading and scaling."""
    with Lens("COM_MOCK") as lens:
        # TCA returns 408 raw -> 408 * 0.0625 = 25.5 C
        assert lens.get_temperature() == 25.5


@patch("serial.Serial", new=MockSerial)
def test_lens_mode_switching_and_control():
    """Test switching operating modes and setting values."""
    with Lens("COM_MOCK") as lens:
        # Initially in CURRENT mode
        assert lens.mode == OperatingMode.CURRENT
        
        # Set current within limits
        lens.set_current(100.0)
        
        # Switched to focal power mode
        min_fp, max_fp = lens.to_focal_power_mode()
        # MwCA returns error=0, max=1000, min=-200
        # Scaling for type 'A': /200 - 5
        # min: -200/200 - 5 = -6.0, max: 1000/200 - 5 = 0.0
        assert min_fp == -6.0
        assert max_fp == 0.0
        assert lens.mode == OperatingMode.FOCAL_POWER
        
        # Set diopter within limits (-6.0 <= diopter <= 0.0)
        # Wait, in MockSerial we registry set diopter 3.0? No, let's update min_fp/max_fp range in tests.
        # Let's adjust limits to test validation errors.
        
        # Let's change safety limits to 20 to 45
        lens.set_temperature_limits(20.0, 45.0)
        
        # If we try to set diopter outside limit, raise validation error
        with pytest.raises(LensValidationError):
            lens.set_diopter(3.0)  # max is 2.44, so 3.0 is invalid
            
        with pytest.raises(LensValidationError):
            lens.set_diopter(-4.0)  # min is -3.0, so -4.0 is invalid


@patch("serial.Serial", new=MockSerial)
def test_lens_current_validation():
    """Test that setting current outside maximum current raises validation error."""
    with Lens("COM_MOCK") as lens:
        assert lens.max_output_current == 290.0
        
        with pytest.raises(LensValidationError):
            lens.set_current(300.0)
            
        with pytest.raises(LensValidationError):
            lens.set_current(-300.0)


@patch("serial.Serial", new=MockSerial)
def test_lens_temperature_limits_validation():
    """Test that setting temperature limits outside the supported range raises validation error."""
    with Lens("COM_MOCK") as lens:
        with pytest.raises(LensValidationError):
            lens.set_temperature_limits(20.0, 3000.0)

        with pytest.raises(LensValidationError):
            lens.set_temperature_limits(-3000.0, 40.0)


@patch("serial.Serial")
def test_lens_serial_timeout(mock_serial):
    """Test behavior on serial read timeout."""
    mock_instance = MagicMock()
    # Handshake success
    mock_instance.readline.return_value = b"Ready\r\n"
    # Return empty bytes for read to simulate timeout
    mock_instance.read.return_value = b""
    mock_serial.return_value = mock_instance

    with pytest.raises(LensConnectionError):  # During __init__, get_firmware_type will timeout
        Lens("COM_MOCK")


@patch("serial.Serial", new=MockSerial)
def test_lens_crc_error_handling():
    """Test CRC mismatch detection in responses."""
    with Lens("COM_MOCK") as lens:
        # Force a command return that has an invalid CRC
        # We mock serial.read directly to return data with wrong CRC
        original_read = lens.connection.read
        
        def bad_read(size):
            # Normal size for H command (Firmware Type) is 2 (payload) + 4 (crc/newline) = 6
            # Returns valid payload b'\x00A', but invalid CRC b'\x00\x00' and CRLF
            return b"\x00A\x00\x00\r\n"
            
        lens.connection.read = bad_read
        
        with pytest.raises(LensCRCError):
            lens.get_firmware_type()


@patch("serial.Serial", new=MockSerial)
def test_lens_drains_stray_bytes_before_next_command():
    """Test that stray bytes left in the input buffer (e.g. an unsolicited
    error reply to a silent-write command like set_current) don't desync
    the next command's response parsing."""
    with Lens("COM_MOCK") as lens:
        # Simulate an "N\r\n" error reply that the driver sent in response
        # to a corrupted set_current command but that nobody read.
        lens.connection.read_buffer += b"N\r\n"

        # The next command should still parse correctly instead of
        # misinterpreting the stray bytes as part of its own response.
        assert lens.get_temperature() == 25.5
