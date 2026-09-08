"""Strict, stateless Baseus frames. Never interpret acknowledgements as state."""

from .const import PORT_BITS

QUERY_HEADER = bytes.fromhex("9AAA03")
STATUS_HEADER = bytes.fromhex("9AAA0300120201")
WRITE_HEADER = bytes.fromhex("9AAA10001200010201")
ACK = bytes.fromhex("9AAA10001200010599")
QUERY = bytes.fromhex("9AAA0300120001C61C")


def crc16(data: bytes) -> int:
    """CRC-16/MODBUS, encoded on this wire high byte first."""
    crc = 0xFFFF
    for value in data:
        crc ^= value
        for _ in range(8):
            crc = (crc >> 1) ^ (0xA001 if crc & 1 else 0)
    return crc


def frame(body: bytes) -> bytes:
    return body + crc16(body).to_bytes(2, "big")


def query_frame(code: str) -> bytes:
    """Build the app's read-register request for a four-digit hex code."""
    if len(code) != 4:
        raise ValueError("Register code must contain four hex digits")
    try:
        register = bytes.fromhex(code)
    except ValueError as err:
        raise ValueError("Register code must contain four hex digits") from err
    return frame(QUERY_HEADER + register + bytes.fromhex("0001"))


def parse_register(data: bytes) -> tuple[str, int, int] | None:
    """Return register code, scale byte and unsigned value from a strict reply."""
    if (
        len(data) != 11
        or not data.startswith(QUERY_HEADER)
        or data[5] != 0x02
        or crc16(data[:-2]) != int.from_bytes(data[-2:], "big")
    ):
        return None
    return data[3:5].hex().upper(), data[6], int.from_bytes(data[7:9], "big")


def parse_status(data: bytes) -> int | None:
    """Accept only the exact 11-byte status grammar, including its checksum."""
    if len(data) != 11 or not data.startswith(STATUS_HEADER):
        return None
    if crc16(data[:-2]) != int.from_bytes(data[-2:], "big"):
        return None
    return int.from_bytes(data[7:9], "big")


def mutate_mask(mask: int, port: str, on: bool) -> int:
    """Change one output disable bit while retaining every unrelated bit."""
    if not 0 <= mask <= 0xFFFF:
        raise ValueError("Mask must be an unsigned 16-bit integer")
    bit = PORT_BITS[port]
    return mask & ~bit if on else mask | bit


def write_frame(mask: int) -> bytes:
    return frame(WRITE_HEADER + mask.to_bytes(2, "big"))
