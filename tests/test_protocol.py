import pytest

from custom_components.baseus_gan240.protocol import (
    ACK,
    QUERY,
    STATUS_HEADER,
    crc16,
    frame,
    mutate_mask,
    parse_status,
    write_frame,
)


@pytest.mark.parametrize(
    ("raw", "mask"),
    [
        ("9AAA030012020100002A89", 0),
        ("9AAA03001202010004E988", 4),
    ],
)
def test_physical_fixtures(raw, mask):
    assert parse_status(bytes.fromhex(raw)) == mask


def test_known_writes_and_query():
    assert write_frame(4).hex().upper() == "9AAA100012000102010004266F"
    assert write_frame(0).hex().upper() == "9AAA100012000102010000E56E"
    assert frame(bytes.fromhex("9AAA0300120001")) == QUERY
    assert crc16(b"123456789") == 0x4B37


@pytest.mark.parametrize(
    "raw",
    [
        ACK,
        QUERY,
        b"",
        bytes.fromhex("9AAA030012020100042A89"),
        bytes.fromhex("9AAA03001202010004E9"),
        bytes.fromhex("9AAA03001202010004E98800"),
        frame(bytes.fromhex("9AAA10001202010004")),
        frame(bytes.fromhex("9AAA03001202020599")),
    ],
)
def test_reject_nonstatus(raw):
    assert parse_status(raw) is None


def test_every_truncation_and_corrupted_byte():
    raw = frame(STATUS_HEADER + b"\xdc\x02")
    for size in range(11):
        assert parse_status(raw[:size]) is None
    for i in range(11):
        corrupt = bytearray(raw)
        corrupt[i] ^= 1
        assert parse_status(corrupt) is None


@pytest.mark.parametrize(("port", "bit"), [("c1", 4), ("c2", 8), ("c3", 16), ("a", 32)])
@pytest.mark.parametrize("on", [True, False])
def test_all_16_bit_mutations(port, bit, on):
    for mask in range(65536):
        changed = mutate_mask(mask, port, on)
        assert (changed & ~bit) == (mask & ~bit)
        assert bool(changed & bit) is not on


@pytest.mark.parametrize("mask", [-1, 65536])
def test_invalid_mask(mask):
    with pytest.raises(ValueError):
        mutate_mask(mask, "c1", True)
