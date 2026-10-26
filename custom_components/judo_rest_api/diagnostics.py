"""Diagnostics support for the Judo REST API integration.

The raw payloads used to sit in the attributes of every entity. They change on
every scan, and in HA an attribute change writes a new state row, so the
recorder database grew by one row per entity per scan even when nothing moved.
They are served here instead, where they are far more useful for debugging:
all commands at once, next to what they were decoded to.
"""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from .configentry import MyConfigEntry
from .const import CONF
from .jdconst import DEVICELISTS

# Only the password is a secret. The user name is not, and a wrong one is
# just as invisible as a wrong password was until it shows up here.
TO_REDACT = {CONF.PASSWORD}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: MyConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data.coordinator
    data = coordinator.data or {}

    items = []
    for device in DEVICELISTS:
        for item in device:
            item_value = data.get(item.key)
            failure = coordinator.last_error(item.key)
            record = {
                "translation_key": item.translation_key,
                "address_read": item.address_read,
                "address_write": item.address_write,
                "read_index": item.read_index,
                "read_bytes": item.read_bytes,
                "read_endian": item.read_endian,
                "format": item.format,
                "raw": item_value.raw if item_value else None,
                "value": str(item_value.value) if item_value else None,
            }
            if failure is not None:
                # The payload of a failed item is the whole point of looking
                # here, so it is reported even though it did not decode.
                raw, message = failure
                record["raw"] = raw
                record["error"] = message
                if raw is not None:
                    record["raw_bytes"] = len(raw) // 2
            record["response_bytes"] = item.response_bytes
            items.append(record)

    return {
        "config": {
            key: value
            for key, value in entry.data.items()
            if key not in TO_REDACT
        },
        "devicetype": coordinator.rest_api.get_devicetype(),
        "last_update_success": coordinator.last_update_success,
        "scan_interval": coordinator.update_interval.total_seconds()
        if coordinator.update_interval
        else None,
        "items": items,
    }
