"""Config flow for the Amperfied Wallbox integration."""
from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from .api import (
    AmperfiedWallboxAuthError,
    AmperfiedWallboxClient,
    AmperfiedWallboxConnectionError,
    async_discover_device_prefix,
)
from .const import CONF_DEVICE_PREFIX, CONF_HOST, CONF_PASSWORD, CONF_USERNAME, DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_USERNAME, default="admin"): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


async def _async_validate_input(data: dict[str, Any]) -> str:
    """Tests the connection with the entered data.

    Most users don't know their wallbox's mDNS hostname/topic prefix (e.g.
    "hdm-smart-connect-abc123"), so it's auto-discovered here instead of
    asked for (see api.async_discover_device_prefix). Then briefly
    establishes a connection, attempts the login flow (see PROTOCOL.md), and
    disconnects again. Raises AmperfiedWallboxAuthError or
    AmperfiedWallboxConnectionError on problems. Returns the discovered
    device_prefix.
    """
    device_prefix = await async_discover_device_prefix(data[CONF_HOST])

    client = AmperfiedWallboxClient(
        host=data[CONF_HOST],
        device_prefix=device_prefix,
        username=data[CONF_USERNAME],
        password=data[CONF_PASSWORD],
    )
    try:
        await client.async_connect()
    finally:
        await client.async_disconnect()

    return device_prefix


class AmperfiedWallboxConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for amperfied_wallbox."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                device_prefix = await _async_validate_input(user_input)
            except AmperfiedWallboxAuthError:
                errors["base"] = "invalid_auth"
            except AmperfiedWallboxConnectionError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error during connection test")
                errors["base"] = "unknown"
            else:
                # Prevent setting up the same wallbox twice.
                await self.async_set_unique_id(device_prefix)
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=f"Wallbox {device_prefix}",
                    data={**user_input, CONF_DEVICE_PREFIX: device_prefix},
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> FlowResult:
        """Triggered by ConfigEntry.async_start_reauth() when the stored
        credentials stop working (e.g. the wallbox password was changed).
        See api.py's on_persistent_auth_failure callback.
        """
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Asks for the new password and re-validates against the wallbox.

        Host/username/device_prefix are kept from the existing entry --
        only the password is assumed to have changed.
        """
        errors: dict[str, str] = {}
        reauth_entry = self._get_reauth_entry()

        if user_input is not None:
            data = {**reauth_entry.data, CONF_PASSWORD: user_input[CONF_PASSWORD]}
            try:
                await _async_validate_input(data)
            except AmperfiedWallboxAuthError:
                errors["base"] = "invalid_auth"
            except AmperfiedWallboxConnectionError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error during reauth connection test")
                errors["base"] = "unknown"
            else:
                return self.async_update_reload_and_abort(reauth_entry, data=data)

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
            errors=errors,
            description_placeholders={"host": reauth_entry.data[CONF_HOST]},
        )
