"""Constants for Alexa Room Sync."""

import logging

DOMAIN = "alexa_room_sync"
LOGGER = logging.getLogger(__package__)

ALEXA_DEVICES_DOMAIN = "alexa_devices"

# Devices and entities carrying this label never join an Alexa room.
IGNORE_LABEL = "no_alexa"

STORAGE_KEY = DOMAIN
STORAGE_VERSION = 1

DEBOUNCE_SECONDS = 5
FALLBACK_INTERVAL_MINUTES = 60
