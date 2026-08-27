"""Shared low-level FIT format constants and helpers.

Copied unchanged from FitLab (../FitLab/fitlab/fitbase.py), the tested
sibling project. Keep the two in sync if a bug is ever found.
"""

# Seconds between the Unix epoch and the FIT epoch (1989-12-31T00:00:00Z).
FIT_EPOCH_OFFSET = 631065600

_CRC_TABLE = (
    0x0000, 0xCC01, 0xD801, 0x1400, 0xF001, 0x3C00, 0x2800, 0xE401,
    0xA001, 0x6C00, 0x7800, 0xB401, 0x5000, 0x9C01, 0x8801, 0x4400,
)


def crc16(data, crc=0):
    """Garmin FIT CRC-16 (nibble table algorithm)."""
    for byte in data:
        tmp = _CRC_TABLE[crc & 0xF]
        crc = (crc >> 4) & 0x0FFF
        crc = crc ^ tmp ^ _CRC_TABLE[byte & 0xF]
        tmp = _CRC_TABLE[crc & 0xF]
        crc = (crc >> 4) & 0x0FFF
        crc = crc ^ tmp ^ _CRC_TABLE[(byte >> 4) & 0xF]
    return crc


# base type byte -> (name, size in bytes, invalid sentinel, struct format char)
BASE_TYPES = {
    0x00: ("enum", 1, 0xFF, "B"),
    0x01: ("sint8", 1, 0x7F, "b"),
    0x02: ("uint8", 1, 0xFF, "B"),
    0x83: ("sint16", 2, 0x7FFF, "h"),
    0x84: ("uint16", 2, 0xFFFF, "H"),
    0x85: ("sint32", 4, 0x7FFFFFFF, "i"),
    0x86: ("uint32", 4, 0xFFFFFFFF, "I"),
    0x07: ("string", 1, 0x00, "B"),
    0x88: ("float32", 4, 0xFFFFFFFF, "f"),
    0x89: ("float64", 8, 0xFFFFFFFFFFFFFFFF, "d"),
    0x0A: ("uint8z", 1, 0x00, "B"),
    0x8B: ("uint16z", 2, 0x0000, "H"),
    0x8C: ("uint32z", 4, 0x00000000, "I"),
    0x0D: ("byte", 1, 0xFF, "B"),
    0x8E: ("sint64", 8, 0x7FFFFFFFFFFFFFFF, "q"),
    0x8F: ("uint64", 8, 0xFFFFFFFFFFFFFFFF, "Q"),
    0x90: ("uint64z", 8, 0x0000000000000000, "Q"),
}


def semicircles_to_deg(semi):
    return semi * (180.0 / 2 ** 31)


def deg_to_semicircles(deg):
    return int(round(deg * (2 ** 31) / 180.0))
