"""The Update Coordinator for the RestItems."""

from __future__ import annotations

import logging
from datetime import timedelta
from time import monotonic
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.translation import async_get_translations
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .configentry import MyConfigEntry
from .const import CONF, CONST, FORMATS, TYPES
from .items import RestItem
from .restobject import (
    ItemValue,
    JudoApiError,
    JudoAuthError,
    JudoDecodeError,
    RestAPI,
    RestObject,
)

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
            config_entry=p_config_entry,
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
        self._translations: dict[str, str] | None = None
        # key -> (raw payload or None, message). Kept for diagnostics: an item
        # that fails to decode is the one whose payload you want to see.
        self._last_errors: dict[str, tuple[str | None, str]] = {}
        # A single 401 can be transient - the module answered one whole nightly
        # scan with 401 and was fine again afterwards. Only a run of scans that
        # fail authentication from start to finish is treated as bad
        # credentials, so a blip does not pop a re-auth dialog.
        self._auth_failures = 0
        # Leave a little room so a slow scan does not run into the next one.
        self._budget = max(CONST.REQUEST_TIMEOUT, self._scan_interval - CONST.SCAN_MARGIN)

    @staticmethod
    def _is_noise(rest_item: RestItem, old_value: Any, new_value: Any) -> bool:
        """Return whether a change is too small to be worth reporting.

        The salt scale wobbles by a gram or two while nothing is being used, so
        without this every single scan produced a state change and a recorder
        row. The deadband is measured against the last *reported* value, not
        the last reading, so slow genuine drift still accumulates until it
        crosses the threshold - nothing is lost, the value is only quantised.
        """
        deadband = (rest_item.params or {}).get("deadband")
        if not deadband:
            return False
        try:
            return abs(float(new_value) - float(old_value)) < float(deadband)
        except (TypeError, ValueError):
            return False

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

    def last_error(self, key: str) -> tuple[str | None, str] | None:
        """Return payload and message of the last failure for an item."""
        return self._last_errors.get(key)

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
        except JudoAuthError as err:
            # Saying "cannot reach device" for a 401 sent us looking for a
            # network problem; the device was answering perfectly well and
            # refusing the credentials.
            raise ConfigEntryAuthFailed(
                f"Judo device refused the credentials: {err}"
            ) from err
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
        errors: dict[str, tuple[str | None, str]] = {}
        auth_failed = False
        deadline = monotonic() + self._budget

        for item in self._readable:
            if monotonic() > deadline:
                _LOGGER.warning(
                    "Scan budget of %s s exhausted after %s of %s items; "
                    "consider a longer scan interval",
                    self._budget,
                    len(data) + len(errors),
                    len(self._readable),
                )
                break
            rest_object = RestObject(self._rest_api, item)
            raw: str | None = None
            try:
                raw = await rest_object.async_read_raw()
                value = rest_object.decode(raw)
                previous = (self.data or {}).get(item.key)
                if previous is not None and self._is_noise(item, previous.value, value):
                    # Carry the previous entry over unchanged, so the new data
                    # compares equal and no listener is woken at all.
                    data[item.key] = previous
                else:
                    data[item.key] = ItemValue(value, raw)
            except JudoAuthError as err:
                errors[item.key] = (raw, str(err))
                auth_failed = True
            except (JudoApiError, JudoDecodeError) as err:
                # Keep the payload: for a decode failure it is the only thing
                # that says why, and it is what diagnostics reports.
                errors[item.key] = (raw, str(err))

        self._last_errors = errors

        if data or not auth_failed:
            self._auth_failures = 0
        else:
            self._auth_failures += 1
            if self._auth_failures >= CONST.AUTH_FAILURES_BEFORE_REAUTH:
                raise ConfigEntryAuthFailed(
                    f"Judo device refused the credentials on "
                    f"{self._auth_failures} scans in a row"
                )

        if not data:
            raise UpdateFailed(
                "No value could be read from the Judo device: "
                + (
                    "; ".join(message for _, message in errors.values())
                    if errors
                    else "no items polled"
                )
            )
        if errors:
            _LOGGER.warning(
                "%s of %s items could not be read: %s",
                len(errors),
                len(self._readable),
                "; ".join(message for _, message in errors.values()),
            )

        await self._async_refresh_device_info()
        return data

    async def _async_refresh_device_info(self) -> None:
        """Fill in device info that the first scan could not provide.

        Device info is read once, when an entity is added. If the device type
        failed to decode back then, the device would be stuck on the fallback
        name for good, so once the values do arrive they are pushed into the
        device registry.
        """
        if self._device_info_complete():
            return
        await self.async_update_device_info()
        if not self._device_info_complete():
            return

        fields = {
            name: value
            for name, value in self._cached_device_info.items()
            if value is not None
        }
        registry = dr.async_get(self.hass)
        for device in dr.async_entries_for_config_entry(
            registry, self._config_entry.entry_id
        ):
            _LOGGER.debug("Updating device registry entry %s: %s", device.id, fields)
            registry.async_update_device(device.id, **fields)

    def _device_info_complete(self) -> bool:
        """Return whether every device info field has a value."""
        info = self._cached_device_info
        return bool(info) and all(info.get(name) for name in ("sw_version", "model", "serial_number"))

    async def async_update_device_info(self) -> None:
        """Build the device registry info from the current values."""
        model = None
        device_type = self._value_by_translation_key("device_type")
        if device_type:
            if self._translations is None:
                self._translations = await async_get_translations(
                    self.hass, self.hass.config.language, "entity", {CONST.DOMAIN}
                )
            translations = self._translations
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
