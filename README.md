[![Validate](https://github.com/Abhijay/alexa-room-sync/actions/workflows/validate.yml/badge.svg)](https://github.com/Abhijay/alexa-room-sync/actions/workflows/validate.yml)

# Alexa Room Sync

[![Open your Home Assistant instance and open this repository inside HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Abhijay&repository=alexa-room-sync&category=integration)


A Home Assistant custom integration that makes your Alexa rooms a generated copy
of your Home Assistant areas. You organise devices into areas once, in Home
Assistant. Alexa follows.

## What it does

- Reads your areas, devices and entities from Home Assistant's registries.
- Reads Alexa's smart-home device inventory and existing rooms.
- Matches Alexa devices to Home Assistant devices or entities by name or
  alias, once. After that they are tracked by ID, so renaming either side is
  safe. Area aliases let an existing Alexa room be adopted under a different
  name; the room then takes the area's name.
- Skips anything hidden or disabled, and anything labelled `no_alexa`. Put
  that label on raw bulbs whose fixture group is what you actually talk to,
  so Alexa rooms hold the fixtures and not the parts.
- Creates a room per area, renames rooms when areas are renamed, and moves
  devices between rooms when you move them between areas.
- Creates a group per floor holding every matched device from that floor's
  areas, so "turn off Common Spaces" works if that is what you called the floor.
  Alexa lets a device sit in many groups, so rooms and floors coexist.
- Creates one group for the whole home, named after your Home Assistant
  instance (Settings → System → General → Name), holding every matched device.
  Alexa has no notion of a house, so this stands in for one.
- Runs a few seconds after any registry change, and hourly as a fallback.

It never deletes an Alexa room, and it never removes devices it did not place
in a room itself. A device it did place is taken back out once it stops
matching, so labelling a bulb `no_alexa` clears it from its room on the next
run. Anything ambiguous, such as two devices with the same name in different
areas, stops the whole run with nothing written.

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

Click the HACS badge above, or in HACS add this repository as a custom
repository of type Integration. Then install **Alexa Room Sync**, restart Home
Assistant, and add it:

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=alexa_room_sync)

## Use

An **Alexa Rooms** panel appears in the sidebar. It lists the home, every floor and area
with the Alexa group it maps to, each matched Home Assistant and Alexa device side by
side, and the Alexa devices that matched nothing. Sync now and the dry-run
toggle live there too.

The same information is available as entities on one service device, for
automations and dashboards:

| Entity | Purpose |
| --- | --- |
| `switch.alexa_room_sync_dry_run` | On by default. Plans are computed and shown but nothing is written to Alexa. Turn it off to apply. |
| `button.alexa_room_sync_sync_now` | Run a pass immediately. |
| `sensor.alexa_room_sync_status` | `in_sync`, `dry_run`, `applied` or `error`. Attributes hold the full plan. |
| `sensor.alexa_room_sync_pending_changes` | Number of Alexa writes the last plan wants, each spelled out in the `changes` attribute. |
| `sensor.alexa_room_sync_unmatched_alexa_devices` | Alexa devices with no same-named object in Home Assistant, Echos listed separately. |
| `sensor.alexa_room_sync_last_run` | Timestamp of the last pass, with the error text if it failed. |

Start in dry run. Open the panel, fix any names that did not match (rename in
Alexa, or add an alias in Home Assistant), then turn dry run off.

## How it talks to Alexa

Alexa has no public API for room management. This integration uses the same
private endpoints the Alexa app uses, through the session that the core Alexa
Devices integration already maintains. Amazon may change them without notice.
When that happens the status sensor reports `error` and nothing is written.
