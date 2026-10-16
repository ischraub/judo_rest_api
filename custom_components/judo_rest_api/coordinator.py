"""The Update Coordinator for the RestItems."""

from __future__ import annotations

import logging
from datetime import timedelta
from time import monotonic
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.translation import async_get_translations
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .configentry import MyConfigEntry
from .const import CONF, CONST, FORMATS, TYPES
from .items import RestItem
from .restobject import ItemValue, JudoApiError, JudoDecodeError, RestAPI, RestObject

_LOGGER = logging.getLogger(__name__)


def scan_interval_of(config_entry: MyConfigEntry) -> int:
    """Return the configured poll interval in seconds.

    The value is stored as a string and was fed to int() unchecked, so an
    entry like "60s" made the whole setup fail with a ValueError.
    """
    raw = config_entry.data.get(CONF.SCAN_INTERVAL, CONST.SCAN_INTERVAL)
    try:
        seconds = int(float(raw))
    except (TypeError, ValueError):
        _LOGGER.warning(
            "Invalid scan interval %r, falling back to %s s", raw, CONST.SCAN_INTERVAL
        )
        seconds = int(CONST.SCAN_INTERVAL)
    return max(seconds, CONST.MIN_SCAN_INTERVAL)


class MyCoordinator(DataUpdateCoordinator[dict[str, ItemValue]]):
    """My custom coordinator.

    Holds the values of all items. They used to live on the RestItem objects
    themselves, which are module level singletons in jdconst.py, so every
    config entry wrote into the same fields and two devices overwrote each
    other's readings.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        my_api: RestAPI,
        api_items: list[RestItem],
        p_config_entry: MyConfigEntry,
    ) -> None:
        """Initialize my coordinator."""
        self._scan_interval = scan_interval_of(p_config_entry)
        super().__init__(
            hass,
            _LOGGER,
            name="judo_rest_api-coordinator",
            update_interval=timedelta(seconds=self._scan_interval),
            # The data is a dict of frozen dataclasses and compares with
            # __eq__, so listeners are only woken when something changed.
            always_update=False,
        )
        self._rest_api = my_api
        self._restitems = api_items
        self._readable = [item for item in api_items if self._is_readable(item)]
        self._config_entry = p_config_entry
        self._cached_device_info: dict[str, Any] = {}
        # Leave a little room so a slow scan does not run into the next one.
        self._budget = max(CONST.REQUEST_TIMEOUT, self._scan_interval - CONST.SCAN_MARGIN)

    @staticmethod
    def _is_readable(rest_item: RestItem) -> bool:
        """Return whether this item can be polled."""
        return (
            rest_item.address_read is not None
            and rest_item.format is not FORMATS.BUTTON
            and rest_item.type not in (TYPES.SELECT_NOIF, TYPES.BUTTON)
        )

    def value_of(self, key: str) -> Any:
        """Return the last decoded value for an item, or None."""
        if not self.data:
            return None
        item_value = self.data.get(key)
        return item_value.value if item_value else None

    def has_value(self, key: str) -> bool:
        """Return whether the last scan produced a value for an item."""
        return bool(self.data) and key in self.data

    def raw_values(self) -> dict[str, str]:
        """Return the raw payloads of the last scan, for diagnostics."""
        return {key: item.raw for key, item in (self.data or {}).items()}

    def async_set_value(self, key: str, value: Any) -> None:
        """Store a value written by the user and tell the entities about it."""
        data = dict(self.data or {})
        previous = data.get(key)
        data[key] = ItemValue(value, previous.raw if previous else "")
        self.async_set_updated_data(data)

    async def _async_setup(self) -> None:
        """Verify the device answers before any entity is created."""
        try:
            await self._rest_api.async_connect()
        except JudoApiError as err:
            # async_config_entry_first_refresh turns this into
            # ConfigEntryNotReady, so HA retries instead of loading a broken
            # integration.
            raise UpdateFailed(f"Cannot reach Judo device: {err}") from err

    async def _async_update_data(self) -> dict[str, ItemValue]:
        """Fetch all values from the REST API.

        Items are read one by one because the device only serves one request
        at a time. An item that fails is left out of the result so its entity
        goes unavailable; it must not keep the previous reading, which would
        be indistinguishable from a fresh one.
        """
        data: dict[str, ItemValue] = {}
        failures: list[str] = []
        deadline = monotonic() + self._budget

        for item in self._readable:
            if monotonic() > deadline:
                _LOGGER.warning(
                    "Scan budget of %s s exhausted after %s of %s items; "
                    "consider a longer scan interval",
                    self._budget,
                    len(data) + len(failures),
                    len(self._readable),
                )
                break
            try:
                data[item.key] = await RestObject(self._rest_api, item).async_read()
            except (JudoApiError, JudoDecodeError) as err:
                failures.append(f"{item.translation_key}: {err}")

        if not data:
            raise UpdateFailed(
                "No value could be read from the Judo device: "
                + ("; ".join(failures) if failures else "no items polled")
            )
        if failures:
            _LOGGER.warning(
                "%s of %s items could not be read: %s",
                len(failures),
                len(self._readable),
                "; ".join(failures),
            )
        return data

    async def async_update_device_info(self) -> None:
        """Build the device registry info once, after the first scan.

        This used to run on every update cycle, fetching the whole translation
        catalogue each time, although device info is only read when an entity
        is added.
        """
        model = None
        device_type = self._value_by_translation_key("device_type")
        if device_type:
            translations = await async_get_translations(
                self.hass, self.hass.config.language, "entity", {CONST.DOMAIN}
            )
            key = (
                f"component.{CONST.DOMAIN}.entity.sensor.device_type.state.{device_type}"
            )
            model = translations.get(key, device_type)

        self._cached_device_info = {
            "sw_version": self._value_by_translation_key("software_version"),
            "model": model,
            "serial_number": self._value_by_translation_key("device_number"),
        }

    def _value_by_translation_key(self, translation_key: str) -> Any:
        """Look an item up by its translation key and return its value."""
        for item in self._restitems:
            if item.translation_key == translation_key:
                return self.value_of(item.key)
        return None

    def get_device_info_values(self) -> dict:
        """Get cached device info values."""
        return self._cached_device_info

    @property
    def rest_api(self) -> RestAPI:
        """Return rest_api."""
        return self._rest_api
