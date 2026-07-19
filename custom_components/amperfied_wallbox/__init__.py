"""Amperfied Wallbox (connect.solar) integration for Home Assistant."""
from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady, ServiceValidationError

from .api import (
    AmperfiedWallboxAuthError,
    AmperfiedWallboxClient,
    AmperfiedWallboxConnectionError,
)
from .const import CONF_DEVICE_PREFIX, CONF_HOST, CONF_PASSWORD, CONF_USERNAME, DOMAIN
from .coordinator import AmperfiedWallboxCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[str] = ["sensor", "binary_sensor", "button"]

SERVICE_GET_CHARGE_LOG = "get_charge_log"

SERVICE_GET_CHARGE_LOG_SCHEMA = vol.Schema(
    {
        vol.Optional("config_entry_id"): str,
        vol.Required("filter_after"): str,
        vol.Required("filter_before"): str,
    }
)


async def _async_handle_get_charge_log(hass: HomeAssistant, call: ServiceCall) -> ServiceResponse:
    """Service handler for amperfied_wallbox.get_charge_log (api/cmd/clog/get)."""
    coordinators: dict[str, AmperfiedWallboxCoordinator] = hass.data.get(DOMAIN, {})
    entry_id = call.data.get("config_entry_id")

    if entry_id is not None:
        coordinator = coordinators.get(entry_id)
        if coordinator is None:
            raise ServiceValidationError(f"Unknown config_entry_id: {entry_id}")
    elif len(coordinators) == 1:
        coordinator = next(iter(coordinators.values()))
    else:
        raise ServiceValidationError(
            "Multiple Amperfied Wallbox config entries loaded -- please specify config_entry_id."
        )

    return await coordinator.client.async_get_charge_log(
        filter_after=call.data["filter_after"],
        filter_before=call.data["filter_before"],
    )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Sets up a config entry."""
    client = AmperfiedWallboxClient(
        host=entry.data[CONF_HOST],
        device_prefix=entry.data[CONF_DEVICE_PREFIX],
        username=entry.data[CONF_USERNAME],
        password=entry.data[CONF_PASSWORD],
    )
    coordinator = AmperfiedWallboxCoordinator(hass, entry, client)
    client.set_callbacks(
        # Extended outage: mark entities unavailable instead of silently
        # keeping stale values forever (cleared automatically by the next
        # successful telemetry update, see async_set_update_error docs).
        on_connection_lost=coordinator.async_set_update_error,
        # Password changed on the wallbox after setup: prompt the user to
        # re-enter it via HA's standard reauth flow instead of retrying
        # forever with credentials that will never work again.
        on_persistent_auth_failure=lambda: entry.async_start_reauth(hass),
    )

    try:
        await coordinator.async_setup()
    except AmperfiedWallboxAuthError as err:
        raise ConfigEntryAuthFailed(str(err)) from err
    except AmperfiedWallboxConnectionError as err:
        # Temporary (wallbox offline, network hiccup, HA starting up before
        # the router) -- HA will retry with backoff on its own.
        raise ConfigEntryNotReady(str(err)) from err

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    if not hass.services.has_service(DOMAIN, SERVICE_GET_CHARGE_LOG):
        hass.services.async_register(
            DOMAIN,
            SERVICE_GET_CHARGE_LOG,
            lambda call: _async_handle_get_charge_log(hass, call),
            schema=SERVICE_GET_CHARGE_LOG_SCHEMA,
            supports_response=SupportsResponse.ONLY,
        )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unloads a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator: AmperfiedWallboxCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.client.async_disconnect()
        if not hass.data[DOMAIN]:
            hass.services.async_remove(DOMAIN, SERVICE_GET_CHARGE_LOG)
    return unload_ok
