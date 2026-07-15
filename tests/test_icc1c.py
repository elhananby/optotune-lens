"""Unit tests for the ICC1C driver using a mock serial implementation."""

import pytest
from unittest.mock import MagicMock, patch

import serial

from optotune_lens import (
    ICC1C,
    LensConnectionError,
    LensTimeoutError,
    LensValidationError,
    LensCommandError,
)


class MockSerial:
    """A mock implementation of serial.Serial simulating ICC-1C Simple Mode."""

    FP_MIN = -5.0
    FP_MAX = 5.0
    CURRENT_MIN = -500.0
    CURRENT_MAX = 500.0

    def __init__(self, port, baudrate, timeout=1):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.is_open = True
        self.read_buffer = b""
        self.fp = 0.0
        self.current = 0.0
        self.static_replies = {
            "START": "OK",
            "DETECTDEVICE": "EL-16-40-TC",
            "GETDEVICESN": "ANAA1234",
            "GETFPMIN": str(self.FP_MIN),
            "GETFPMAX": str(self.FP_MAX),
            "GETTEMP": "25.5",
        }

    def reset_input_buffer(self):
        pass

    def reset_output_buffer(self):
        pass

    def close(self):
        self.is_open = False

    def write(self, data):
        cmd = data.decode('ascii').strip()

        if cmd.startswith("SETFP="):
            value = float(cmd.split("=", 1)[1])
            if value < self.FP_MIN:
                reply = "OL"
            elif value > self.FP_MAX:
                reply = "OU"
            else:
                self.fp = value
                reply = "OK"
        elif cmd.startswith("SETCURRENT="):
            value = float(cmd.split("=", 1)[1])
            if value < self.CURRENT_MIN:
                reply = "OL"
            elif value > self.CURRENT_MAX:
                reply = "OU"
            else:
                self.current = value
                reply = "OK"
        elif cmd == "GETFP":
            reply = str(self.fp)
        elif cmd == "GETCURRENT":
            reply = str(self.current)
        elif cmd in self.static_replies:
            reply = self.static_replies[cmd]
        else:
            reply = "ERROR"

        self.read_buffer += (reply + "\r\n").encode('ascii')
        return len(data)

    def read(self, size):
        chunk = self.read_buffer[:size]
        self.read_buffer = self.read_buffer[size:]
        return chunk


@patch("serial.Serial", new=MockSerial)
def test_icc1c_init_and_properties():
    """Test successful initialization and property loading."""
    with ICC1C("COM_MOCK") as icc:
        assert icc.device_type == "EL-16-40-TC"
        assert icc.device_serial == "ANAA1234"


@patch("serial.Serial")
def test_icc1c_handshake_fails(mock_serial):
    """Test that connection fails if handshake does not return OK."""
    mock_instance = MagicMock()
    reply_bytes = iter(b"ERROR\r\n")  # iterating bytes yields ints in Python 3

    def fake_read(size):
        try:
            return bytes([next(reply_bytes)])
        except StopIteration:
            return b""

    mock_instance.read.side_effect = fake_read
    mock_serial.return_value = mock_instance

    with pytest.raises(LensConnectionError) as exc_info:
        ICC1C("COM_MOCK")
    assert "did not reply OK" in str(exc_info.value)


@patch("serial.Serial", new=MockSerial)
def test_icc1c_set_and_get_diopter():
    """Test setting and reading back focal power within limits."""
    with ICC1C("COM_MOCK") as icc:
        icc.set_diopter(2.5)
        assert icc.get_diopter() == 2.5


@patch("serial.Serial", new=MockSerial)
def test_icc1c_diopter_out_of_range_raises_validation_error():
    """Test that focal power outside the lens's range raises LensValidationError."""
    with ICC1C("COM_MOCK") as icc:
        with pytest.raises(LensValidationError):
            icc.set_diopter(10.0)  # above FP_MAX

        with pytest.raises(LensValidationError):
            icc.set_diopter(-10.0)  # below FP_MIN


@patch("serial.Serial", new=MockSerial)
def test_icc1c_set_and_get_current():
    """Test setting and reading back current within limits."""
    with ICC1C("COM_MOCK") as icc:
        icc.set_current(100.0)
        assert icc.get_current() == 100.0


@patch("serial.Serial", new=MockSerial)
def test_icc1c_current_out_of_range_raises_validation_error():
    """Test that current outside device limits raises LensValidationError."""
    with ICC1C("COM_MOCK") as icc:
        with pytest.raises(LensValidationError):
            icc.set_current(600.0)  # above CURRENT_MAX

        with pytest.raises(LensValidationError):
            icc.set_current(-600.0)  # below CURRENT_MIN


@patch("serial.Serial", new=MockSerial)
def test_icc1c_get_temperature():
    """Test temperature reading."""
    with ICC1C("COM_MOCK") as icc:
        assert icc.get_temperature() == 25.5


@patch("serial.Serial", new=MockSerial)
def test_icc1c_to_focal_power_mode_validates_lens_support():
    """Test that to_focal_power_mode succeeds when the lens reports FP limits."""
    with ICC1C("COM_MOCK") as icc:
        icc.to_focal_power_mode()  # should not raise


@patch("serial.Serial", new=MockSerial)
def test_icc1c_to_focal_power_mode_raises_without_lens_calibration():
    """Test that to_focal_power_mode raises if the lens has no FP calibration."""
    with ICC1C("COM_MOCK") as icc:
        icc.connection.static_replies["GETFPMIN"] = "NO"
        with pytest.raises(LensCommandError):
            icc.to_focal_power_mode()


@patch("serial.Serial", new=MockSerial)
def test_icc1c_to_current_mode_is_a_noop():
    """Test that to_current_mode doesn't raise (no mode-switch command exists)."""
    with ICC1C("COM_MOCK") as icc:
        assert icc.to_current_mode() is None


@patch("serial.Serial")
def test_icc1c_serial_timeout(mock_serial):
    """Test behavior on serial read timeout."""
    mock_instance = MagicMock()
    mock_instance.read.return_value = b""
    mock_serial.return_value = mock_instance

    with pytest.raises(LensConnectionError):  # LensTimeoutError is-a LensConnectionError
        ICC1C("COM_MOCK")


@patch("serial.Serial", new=MockSerial)
def test_icc1c_unrecognized_command_raises_command_error():
    """Test that an unrecognized command's ERROR reply raises LensCommandError."""
    with ICC1C("COM_MOCK") as icc:
        with pytest.raises(LensCommandError):
            icc._send_set_command("BOGUSCOMMAND")
