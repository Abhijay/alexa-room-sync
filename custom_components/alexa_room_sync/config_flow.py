"""Config flow for Alexa Room Sync."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .const import ALEXA_DEVICES_DOMAIN, DOMAIN


class AlexaRoomSyncConfigFlow(ConfigFlow, domain=DOMAIN):
    """Single confirmation step; credentials live in the Alexa Devices integration."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Confirm and create the entry."""
        if not self.hass.config_entries.async_entries(ALEXA_DEVICES_DOMAIN):
            return self.async_abort(reason="no_alexa_devices")
        if user_input is not None:
            return self.async_create_entry(title="Alexa Room Sync", data={})
        return self.async_show_form(step_id="user")
