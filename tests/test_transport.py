import asyncio

import pytest

from custom_components.baseus_gan240.const import NOTIFY_UUID, SERVICE_UUID, WRITE_UUID
from custom_components.baseus_gan240.protocol import (
    ACK,
    QUERY,
    STATUS_HEADER,
    frame,
    parse_register,
    query_frame,
)
from custom_components.baseus_gan240.transport import BaseusError, BaseusTransport


def status(mask):
    return frame(STATUS_HEADER + mask.to_bytes(2, "big"))


def register_response(code, scale, value):
    return frame(
        bytes.fromhex("9AAA03" + code + "02")
        + bytes([scale])
        + value.to_bytes(2, "big")
    )


class FakeClient:
    def __init__(self, device, disconnected):
        self.device = device
        self.disconnected = disconnected
        self.callback = None
        self.closed = False
        self.is_connected = True
        self.services = self
        self.properties = ["write-without-response", "notify"]

    def get_service(self, uuid):
        assert uuid == SERVICE_UUID
        return None if self.device.missing else self

    def get_characteristic(self, uuid):
        assert uuid in (WRITE_UUID, NOTIFY_UUID)
        return self

    async def start_notify(self, uuid, callback):
        assert uuid == NOTIFY_UUID
        self.callback = callback
        # Subscription-time stale frame and ACK must never be retained.
        callback(None, status(0x0599))
        callback(None, ACK)

    async def write_gatt_char(self, uuid, payload, response):
        assert uuid == WRITE_UUID and response is False
        loop = asyncio.get_running_loop()
        if payload.startswith(bytes.fromhex("9AAA03")):
            self.device.queries += 1
            self.device.queried.set()
            # Deliver queued pre-query status while the query write is in flight.
            self.callback(None, status(0x0599))
            loop.call_soon(self.callback, None, status(0x0599))
            await asyncio.sleep(0)
            if self.device.drop:
                self.disconnected(self)
            if not self.device.silent:
                loop.call_later(0.001, self.callback, None, ACK)
                code = payload[3:5].hex().upper()
                reply = (
                    status(self.device.mask)
                    if code == "0012"
                    else register_response(code, *self.device.registers[code])
                )
                loop.call_later(0.002, self.callback, None, reply)
        else:
            self.device.writes.append(bytes(payload))
            if self.callback is not None:
                loop.call_later(0.001, self.callback, None, ACK)
            self.device.mask = int.from_bytes(payload[9:11], "big")
            if self.device.write_fail:
                raise OSError("uncertain acceptance")
            if self.device.mismatch:
                self.device.mask ^= 1
            if self.device.silent_after_write:
                self.device.silent = True
            # A previous connection's callbacks cannot fulfill verification.
            if len(self.device.clients) >= 2:
                old = self.device.clients[-2].callback
                loop.call_later(0.003, old, None, status(self.device.mask))

    async def disconnect(self):
        self.closed = True
        self.is_connected = False
        if self.device.disconnect_fail:
            raise OSError("disconnect failed")


class FakeDevice:
    def __init__(self, mask=0xDC03):
        self.mask = mask
        self.clients = []
        self.writes = []
        self.queries = 0
        self.queried = asyncio.Event()
        self.silent = self.drop = self.write_fail = self.mismatch = False
        self.silent_after_write = self.missing = self.disconnect_fail = False
        self.registers = {"001E": (10, 1234), "000B": (1, 0x8278)}

    async def connect(self, disconnected):
        client = FakeClient(self, disconnected)
        self.clients.append(client)
        return client

    def transport(self):
        return BaseusTransport(
            self.connect, timeout=0.08, connect_timeout=0.08, drain_time=0
        )


async def test_read_rejects_queued_and_inflight_stale_frames():
    device = FakeDevice()
    assert await device.transport().read() == 0xDC03
    assert device.writes == []
    assert all(c.closed for c in device.clients)


async def test_read_multiple_registers_on_one_connection():
    device = FakeDevice()
    values = await device.transport().read_registers(("0012", "001E", "000B"))
    assert values == {
        "0012": (1, device.mask),
        "001E": (10, 1234),
        "000B": (1, 0x8278),
    }
    assert device.queries == 3
    assert len(device.clients) == 1 and device.clients[0].closed


def test_generic_query_and_response_validation():
    assert query_frame("0012") == QUERY
    reply = register_response("001E", 10, 1234)
    assert parse_register(reply) == ("001E", 10, 1234)
    assert parse_register(reply[:-1] + b"\x00") is None
    with pytest.raises(ValueError):
        query_frame("XYZ")


async def test_concurrent_requests_preserve_unknown_and_other_ports():
    device = FakeDevice()
    transport = device.transport()
    await asyncio.gather(
        transport.set_port("c1", False), transport.set_port("a", False)
    )
    assert device.mask == 0xDC27
    assert len(device.writes) == 2
    assert device.queries == 4
    assert all(c.closed for c in device.clients)


async def test_noop_requires_fresh_read_without_write():
    device = FakeDevice(4)
    assert await device.transport().set_port("c1", False) == 4
    assert not device.writes
    assert device.queries == 1


@pytest.mark.parametrize("fault", ["silent", "drop", "missing"])
async def test_read_failures_never_write(fault):
    device = FakeDevice()
    setattr(device, fault, True)
    with pytest.raises(BaseusError):
        await device.transport().set_port("c2", False)
    assert not device.writes
    assert all(c.closed for c in device.clients)


@pytest.mark.parametrize("fault", ["write_fail", "mismatch", "silent_after_write"])
async def test_uncertain_write_is_never_retried(fault):
    device = FakeDevice()
    setattr(device, fault, True)
    with pytest.raises(BaseusError):
        await device.transport().set_port("c2", False)
    assert len(device.writes) == 1
    assert all(c.closed for c in device.clients)


async def test_next_request_after_uncertain_write_reads_actual_state():
    device = FakeDevice()
    transport = device.transport()
    device.write_fail = True
    with pytest.raises(BaseusError):
        await transport.set_port("c2", False)
    device.write_fail = False
    assert await transport.set_port("c2", False) == device.mask
    assert len(device.writes) == 1  # fresh read sees first write took effect
    assert device.queries == 2


async def test_old_connection_callback_cannot_verify():
    device = FakeDevice()
    device.silent_after_write = True
    with pytest.raises(BaseusError):
        await device.transport().set_port("c1", False)
    assert device.queries == 2
    assert len(device.writes) == 1


async def test_close_cancels_active_and_rejects_queued_operations():
    device = FakeDevice()
    device.silent = True
    transport = device.transport()
    running = asyncio.create_task(transport.read())
    await device.queried.wait()
    queued = asyncio.create_task(transport.set_port("a", False))
    await transport.close()
    with pytest.raises(asyncio.CancelledError):
        await running
    with pytest.raises(BaseusError, match="unloaded"):
        await queued
    assert not device.writes
    assert all(c.closed for c in device.clients)


async def test_connection_timeout():
    async def connect(_):
        await asyncio.sleep(1)

    with pytest.raises(BaseusError):
        await BaseusTransport(connect, connect_timeout=0.001).read()


async def test_disconnect_failure_blocks_control():
    device = FakeDevice()
    device.disconnect_fail = True
    with pytest.raises(BaseusError):
        await device.transport().set_port("a", False)
    assert not device.writes


@pytest.mark.parametrize("phase", ["notify", "query", "control"])
async def test_bounded_gatt_operations(phase):
    device = FakeDevice()
    original_connect = device.connect

    async def connect(callback):
        client = await original_connect(callback)
        original_write = client.write_gatt_char

        async def write(uuid, payload, response):
            if (phase == "query" and payload == QUERY) or (
                phase == "control" and payload != QUERY
            ):
                await asyncio.sleep(1)
            await original_write(uuid, payload, response)

        async def notify(*_):
            await asyncio.sleep(1)

        client.write_gatt_char = write
        if phase == "notify":
            client.start_notify = notify
        return client

    transport = BaseusTransport(connect, timeout=0.02, drain_time=0)
    with pytest.raises(BaseusError):
        await transport.set_port("c1", False)
    assert all(c.closed for c in device.clients)
    assert not device.writes


async def test_only_ack_and_corrupt_frames_timeout():
    device = FakeDevice()
    original_connect = device.connect

    async def connect(callback):
        client = await original_connect(callback)

        async def write(*args, **kwargs):
            loop = asyncio.get_running_loop()
            loop.call_later(0.001, client.callback, None, ACK)
            loop.call_later(0.002, client.callback, None, b"\x9a\xaa")
            loop.call_later(0.003, client.callback, None, status(4)[:-1] + b"\x00")

        client.write_gatt_char = write
        return client

    with pytest.raises(BaseusError):
        await BaseusTransport(connect, timeout=0.02, drain_time=0).read()


async def test_required_characteristic_properties():
    device = FakeDevice()
    original_connect = device.connect

    async def connect(callback):
        client = await original_connect(callback)
        client.properties = ["read"]
        return client

    with pytest.raises(BaseusError, match="characteristics"):
        await BaseusTransport(connect).read()
    assert device.clients[0].closed


@pytest.mark.parametrize("repeat_cancel", [False, True])
async def test_close_during_disconnect_drains_owned_cleanup(repeat_cancel):
    device = FakeDevice()
    started, release = asyncio.Event(), asyncio.Event()
    original_connect = device.connect
    disconnects = []

    async def connect(callback):
        client = await original_connect(callback)
        original_disconnect = client.disconnect

        async def disconnect():
            disconnects.append(asyncio.current_task())
            started.set()
            await release.wait()
            await original_disconnect()

        client.disconnect = disconnect
        return client

    transport = BaseusTransport(connect, timeout=1, drain_time=0)
    running = asyncio.create_task(transport.set_port("a", False))
    await started.wait()
    closing = asyncio.create_task(transport.close())
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    if repeat_cancel:
        for _ in range(3):
            running.cancel()
            closing.cancel()
            await asyncio.sleep(0)
    assert not closing.done()
    assert not running.done()
    assert transport._lock.locked()
    assert not disconnects[0].done()
    release.set()
    if repeat_cancel:
        with pytest.raises(asyncio.CancelledError):
            await closing
    else:
        await closing
    with pytest.raises(asyncio.CancelledError):
        await running
    await transport.close()  # Idempotent even after cancelling a close caller.
    assert len(disconnects) == 1 and disconnects[0].done()
    assert all(c.closed for c in device.clients)
    assert not device.writes
    assert not transport._lock.locked()


async def test_close_disconnect_timeout_is_bounded():
    device = FakeDevice()
    started, stopped = asyncio.Event(), asyncio.Event()

    async def connect(callback):
        client = await device.connect(callback)

        async def disconnect():
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()

        client.disconnect = disconnect
        return client

    transport = BaseusTransport(connect, timeout=0.03, drain_time=0)
    running = asyncio.create_task(transport.set_port("a", False))
    await started.wait()
    await asyncio.wait_for(transport.close(), timeout=0.5)
    with pytest.raises(BaseusError):
        await running
    assert stopped.is_set()
    assert not transport._lock.locked()
    assert not device.writes


@pytest.mark.parametrize("late_failed_callback", [False, True])
async def test_retry_failed_attempt_does_not_poison_healthy_client(
    late_failed_callback,
):
    device = FakeDevice()

    async def connect(callback):
        failed = FakeClient(device, callback)
        failed.is_connected = False
        callback(failed)
        client = await device.connect(callback)
        if late_failed_callback:
            asyncio.get_running_loop().call_later(0.001, callback, failed)
        return client

    transport = BaseusTransport(connect, timeout=0.04, drain_time=0)
    assert await transport.set_port("a", False) == device.mask
    assert len(device.writes) == 1
    assert all(c.closed for c in device.clients)


async def test_disconnected_returned_client_rejected_before_io():
    device = FakeDevice()

    async def connect(callback):
        client = await device.connect(callback)
        client.is_connected = False
        callback(client)  # Before connector returns: checked through live state.
        return client

    with pytest.raises(BaseusError, match="establishment"):
        await BaseusTransport(connect).set_port("a", False)
    assert not device.queries and not device.writes
    assert device.clients[0].closed


@pytest.mark.parametrize("callback_delivered", [False, True])
@pytest.mark.parametrize("phase", ["query", "control"])
async def test_established_connection_loss_fails_closed(callback_delivered, phase):
    device = FakeDevice()

    async def connect(callback):
        client = await device.connect(callback)
        original_write = client.write_gatt_char

        async def write(uuid, payload, response):
            await original_write(uuid, payload, response)
            if (phase == "query") == (payload == QUERY):
                client.is_connected = False
                if callback_delivered:
                    callback(client)

        client.write_gatt_char = write
        return client

    with pytest.raises(BaseusError, match="[Dd]isconnected"):
        await BaseusTransport(connect, timeout=0.04, drain_time=0).set_port("a", False)
    assert len(device.writes) == (1 if phase == "control" else 0)
    assert all(c.closed for c in device.clients)


async def test_legitimate_reply_during_write_still_fails_closed():
    device = FakeDevice()

    async def connect(callback):
        client = await device.connect(callback)

        async def write(*args, **kwargs):
            client.callback(None, status(device.mask))
            await asyncio.sleep(0)

        client.write_gatt_char = write
        return client

    with pytest.raises(BaseusError):
        await BaseusTransport(connect, timeout=0.02, drain_time=0).set_port("a", False)
    assert not device.writes
    assert all(c.closed for c in device.clients)


@pytest.mark.parametrize(
    "failure",
    [TimeoutError("AA:BB:CC:DD:EE:FF secret"), OSError("AA:BB:CC:DD:EE:FF secret")],
)
async def test_connect_failure_logs_only_stage_category(caplog, failure):
    async def connect(_callback):
        raise failure

    with pytest.raises(BaseusError):
        await BaseusTransport(connect).read()
    assert "stage=connect" in caplog.text
    assert (
        "category=timeout" in caplog.text
        if isinstance(failure, TimeoutError)
        else "category=backend" in caplog.text
    )
    assert "AA:BB" not in caplog.text
    assert "secret" not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


async def test_silent_status_stage_logged_and_slot_released(caplog):
    device = FakeDevice()
    device.silent = True
    with pytest.raises(BaseusError):
        await device.transport().read()
    assert "stage=status_wait category=timeout" in caplog.text
    assert all(client.closed for client in device.clients)
    assert not device.writes


async def test_missing_gatt_stage_logged(caplog):
    device = FakeDevice()
    device.missing = True
    with pytest.raises(BaseusError):
        await device.transport().read()
    assert "stage=validate_gatt category=validation" in caplog.text
    assert all(client.closed for client in device.clients)


async def test_queued_control_waits_for_ack_before_disconnect():
    device = FakeDevice(4)
    original_connect = device.connect

    async def connect(callback):
        client = await original_connect(callback)
        original_write = client.write_gatt_char

        async def write(uuid, payload, response):
            if payload == QUERY:
                return await original_write(uuid, payload, response)
            device.writes.append(bytes(payload))

            def deliver():
                if client.closed or client.callback is None:
                    return
                device.mask = int.from_bytes(payload[9:11], "big")
                client.callback(None, ACK)

            asyncio.get_running_loop().call_later(0.002, deliver)

        client.write_gatt_char = write
        return client

    transport = BaseusTransport(
        connect, timeout=0.04, connect_timeout=0.04, drain_time=0
    )
    assert await transport.set_port("c2", False) == 12
    assert len(device.writes) == 1
    assert all(client.closed for client in device.clients)


@pytest.mark.parametrize("reply", [None, ACK[:-1] + b"\x00", status(12)])
async def test_control_requires_exact_post_dispatch_ack(reply):
    device = FakeDevice(4)
    original_connect = device.connect

    async def connect(callback):
        client = await original_connect(callback)
        original_write = client.write_gatt_char

        async def write(uuid, payload, response):
            if payload == QUERY:
                return await original_write(uuid, payload, response)
            device.writes.append(bytes(payload))
            if reply is not None:
                asyncio.get_running_loop().call_later(
                    0.001, client.callback, None, reply
                )

        client.write_gatt_char = write
        return client

    transport = BaseusTransport(
        connect, timeout=0.02, connect_timeout=0.04, drain_time=0
    )
    with pytest.raises(BaseusError):
        await transport.set_port("c2", False)
    assert len(device.writes) == 1
    assert device.queries == 1
    assert all(client.closed for client in device.clients)


async def test_control_ack_during_dispatch_is_retained():
    device = FakeDevice(4)
    original_connect = device.connect

    async def connect(callback):
        client = await original_connect(callback)
        original_write = client.write_gatt_char

        async def write(uuid, payload, response):
            if payload == QUERY:
                return await original_write(uuid, payload, response)
            device.writes.append(bytes(payload))
            device.mask = int.from_bytes(payload[9:11], "big")
            client.callback(None, ACK)
            await asyncio.sleep(0)

        client.write_gatt_char = write
        return client

    transport = BaseusTransport(
        connect, timeout=0.04, connect_timeout=0.04, drain_time=0
    )
    assert await transport.set_port("c2", False) == 12
    assert device.queries == 2


async def test_cancel_while_waiting_control_ack_releases_connection():
    device = FakeDevice(4)
    sent = asyncio.Event()
    original_connect = device.connect

    async def connect(callback):
        client = await original_connect(callback)
        original_write = client.write_gatt_char

        async def write(uuid, payload, response):
            if payload == QUERY:
                return await original_write(uuid, payload, response)
            device.writes.append(bytes(payload))
            sent.set()

        client.write_gatt_char = write
        return client

    transport = BaseusTransport(
        connect, timeout=0.1, connect_timeout=0.04, drain_time=0
    )
    operation = asyncio.create_task(transport.set_port("c2", False))
    await sent.wait()
    await transport.close()
    with pytest.raises(asyncio.CancelledError):
        await operation
    assert len(device.writes) == 1
    assert all(client.closed for client in device.clients)
