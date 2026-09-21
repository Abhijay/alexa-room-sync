"""Sidebar panel showing every area beside its Alexa room."""

from __future__ import annotations

from pathlib import Path

import voluptuous as vol

from homeassistant.components import frontend, panel_custom, websocket_api
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant, callback

from .const import DOMAIN
from .coordinator import AlexaRoomSyncConfigEntry

PANEL_URL = "alexa-room-sync"
STATIC_URL = f"/{DOMAIN}_static"
FRONTEND_DIR = Path(__file__).parent / "frontend"


async def async_register_panel(hass: HomeAssistant, entry: AlexaRoomSyncConfigEntry) -> None:
    """Serve the panel script and register the sidebar entry."""
    await hass.http.async_register_static_paths([StaticPathConfig(STATIC_URL, str(FRONTEND_DIR), cache_headers=False)])
    websocket_api.async_register_command(hass, ws_overview)
    await panel_custom.async_register_panel(
        hass,
        frontend_url_path=PANEL_URL,
        webcomponent_name="alexa-room-sync-panel",
        sidebar_title="Alexa Rooms",
        sidebar_icon="mdi:home-group",
        module_url=f"{STATIC_URL}/panel.js",
        require_admin=True,
        config={"entry_id": entry.entry_id},
    )


@callback
def async_remove_panel(hass: HomeAssistant) -> None:
    """Take the sidebar entry down."""
    frontend.async_remove_panel(hass, PANEL_URL)


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/overview"})
@callback
def ws_overview(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    """Return the last run as the panel wants it."""
    entries = hass.config_entries.async_entries(DOMAIN)
    sync = getattr(entries[0], "runtime_data", None) if entries else None
    if sync is None:
        connection.send_error(msg["id"], "not_loaded", "Alexa Room Sync is not loaded")
        return
    connection.send_result(msg["id"], sync.overview())
