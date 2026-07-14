"""Package-specific exceptions for the Optotune Lens driver."""

class LensError(Exception):
    """Base exception for all Optotune Lens errors."""
    pass


class LensConnectionError(LensError):
    """Raised when there is an issue establishing or maintaining the serial connection."""
    pass


class LensTimeoutError(LensConnectionError):
    """Raised when a read or write operation times out."""
    pass


class LensCRCError(LensError):
    """Raised when the response CRC does not match the computed CRC."""
    pass


class LensCommandError(LensError):
    """Raised when the lens hardware returns an error code or unexpected response."""
    pass


class LensValidationError(LensError, ValueError):
    """Raised when provided arguments (e.g. current, diopter) are out of valid ranges."""
    pass
