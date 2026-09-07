"""Strict, stateless Baseus frames. Never interpret acknowledgements as state."""

from .const import PORT_BITS

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


def parse_status(data: bytes) -> int | None:
    """Accept only the exact 11-byte status grammar, including its checksum."""
    if len(data) != 11 or not data.startswith(STATUS_HEADER):
        return None
    if crc16(data[:-2]) != int.from_bytes(data[-2:], "big"):
        return None
    return int.from_bytes(data[7:9], "big")


def mutate_mask(mask: int, port: str, on: bool) -> int:
    """Change one USB disable bit; retain DC, shutdown and unknown bits."""
    if not 0 <= mask <= 0xFFFF:
        raise ValueError("Mask must be an unsigned 16-bit integer")
    bit = PORT_BITS[port]
    return mask & ~bit if on else mask | bit


def write_frame(mask: int) -> bytes:
    return frame(WRITE_HEADER + mask.to_bytes(2, "big"))
