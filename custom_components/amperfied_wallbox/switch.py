"""Switch entity for the Boost/ForceCurrent toggle.

See CLAUDE.md point 8 ("Explicit exception: Boost / ForceCurrent toggle") --
this is the one deliberate exception to the read-primary design policy's
exclusion of power/current overrides, because it sends the wallbox's own
hardcoded Boost payload (not a user-chosen value). is_on is derived from
energymanager/emState == "ForceCurrent" (see PROTOCOL.md).
"""
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import AmperfiedWallboxConnectionError
from .const import DOMAIN, EM_STATE_FORCE_CURRENT, TOPIC_EM_STATE
from .coordinator import AmperfiedWallboxCoordinator

BOOST_DESCRIPTION = SwitchEntityDescription(
    key="boost",
    translation_key="boost",
)


def _unwrap(raw: Any) -> Any:
    return raw["value"] if isinstance(raw, dict) and "value" in raw else raw


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Sets up the switch entities for this config entry."""
    coordinator: AmperfiedWallboxCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([AmperfiedWallboxBoostSwitch(coordinator, entry)])


class AmperfiedWallboxBoostSwitch(
    CoordinatorEntity[AmperfiedWallboxCoordinator], SwitchEntity
):
    """Toggles Boost/ForceCurrent (forces the max charging current, bypassing
    PV-surplus/load-management strategy) on or off.
    """

    entity_description = BOOST_DESCRIPTION
    _attr_has_entity_name = True

    def __init__(self, coordinator: AmperfiedWallboxCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_boost"
        self._attr_device_info = coordinator.device_info

    @property
    def is_on(self) -> bool | None:
        if self.coordinator.data is None:
            return None
        raw: Any = self.coordinator.data.get(TOPIC_EM_STATE)
        if raw is None:
            return None
        return _unwrap(raw) == EM_STATE_FORCE_CURRENT

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._async_set_boost(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_set_boost(False)

    async def _async_set_boost(self, enable: bool) -> None:
        try:
            await self.coordinator.client.async_set_boost(enable)
        except TimeoutError as err:
            raise HomeAssistantError(
                "The wallbox did not respond in time. It may not be in a state "
                "where this action applies, or the connection is currently down."
            ) from err
        except AmperfiedWallboxConnectionError as err:
            raise HomeAssistantError(f"Not connected to the wallbox: {err}") from err
