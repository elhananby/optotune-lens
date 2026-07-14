"""Unit tests for the ICC-4C/ECC-1C/ICC-1C wrapper using a fake optoICC board (no hardware/mocking of
optoICC internals required, per the IccLens(board, controller) dependency-injection constructor).
"""

import pytest
import serial

from optotune_lens import (
    IccLens,
    IccChannel,
    IccControllerType,
    LensConnectionError,
    LensValidationError,
)
from optotune_lens.icc import optoICC


class FakeStaticInput:
    def __init__(self):
        self.current = {'range': [-2, 2]}
        self.focal_power = {'range': [-50, 50]}
        self._current_value = 0.0
        self._focal_power_value = 0.0
        self.input_selected = False

    def SetAsInput(self):
        self.input_selected = True

    def SetCurrent(self, value):
        self._current_value = value

    def GetCurrent(self):
        return self._current_value

    def SetFocalPower(self, value):
        self._focal_power_value = value

    def GetFocalPower(self):
        return self._focal_power_value


class FakeTemperatureManager:
    def __init__(self, temperature=25.0):
        self.temperature = temperature

    def GetDeviceTemperature(self):
        return self.temperature


class FakeDeviceEEPROM:
    def __init__(self, serial_number=b'ABC12345\x00\x00', eeprom=None):
        self._serial_number = serial_number
        self._eeprom = eeprom if eeprom is not None else bytearray(range(16))

    def GetSerialNumber(self):
        return self._serial_number

    def GetEEPROMSize(self):
        return len(self._eeprom)

    def GetEEPROM(self, index, count):
        return self._eeprom[index:index + count]


class FakeSignalGenerator:
    def __init__(self):
        self.running = False
        self.config = {}
        self.input_selected = False

    def SetUnit(self, value):
        self.config['unit'] = value

    def SetShape(self, value):
        self.config['shape'] = value

    def SetFrequency(self, value):
        self.config['frequency'] = value

    def SetAmplitude(self, value):
        self.config['amplitude'] = value

    def SetOffset(self, value):
        self.config['offset'] = value

    def SetPhase(self, value):
        self.config['phase'] = value

    def SetCycles(self, value):
        self.config['cycles'] = value

    def SetAsInput(self):
        self.input_selected = True

    def Run(self):
        self.running = True

    def Stop(self):
        self.running = False


class FakeAnalog:
    def __init__(self):
        self.lut_type = None
        self.voltages = None
        self.values = None
        self.input_selected = False

    def SetLUTtype(self, value):
        self.lut_type = value

    def SetLUTvoltages(self, value):
        self.voltages = value

    def SetLUTvalues(self, value):
        self.values = value

    def SetAsInput(self):
        self.input_selected = True


class FakeChannel:
    def __init__(self):
        self.StaticInput = FakeStaticInput()
        self.TemperatureManager = FakeTemperatureManager()
        self.DeviceEEPROM = FakeDeviceEEPROM()
        self.SignalGenerator = FakeSignalGenerator()
        self.Analog = FakeAnalog()


class FakeStatus:
    def GetFirmwareVersionMajor(self):
        return 1

    def GetFirmwareVersionMinor(self):
        return 2

    def GetFirmwareVersionRevision(self):
        return 3


class FakeBoardEEPROM:
    def GetSerialNumber(self):
        return b'BOARDSN1'


class FakeConnection:
    def __init__(self):
        self.disconnected = False

    def disconnect(self):
        self.disconnected = True


class FakeBoard:
    def __init__(self, n_channels=1):
        self.channel = [FakeChannel() for _ in range(n_channels)]
        self.Status = FakeStatus()
        self.EEPROM = FakeBoardEEPROM()
        self.Connection = FakeConnection()


@pytest.fixture
def lens():
    return IccLens(FakeBoard(), IccControllerType.ICC1C)


def test_set_get_current(lens):
    channel = lens.channels[0]
    channel.set_current(0.5)
    assert channel._ch.StaticInput.input_selected
    assert channel.get_current() == 0.5


def test_set_current_out_of_range_raises(lens):
    with pytest.raises(LensValidationError):
        lens.channels[0].set_current(5.0)


def test_set_get_diopter(lens):
    channel = lens.channels[0]
    channel.set_diopter(3.0)
    assert channel._ch.StaticInput.input_selected
    assert channel.get_diopter() == 3.0


def test_set_diopter_out_of_range_raises(lens):
    with pytest.raises(LensValidationError):
        lens.channels[0].set_diopter(1000.0)


def test_get_temperature(lens):
    assert lens.channels[0].get_temperature() == 25.0


def test_channel_serial_number(lens):
    assert lens.channels[0].serial_number == 'ABC12345'


def test_eeprom_dump(lens):
    assert lens.channels[0].eeprom_dump() == list(range(16))


def test_run_and_stop_waveform(lens):
    channel = lens.channels[0]
    channel.run_waveform(shape=0, frequency=5.0, amplitude=0.2, offset=0.1, phase=0.0, cycles=3)
    sig_gen = channel._ch.SignalGenerator
    assert sig_gen.input_selected
    assert sig_gen.running
    assert sig_gen.config == {
        'unit': 0, 'shape': 0, 'frequency': 5.0, 'amplitude': 0.2, 'offset': 0.1, 'phase': 0.0, 'cycles': 3,
    }
    channel.stop_waveform()
    assert not sig_gen.running


def test_configure_analog_input(lens):
    channel = lens.channels[0]
    channel.configure_analog_input(voltage_range=[0, 10], value_range=[-2, 3], unit='focal_power')
    analog = channel._ch.Analog
    assert analog.lut_type == 3
    assert analog.voltages == [0, 10]
    assert analog.values == [-2, 3]
    assert analog.input_selected


def test_configure_analog_input_invalid_unit_raises(lens):
    with pytest.raises(LensValidationError):
        lens.channels[0].configure_analog_input(voltage_range=[0, 10], value_range=[-2, 3], unit='bogus')


def test_board_firmware_version_and_serial_number(lens):
    assert lens.firmware_version == '1.2.3'
    assert lens.serial_number == 'BOARDSN1'


def test_context_manager_closes_connection():
    board = FakeBoard()
    with IccLens(board, IccControllerType.ICC1C):
        pass
    assert board.Connection.disconnected


def test_icc4c_exposes_four_channels():
    lens = IccLens(FakeBoard(n_channels=4), IccControllerType.ICC4C)
    assert len(lens.channels) == 4
    assert all(isinstance(ch, IccChannel) for ch in lens.channels)


def test_connect_wraps_connection_failure(monkeypatch):
    def raise_serial_exception(**kwargs):
        raise serial.SerialException("port busy")

    monkeypatch.setattr(optoICC, 'connectIcc1c', raise_serial_exception)
    with pytest.raises(LensConnectionError):
        IccLens.connect('icc1c', port='COM7')


def test_connect_no_port_found_raises_connection_error(monkeypatch):
    monkeypatch.setattr('optotune_lens.icc.get_icc4c_port', lambda: None)
    with pytest.raises(LensConnectionError):
        IccLens.connect('icc1c')


def test_connect_ecc1c_with_ip_address_raises_validation_error():
    with pytest.raises(LensValidationError):
        IccLens.connect('ecc1c', ip_address='10.0.0.5')
