"""init."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er

from .configentry import MyConfigEntry, MyData
from .const import CONF, CONST
from .coordinator import MyCoordinator
from .jdconst import DEVICELISTS
from .restobject import RestAPI

_LOGGER = logging.getLogger(__name__)

RETIRED_UNIQUE_ID_SUFFIXES = (
    "_operating_minutes",
    "_operating_hours",
    "_operating_days",
)

PLATFORMS: list[str] = [
    "binary_sensor",
    "number",
    "select",
    "sensor",
    "button",
]


async def _async_migrate_unique_ids(hass: HomeAssistant, entry: MyConfigEntry) -> None:
    """Add the device postfix to unique ids that were created without it.

    The postfix was computed and then thrown away again, so every config entry
    produced the same unique ids. Entries without a postfix are unaffected.
    """
    postfix = entry.data.get(CONF.DEVICE_POSTFIX, "")
    if not postfix:
        return

    @callback
    def _migrate(registry_entry: er.RegistryEntry) -> dict | None:
        old = registry_entry.unique_id
        for device in {item.device for items in DEVICELISTS for item in items}:
            prefix = f"{CONST.DOMAIN}_{device}_"
            if old.startswith(prefix) and f"_{device}_{postfix}_" not in old:
                new = f"{CONST.DOMAIN}_{device}_{postfix}_{old[len(prefix):]}"
                _LOGGER.info("Migrating unique id %s -> %s", old, new)
                return {"new_unique_id": new}
        return None

    await er.async_migrate_entries(hass, entry.entry_id, _migrate)


async def _async_remove_retired_entities(
    hass: HomeAssistant, entry: MyConfigEntry
) -> None:
    """Drop entities this version no longer creates.

    operating_minutes / operating_hours / operating_days were three sensors for
    three fields of one counter, so "operating hours" only showed the 0..23
    remainder. They are replaced by operating_time. Without removing them they
    would stay in the registry forever as unavailable leftovers.
    """
    registry = er.async_get(hass)
    # Snapshot: the registry is mutated inside the loop.
    for registry_entry in list(
        er.async_entries_for_config_entry(registry, entry.entry_id)
    ):
        if registry_entry.unique_id.endswith(RETIRED_UNIQUE_ID_SUFFIXES):
            _LOGGER.info(
                "Removing %s, replaced by the combined operating_time sensor",
                registry_entry.entity_id,
            )
            registry.async_remove(registry_entry.entity_id)


async def async_setup_entry(hass: HomeAssistant, entry: MyConfigEntry) -> bool:
    """Set up entry."""
    if entry.unique_id is None:
        # Entries created before the config flow set one. Without it the
        # duplicate check in the config flow cannot see them. Safe to do here:
        # no update listener is registered yet, so this does not reload.
        hass.config_entries.async_update_entry(
            entry, unique_id=str(entry.data[CONF.HOST])
        )

    await _async_migrate_unique_ids(hass, entry)
    await _async_remove_retired_entities(hass, entry)

    restapi = RestAPI(config_entry=entry, hass=hass)

    itemlist = [item for device in DEVICELISTS for item in device]

    coordinator = MyCoordinator(
        hass=hass, my_api=restapi, api_items=itemlist, p_config_entry=entry
    )
    # Raises ConfigEntryNotReady when the device does not answer, so HA
    # retries instead of loading an integration that can never produce data.
    await coordinator.async_config_entry_first_refresh()
    await coordinator.async_update_device_info()

    entry.runtime_data = MyData(
        rest_api=restapi,
        hass=hass,
        coordinator=coordinator,
    )

    # see https://community.home-assistant.io/t/config-flow-how-to-update-an-existing-entity/522442/8
    entry.async_on_unload(entry.add_update_listener(update_listener))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _LOGGER.debug("Setup of %s done", entry.title)

    return True


async def update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Update listener."""
    await hass.config_entries.async_reload(
        entry.entry_id
    )  # list of entry_ids created for file


async def async_migrate_entry(hass: HomeAssistant, config_entry: MyConfigEntry):
    """Migrate old entry."""

    new_data = {**config_entry.data}

    if config_entry.version > 1:
        # This means the user has downgraded from a future version
        return True

    # to ensure all update paths we have to check every version to not overwrite existing entries
    if config_entry.version < 1:
        _LOGGER.warning("Old Version detected")

    if config_entry.version < 2:
        _LOGGER.warning("Version <2 detected")
        new_data[CONF.SCAN_INTERVAL] = CONST.SCAN_INTERVAL

    hass.config_entries.async_update_entry(
        config_entry, data=new_data, minor_version=1, version=2
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
