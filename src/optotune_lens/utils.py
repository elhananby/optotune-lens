"""Utility functions for the Optotune Lens driver."""

def crc_16(data: bytes) -> int:
    """Calculate CRC-16 Modbus (polynomial 0xA001).
    
    Args:
        data: Input bytes to calculate the CRC for.
        
    Returns:
        The 16-bit CRC checksum as an integer.
    """
    crc = 0x0000
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc
