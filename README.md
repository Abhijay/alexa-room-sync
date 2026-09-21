# Alexa Room Sync

A Home Assistant custom integration that makes your Alexa rooms a generated copy
of your Home Assistant areas. You organise devices into areas once, in Home
Assistant. Alexa follows.

## What it does

- Reads your areas, devices and entities from Home Assistant's registries.
- Reads Alexa's smart-home device inventory and existing rooms.
- Matches Alexa devices to Home Assistant devices or entities by name, once.
  After that they are tracked by ID, so renaming either side is safe.
- Creates a room per area, renames rooms when areas are renamed, and moves
  devices between rooms when you move them between areas.
- Runs a few seconds after any registry change, and hourly as a fallback.

It never deletes an Alexa room, and it never removes devices it did not match to
Home Assistant. Anything ambiguous, such as two devices with the same name in
different areas, stops the whole run with nothing written.

Echo devices are included through the core
[Alexa Devices](https://www.home-assistant.io/integrations/alexa_devices)
integration: assign each Echo's Home Assistant device to an area and it joins
that room in Alexa.

## Requirements

- Home Assistant 2025.9 or newer.
- The core **Alexa Devices** integration set up and signed in. This integration
  reuses that Amazon session and stores no credentials of its own.
- Your smart-home devices exposed to Alexa by some route, for example a Matter
  bridge or the Home Assistant cloud skill. Names must match between the two
  systems for the first match.

## Install

1. In HACS, add this repository as a custom repository of type Integration.
2. Install **Alexa Room Sync** and restart Home Assistant.
3. Settings, Devices & services, Add integration, **Alexa Room Sync**.

## Use

The integration adds one service device with three entities:

| Entity | Purpose |
| --- | --- |
| `switch.alexa_room_sync_dry_run` | On by default. Plans are computed and shown but nothing is written to Alexa. Turn it off to apply. |
| `button.alexa_room_sync_sync_now` | Run a pass immediately. |
| `sensor.alexa_room_sync_status` | `in_sync`, `dry_run`, `applied` or `error`. Attributes list the planned actions, warnings, and Alexa devices with no Home Assistant match. |

Start in dry run. Check the sensor's `actions` attribute, fix any names that
did not match, then turn the switch off.

## How it talks to Alexa

Alexa has no public API for room management. This integration uses the same
private endpoints the Alexa app uses, through the session that the core Alexa
Devices integration already maintains. Amazon may change them without notice.
When that happens the status sensor reports `error` and nothing is written.
