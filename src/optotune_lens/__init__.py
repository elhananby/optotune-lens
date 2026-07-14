"""Optotune Lens Python Package.

This package provides a clean, robust, and modern driver for controlling
Optotune electrically tunable lenses over a serial connection.
"""

from .exceptions import (
    LensError,
    LensConnectionError,
    LensTimeoutError,
    LensCRCError,
    LensCommandError,
    LensValidationError,
)
from .lens import Lens, OperatingMode, FirmwareVersion
from .icc import IccLens, IccChannel, IccControllerType
from .utils import crc_16

__all__ = [
    "Lens",
    "OperatingMode",
    "FirmwareVersion",
    "IccLens",
    "IccChannel",
    "IccControllerType",
    "LensError",
    "LensConnectionError",
    "LensTimeoutError",
    "LensCRCError",
    "LensCommandError",
    "LensValidationError",
    "crc_16",
]

__version__ = "0.1.0"
