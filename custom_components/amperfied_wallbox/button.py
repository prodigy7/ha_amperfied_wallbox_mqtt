"""Button entities for manually authorizing, pausing, and resuming charging."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import AmperfiedWallboxClient
from .const import DOMAIN
from .coordinator import AmperfiedWallboxCoordinator


@dataclass(frozen=True, kw_only=True)
class AmperfiedWallboxButtonDescription(ButtonEntityDescription):
    """Describes an Amperfied Wallbox button entity."""

    press_fn: Callable[[AmperfiedWallboxClient], Awaitable[None]] | None = None


BUTTON_DESCRIPTIONS: tuple[AmperfiedWallboxButtonDescription, ...] = (
    AmperfiedWallboxButtonDescription(
        key="authenticate_charging",
        translation_key="authenticate_charging",
        press_fn=lambda client: client.async_authenticate_charging(),
    ),
    AmperfiedWallboxButtonDescription(
        key="pause_charging",
        translation_key="pause_charging",
        press_fn=lambda client: client.async_pause_charging(),
    ),
    AmperfiedWallboxButtonDescription(
        key="resume_charging",
        translation_key="resume_charging",
        press_fn=lambda client: client.async_resume_charging(),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Sets up the button entities for this config entry."""
    coordinator: AmperfiedWallboxCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        AmperfiedWallboxButton(coordinator, entry, description)
        for description in BUTTON_DESCRIPTIONS
    )


class AmperfiedWallboxButton(CoordinatorEntity[AmperfiedWallboxCoordinator], ButtonEntity):
    """A button entity that triggers a single wallbox command on press."""

    entity_description: AmperfiedWallboxButtonDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: AmperfiedWallboxCoordinator,
        entry: ConfigEntry,
        description: AmperfiedWallboxButtonDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = coordinator.device_info

    async def async_press(self) -> None:
        """Called when the button is pressed in HA."""
        await self.entity_description.press_fn(self.coordinator.client)
