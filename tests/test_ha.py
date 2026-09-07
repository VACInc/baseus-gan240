from types import MappingProxyType, SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.baseus_gan240 import async_setup_entry, async_unload_entry
from custom_components.baseus_gan240.config_flow import BaseusConfigFlow
from custom_components.baseus_gan240.const import DOMAIN
from custom_components.baseus_gan240.coordinator import (
    BaseusCoordinator,
    make_transport,
)
from custom_components.baseus_gan240.diagnostics import (
    async_get_config_entry_diagnostics,
)
from custom_components.baseus_gan240.switch import BaseusSwitch
from custom_components.baseus_gan240.switch import async_setup_entry as setup_switches
from custom_components.baseus_gan240.transport import BaseusError


@pytest.fixture
def entry():
    return ConfigEntry(
        domain=DOMAIN,
        data={"address": "AA:BB:CC:DD:EE:FF"},
        unique_id="AA:BB:CC:DD:EE:FF",
        version=1,
        minor_version=1,
        title="BS-GaN240",
        source="user",
        options={},
        discovery_keys=MappingProxyType({}),
        subentries_data=[],
    )


@pytest.fixture
async def hass(tmp_path):
    instance = HomeAssistant(str(tmp_path))
    yield instance
    await instance.async_stop()


async def test_switches_and_diagnostics(hass, entry):
    coordinator = BaseusCoordinator(hass, entry)
    entry.runtime_data = coordinator
    coordinator.async_set_updated_data(0xDC27)
    entities = []
    await setup_switches(hass, entry, lambda items: entities.extend(items))
    assert len(entities) == 4
    assert [e.is_on for e in entities] == [False, True, True, False]
    assert len({e.unique_id for e in entities}) == 4
    assert entities[0].device_info["model"].startswith("CCGAN240CS")
    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    assert "AA:BB" not in str(diagnostics)
    assert diagnostics["disable_mask"] == 0xDC27
    coordinator.async_set_update_error(UpdateFailed("failure"))
    assert all(not e.available and e.is_on is None for e in entities)
    assert (await async_get_config_entry_diagnostics(hass, entry))[
        "disable_mask"
    ] is None
    await coordinator.async_shutdown()


async def test_service_nonoptimistic_failure_and_recovery(hass, entry):
    coordinator = BaseusCoordinator(hass, entry)
    coordinator.transport = SimpleNamespace(
        set_port=AsyncMock(side_effect=BaseusError("failed")),
        read=AsyncMock(return_value=4),
        close=AsyncMock(),
    )
    coordinator.async_set_updated_data(0)
    entity = BaseusSwitch(coordinator, entry, "c1")
    with pytest.raises(HomeAssistantError):
        await entity.async_turn_off()
    assert entity.is_on is None and not entity.available
    assert coordinator.data == 0  # no guessed mask was published
    coordinator.transport.set_port = AsyncMock(return_value=4)
    await entity.async_turn_off()
    assert entity.is_on is False and entity.available
    coordinator.transport.set_port = AsyncMock(return_value=0)
    await entity.async_turn_on()
    assert entity.is_on is True
    await coordinator.async_shutdown()


async def test_poll_failure(hass, entry):
    coordinator = BaseusCoordinator(hass, entry)
    coordinator.transport.read = AsyncMock(side_effect=BaseusError("offline"))
    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()
    await coordinator.async_shutdown()


async def test_ha_manager_connectable_lookup(hass):
    transport = make_transport(hass, "AA:BB:CC:DD:EE:FF")
    with patch(
        "custom_components.baseus_gan240.coordinator.bluetooth.async_ble_device_from_address",
        return_value=None,
    ) as lookup:
        with pytest.raises(BaseusError, match="connectable"):
            await transport.read()
        lookup.assert_called_once_with(hass, "AA:BB:CC:DD:EE:FF", connectable=True)


async def test_setup_unload_and_reload(entry):
    hass = SimpleNamespace(
        config_entries=SimpleNamespace(
            async_forward_entry_setups=AsyncMock(),
            async_unload_platforms=AsyncMock(return_value=True),
        )
    )
    coordinators = []

    def factory(*_):
        coordinator = SimpleNamespace(
            async_config_entry_first_refresh=AsyncMock(), async_shutdown=AsyncMock()
        )
        coordinators.append(coordinator)
        return coordinator

    with patch(
        "custom_components.baseus_gan240.BaseusCoordinator", side_effect=factory
    ):
        assert await async_setup_entry(hass, entry)
        assert await async_unload_entry(hass, entry)
        coordinators[0].async_shutdown.assert_awaited_once()
        assert await async_setup_entry(hass, entry)
        assert coordinators[0] is not entry.runtime_data
        assert await async_unload_entry(hass, entry)


async def test_failed_platform_unload_keeps_runtime(entry):
    hass = SimpleNamespace(
        config_entries=SimpleNamespace(
            async_unload_platforms=AsyncMock(return_value=False)
        )
    )
    entry.runtime_data = SimpleNamespace(async_shutdown=AsyncMock())
    assert not await async_unload_entry(hass, entry)
    entry.runtime_data.async_shutdown.assert_not_awaited()


async def test_setup_failure_cleans_up(entry):
    coordinator = SimpleNamespace(
        async_config_entry_first_refresh=AsyncMock(side_effect=BaseusError()),
        async_shutdown=AsyncMock(),
    )
    with patch(
        "custom_components.baseus_gan240.BaseusCoordinator", return_value=coordinator
    ):
        with pytest.raises(BaseusError):
            await async_setup_entry(Mock(), entry)
    coordinator.async_shutdown.assert_awaited_once()


@pytest.fixture
def flow(hass):
    flow = BaseusConfigFlow()
    flow.hass = hass
    flow.context = {}
    flow.async_set_unique_id = AsyncMock()
    flow._abort_if_unique_id_configured = Mock()
    flow._validate = AsyncMock()
    return flow


async def test_manual_flow_validation_and_normalization(flow):
    assert (await flow.async_step_user({"address": "invalid"}))["errors"][
        "address"
    ] == "invalid_address"
    result = await flow.async_step_user({"address": " aa:bb:cc:dd:ee:ff "})
    assert result["type"] == "create_entry"
    assert result["data"]["address"] == "AA:BB:CC:DD:EE:FF"
    flow.async_set_unique_id.assert_awaited_once_with("AA:BB:CC:DD:EE:FF")
    flow._abort_if_unique_id_configured.assert_called_once()


async def test_manual_connection_error(flow):
    flow._validate.side_effect = BaseusError()
    result = await flow.async_step_user({"address": "AA:BB:CC:DD:EE:FF"})
    assert result["errors"] == {"base": "cannot_connect"}


async def test_discovery_confirm_and_filter(flow):
    info = SimpleNamespace(
        name="BS-GaN240", address="aa:bb:cc:dd:ee:ff", connectable=False
    )
    assert (await flow.async_step_bluetooth(info))["reason"] == "not_supported"
    info.connectable = True
    assert (await flow.async_step_bluetooth(info))["step_id"] == "bluetooth_confirm"
    flow._validate.assert_not_awaited()
    assert (await flow.async_step_bluetooth_confirm({}))["type"] == "create_entry"
    info.name = "Other charger"
    assert (await flow.async_step_bluetooth(info))["reason"] == "not_supported"


async def test_discovery_validation_failure(flow):
    flow._validate.side_effect = BaseusError()
    result = await flow.async_step_bluetooth_confirm({})
    assert result["errors"]["base"] == "cannot_connect"


async def test_flow_read_only_validation_closes_transport(hass):
    flow = BaseusConfigFlow()
    flow.hass = hass
    flow._address = "AA:BB:CC:DD:EE:FF"
    transport = SimpleNamespace(
        read=AsyncMock(side_effect=BaseusError()), close=AsyncMock()
    )
    with patch(
        "custom_components.baseus_gan240.config_flow.make_transport",
        return_value=transport,
    ):
        with pytest.raises(BaseusError):
            await flow._validate()
    transport.close.assert_awaited_once()


async def test_connector_uses_retry_connector_and_current_device(hass):
    transport = make_transport(hass, "AA:BB:CC:DD:EE:FF")
    device = object()
    client = object()
    with (
        patch(
            "custom_components.baseus_gan240.coordinator.bluetooth.async_ble_device_from_address",
            return_value=device,
        ),
        patch(
            "custom_components.baseus_gan240.coordinator.establish_connection",
            new=AsyncMock(return_value=client),
        ) as establish,
    ):
        callback = Mock()
        assert await transport._connector(callback) is client
        assert establish.await_args.args[1] is device
        assert establish.await_args.kwargs["max_attempts"] == 3
        assert establish.await_args.kwargs["disconnected_callback"] is callback


async def test_remove_rediscovery(hass, entry):
    from custom_components.baseus_gan240 import async_remove_entry

    with patch(
        "custom_components.baseus_gan240.bluetooth.async_rediscover_address"
    ) as rediscover:
        await async_remove_entry(hass, entry)
    rediscover.assert_called_once_with(hass, entry.data["address"])
