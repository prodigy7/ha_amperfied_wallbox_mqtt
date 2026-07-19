"""Button entity for manually authorizing charging (without RFID)."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import AmperfiedWallboxCoordinator

AUTHENTICATE_BUTTON = ButtonEntityDescription(
    key="authenticate_charging",
    translation_key="authenticate_charging",
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Sets up the button entity for this config entry."""
    coordinator: AmperfiedWallboxCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([AmperfiedWallboxAuthenticateButton(coordinator, entry)])


class AmperfiedWallboxAuthenticateButton(
    CoordinatorEntity[AmperfiedWallboxCoordinator], ButtonEntity
):
    """Manually authorizes charging (api/cmd/energymanager/authenticate)."""

    entity_description = AUTHENTICATE_BUTTON
    _attr_has_entity_name = True

    def __init__(self, coordinator: AmperfiedWallboxCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_authenticate_charging"
        self._attr_device_info = coordinator.device_info

    async def async_press(self) -> None:
        """Called when the button is pressed in HA."""
        await self.coordinator.client.async_authenticate_charging()
