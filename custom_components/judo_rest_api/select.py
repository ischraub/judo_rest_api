"""Setting up my select entities."""

from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv, entity_platform
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .configentry import MyConfigEntry
from .const import CONST, TYPES
from .entity_helpers import build_entity_list
from .jdconst import DEVICELISTS

_LOGGER: logging.Logger = logging.getLogger(name=__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: MyConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the number platform."""
    _useless = hass
    # start with an empty list of entries
    entries = []

    # we create one communicator per integration only for better performance and to allow dynamic parameters
    coordinator = config_entry.runtime_data.coordinator

    for device in DEVICELISTS:
        entries = await build_entity_list(
            entries=entries,
            config_entry=config_entry,
            rest_items=device,
            item_type=TYPES.SELECT,
            coordinator=coordinator,
        )

    for device in DEVICELISTS:
        entries = await build_entity_list(
            entries=entries,
            config_entry=config_entry,
            rest_items=device,
            item_type=TYPES.SELECT_NOIF,
            coordinator=coordinator,
        )

    for item_type in (TYPES.SELECT_LOCAL, TYPES.SCENE):
        for device in DEVICELISTS:
            entries = await build_entity_list(
                entries=entries,
                config_entry=config_entry,
                rest_items=device,
                item_type=item_type,
                coordinator=coordinator,
            )

    async_add_entities(entries)

    # One action that takes the scene and its duration together. Setting them
    # with two select.select_option calls works, but only in the right order.
    entity_platform.async_get_current_platform().async_register_entity_service(
        CONST.SERVICE_ACTIVATE_SCENE,
        {
            vol.Required("scene"): cv.string,
            vol.Optional("duration"): cv.string,
            vol.Optional("days"): vol.All(vol.Coerce(int), vol.Range(min=1, max=60)),
        },
        "async_activate_scene_service",
    )
