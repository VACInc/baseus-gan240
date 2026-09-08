"""Bounded, fail-closed transactions over HA-provided Bleak connections.

Each query uses a new connection/notification closure. Verification cannot
consume notifications queued by the control connection. The protocol has no
transaction ID: see README for the remaining on-wire freshness limitation.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

from .const import NOTIFY_UUID, SERVICE_UUID, WRITE_UUID
from .protocol import (
    ACK,
    QUERY,
    mutate_mask,
    parse_register,
    parse_status,
    query_frame,
    write_frame,
)

_LOGGER = logging.getLogger(__name__)


class BaseusError(Exception):
    """A transaction could not be safely completed."""


async def _await_owned(task: asyncio.Task) -> None:
    """Drain independently owned cleanup despite repeated caller cancellation.

    The owned operation supplies its own timeout. Shield alone is insufficient:
    it would let the caller release the transaction lock before cleanup finishes.
    """
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
    task.result()  # Cleanup failure must still prevent subsequent connections.
    if cancelled:
        raise asyncio.CancelledError


class BaseusTransport:
    """One lock owns the full fresh-read, optional-write, fresh-verify sequence."""

    def __init__(
        self,
        connector: Callable[..., Awaitable[Any]],
        *,
        timeout: float = 10,
        connect_timeout: float = 30,
        drain_time: float = 0.2,
    ) -> None:
        self._connector = connector
        self._timeout = timeout
        self._connect_timeout = connect_timeout
        self._drain_time = drain_time
        self._lock = asyncio.Lock()
        self._closed = False
        self._active: asyncio.Task | None = None
        self._close_task: asyncio.Task | None = None

    @asynccontextmanager
    async def _stage(self, stage: str):
        """Log only constant stage names and allowlisted error categories."""
        try:
            yield
        except asyncio.CancelledError:
            raise
        except Exception as err:
            category = (
                "timeout"
                if isinstance(err, TimeoutError)
                else "validation"
                if isinstance(err, BaseusError)
                else "backend"
            )
            _LOGGER.warning(
                "Bluetooth transaction failed: stage=%s category=%s", stage, category
            )
            raise

    @asynccontextmanager
    async def _connection(self):
        client = None
        disconnected = asyncio.Event()

        def on_disconnected(candidate):
            # Retry connector may invoke this for failed attempts, even after
            # returning a different healthy client. Only the returned client owns
            # this transaction's event. Pre-return loss is checked below.
            if client is not None and candidate is client:
                disconnected.set()

        try:
            async with self._stage("connect"), asyncio.timeout(self._connect_timeout):
                client = await self._connector(on_disconnected)
            async with self._stage("validate_gatt"):
                if not client.is_connected:
                    raise BaseusError("Charger disconnected during establishment")
                service = client.services.get_service(SERVICE_UUID)
                if service is None:
                    raise BaseusError("Required charger service missing")
                write = service.get_characteristic(WRITE_UUID)
                notify = service.get_characteristic(NOTIFY_UUID)
                if (
                    write is None
                    or notify is None
                    or "write-without-response" not in write.properties
                    or "notify" not in notify.properties
                ):
                    raise BaseusError("Required charger characteristics missing")
            yield client, disconnected
        finally:
            if client is not None:
                # Disconnect also removes subscriptions and releases proxy slots.
                # Failure is not suppressed: do not proceed to another connection.
                await _await_owned(asyncio.create_task(self._disconnect(client)))

    async def _disconnect(self, client) -> None:
        async with self._stage("disconnect"), asyncio.timeout(self._timeout):
            await client.disconnect()

    async def _query(self) -> int:
        async with self._connection() as (client, disconnected):
            loop = asyncio.get_running_loop()
            result = loop.create_future()
            accepting = False

            def notification(_characteristic, data):
                # Gate BEFORE parsing or scheduling: pre-query callbacks cannot
                # be replayed into a later query's waiter. ACK is never state.
                if accepting and not result.done():
                    mask = parse_status(bytes(data))
                    if mask is not None:
                        result.set_result(mask)

            lost = None
            stage = "subscribe"
            try:
                async with asyncio.timeout(self._timeout):
                    await client.start_notify(NOTIFY_UUID, notification)
                    stage = "drain"
                    await asyncio.sleep(self._drain_time)
                    stage = "query_write"
                    await client.write_gatt_char(WRITE_UUID, QUERY, response=False)
                    # Conservative barrier: reject even responses delivered while
                    # the write is pending. A fast legitimate response may time out
                    # rather than accepting an unproven pre-query notification.
                    accepting = True
                    stage = "status_wait"
                    lost = asyncio.create_task(disconnected.wait())
                    done, _ = await asyncio.wait(
                        (result, lost), return_when=asyncio.FIRST_COMPLETED
                    )
                    if disconnected.is_set() or not client.is_connected:
                        raise BaseusError("Charger disconnected during query")
                    if result in done:
                        return result.result()
                    raise BaseusError("No fresh status")
            except Exception:
                async with self._stage(stage):
                    raise
            finally:
                accepting = False
                result.cancel()
                if lost is not None:
                    lost.cancel()
                    await asyncio.gather(lost, return_exceptions=True)

    async def _query_registers(
        self, codes: tuple[str, ...]
    ) -> dict[str, tuple[int, int]]:
        """Read several registers over one owned subscription and connection."""
        async with self._connection() as (client, disconnected):
            accepting = False
            expected: str | None = None
            result: asyncio.Future | None = None

            def notification(_characteristic, data):
                parsed = parse_register(bytes(data))
                if (
                    accepting
                    and parsed is not None
                    and parsed[0] == expected
                    and result is not None
                    and not result.done()
                ):
                    result.set_result(parsed[1:])

            stage = "subscribe"
            try:
                async with asyncio.timeout(self._timeout):
                    await client.start_notify(NOTIFY_UUID, notification)
                    stage = "drain"
                    await asyncio.sleep(self._drain_time)

                values: dict[str, tuple[int, int]] = {}
                for code in codes:
                    result = asyncio.get_running_loop().create_future()
                    expected = code
                    accepting = False
                    lost = None
                    try:
                        stage = "register_write"
                        async with asyncio.timeout(self._timeout):
                            await client.write_gatt_char(
                                WRITE_UUID, query_frame(code), response=False
                            )
                            accepting = True
                            stage = "register_wait"
                            lost = asyncio.create_task(disconnected.wait())
                            done, _ = await asyncio.wait(
                                (result, lost), return_when=asyncio.FIRST_COMPLETED
                            )
                            if disconnected.is_set() or not client.is_connected:
                                raise BaseusError("Charger disconnected during query")
                            if result not in done:
                                raise BaseusError("No fresh register response")
                            values[code] = result.result()
                    finally:
                        if lost is not None:
                            lost.cancel()
                            await asyncio.gather(lost, return_exceptions=True)
                    accepting = False
                    result = None
                    expected = None
                return values
            except Exception:
                async with self._stage(stage):
                    raise
            finally:
                accepting = False
                if result is not None:
                    result.cancel()

    async def _write(self, target: int) -> None:
        """Keep the control connection alive until the exact device ACK arrives.

        A proxy's write-without-response only queues an API message. It does not
        prove delivery. ACK proves receipt, not state; _run still reads state
        over a separate connection and never retries an uncertain write.
        """
        async with self._connection() as (client, disconnected):
            ack = asyncio.Event()
            accepting = False
            lost = None
            received = None

            def notification(_characteristic, data):
                if accepting and bytes(data) == ACK:
                    ack.set()

            try:
                async with self._stage("control_write"), asyncio.timeout(self._timeout):
                    await client.start_notify(NOTIFY_UUID, notification)
                    await asyncio.sleep(self._drain_time)
                    # Reject subscription-time frames. Arm before dispatch so a
                    # legitimate ACK arriving during write completion is retained.
                    accepting = True
                    await client.write_gatt_char(
                        WRITE_UUID, write_frame(target), response=False
                    )
                    lost = asyncio.create_task(disconnected.wait())
                    received = asyncio.create_task(ack.wait())
                    await asyncio.wait(
                        (received, lost), return_when=asyncio.FIRST_COMPLETED
                    )
                    if disconnected.is_set() or not client.is_connected:
                        raise BaseusError(
                            "Disconnected during write; outcome uncertain"
                        )
                    if not ack.is_set():
                        raise BaseusError("Missing control acknowledgment")
            finally:
                accepting = False
                tasks = [task for task in (lost, received) if task is not None]
                for task in tasks:
                    task.cancel()
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)

    async def _run(self, port: str | None = None, on: bool = False) -> int:
        async with self._lock:
            if self._closed:
                raise BaseusError("Integration unloaded")
            self._active = asyncio.current_task()
            try:
                current = await self._query()
                if port is None:
                    return current
                target = mutate_mask(current, port, on)
                if current == target:
                    return current
                await self._write(target)
                observed = await self._query()
                if observed != target:
                    raise BaseusError("Readback mismatch; write outcome unverified")
                return observed
            except asyncio.CancelledError:
                raise
            except BaseusError:
                raise
            except Exception as err:
                # Do not expose BLE addresses/backend details in HA diagnostics.
                raise BaseusError(
                    "Bluetooth transaction failed; state unverified"
                ) from err
            finally:
                self._active = None

    async def read(self) -> int:
        return await self._run()

    async def read_registers(
        self, codes: tuple[str, ...]
    ) -> dict[str, tuple[int, int]]:
        async with self._lock:
            if self._closed:
                raise BaseusError("Integration unloaded")
            self._active = asyncio.current_task()
            try:
                return await self._query_registers(codes)
            except asyncio.CancelledError:
                raise
            except BaseusError:
                raise
            except Exception as err:
                raise BaseusError(
                    "Bluetooth transaction failed; telemetry unavailable"
                ) from err
            finally:
                self._active = None

    async def set_port(self, port: str, on: bool) -> int:
        return await self._run(port, on)

    async def close(self) -> None:
        """Stop pending I/O; no state restoration or compensating write."""
        self._closed = True
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._shutdown())
        await _await_owned(self._close_task)

    async def _shutdown(self) -> None:
        active = self._active
        if active is not None:
            active.cancel()
            await asyncio.gather(active, return_exceptions=True)
        async with self._lock:
            pass
