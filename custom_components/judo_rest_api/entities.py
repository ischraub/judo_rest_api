"""Entity classes used in this integration."""

from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.components.number import NumberEntity
from homeassistant.components.select import SelectEntity
from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .configentry import MyConfigEntry
from .const import CONF, CONST, FORMATS, TYPES
from .coordinator import MyCoordinator
from .items import RestItem
from .restobject import JudoApiError, JudoDecodeError, RestObject

_LOGGER = logging.getLogger(__name__)


class MyEntity(CoordinatorEntity[MyCoordinator]):
    """Base class for entities that hold general parameters.

    The value is read from the coordinator on every access instead of being
    cached on the entity, so a failed scan shows up as unavailable rather than
    as a stale reading that looks current.
    """

    _attr_has_entity_name = True

    def __init__(
        self,
        config_entry: MyConfigEntry,
        rest_item: RestItem,
        coordinator: MyCoordinator,
        idx=None,
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator, context=idx)
        self.idx = idx
        self._config_entry = config_entry
        self._rest_item = rest_item
        self._coordinator = coordinator
        self._rest_api = coordinator.rest_api
        self._divider = 1

        dev_postfix = "_" + self._config_entry.data[CONF.DEVICE_POSTFIX]
        if dev_postfix == "_":
            dev_postfix = ""

        # The postfix has to stay in the device name AND in the identifiers:
        # without it a second config entry produces the same unique ids and
        # the same device, so HA drops its entities.
        self._dev_device = self._rest_item.device + dev_postfix
        self._dev_translation_placeholders = {"postfix": dev_postfix}

        self._attr_translation_key = self._rest_item.translation_key
        self._attr_entity_category = self._rest_item.entity_category
        self._attr_unique_id = (
            CONST.DOMAIN + "_" + self._dev_device + "_" + self._rest_item.translation_key
        )

        params = self._rest_item.params or {}
        self._divider = params.get("divider", 1)
        self._attr_device_class = params.get("deviceclass", None)
        if params.get("icon") is not None:
            self._attr_icon = params["icon"]

        match self._rest_item.format:
            case (
                FORMATS.STATUS
                | FORMATS.TEXT
                | FORMATS.DATE
                | FORMATS.SW_VERSION
                | FORMATS.BUTTON
            ):
                # Not numeric: no unit, no state class, no min/max.
                pass
            case _:
                self._attr_state_class = params.get(
                    "stateclass", SensorStateClass.MEASUREMENT
                )
                self._attr_native_unit_of_measurement = params.get("unit", "")
                self._attr_native_step = params.get("step", 1)
                self._attr_suggested_display_precision = params.get("precision", 2)
                self._attr_native_min_value = params.get("min", -999999)
                self._attr_native_max_value = params.get("max", 999999)

    @property
    def _item_value(self):
        """Return the current value of this item from the coordinator."""
        return self._coordinator.value_of(self._rest_item.key)

    @property
    def available(self) -> bool:
        """Return whether the last scan produced a value for this item."""
        if not self.coordinator.last_update_success:
            return False
        if self._rest_item.address_read is None:
            # Write-only items (buttons) follow the device, not a reading.
            return True
        return self._coordinator.has_value(self._rest_item.key)

    def my_device_info(self) -> DeviceInfo:
        """Build the device info with dynamic values."""
        sw_version = "unknown"
        model = "Judo Device"
        serial_number = "unknown"

        device_info_values = self._coordinator.get_device_info_values()
        if device_info_values.get("sw_version"):
            sw_version = str(device_info_values["sw_version"])
        if device_info_values.get("model"):
            model = str(device_info_values["model"])
        if device_info_values.get("serial_number"):
            serial_number = str(int(device_info_values["serial_number"]))

        return {
            "identifiers": {(CONST.DOMAIN, self._dev_device)},
            "translation_key": self._rest_item.device,
            "translation_placeholders": self._dev_translation_placeholders,
            "sw_version": sw_version,
            "serial_number": serial_number,
            "model": model,
            "manufacturer": "Judo",
            "suggested_area": "Utility room",
        }

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return self.my_device_info()


class MySensorEntity(MyEntity, SensorEntity):
    """Class that represents a sensor entity.

    Derived from Sensorentity
    and decorated with general parameters from MyEntity
    """

    @property
    def native_value(self):
        """Return the sensor value."""
        return self._item_value


class MyNumberEntity(MyEntity, NumberEntity):  # pylint: disable=W0223
    """Represent a Number Entity.

    Class that represents a number entity derived from NumberEntity
    and decorated with general parameters from MyEntity
    """

    @property
    def native_value(self):
        """Return the number value."""
        return self._item_value

    async def async_set_native_value(self, value: float) -> None:
        """Write the value to the device and refresh HA."""
        ro = RestObject(self._rest_api, self._rest_item)
        try:
            written = await ro.async_write(value)
        except (JudoApiError, JudoDecodeError) as err:
            raise HomeAssistantError(
                f"Could not write {self._rest_item.translation_key}: {err}"
            ) from err
        self._coordinator.async_set_value(self._rest_item.key, written)


class MyButtonEntity(MyEntity, ButtonEntity):  # pylint: disable=W0223
    """Represent a Button Entity.

    Class that represents a button entity derived from ButtonEntity
    and decorated with general parameters from MyEntity
    """

    async def async_press(self):
        """Send the command to the device."""
        ro = RestObject(self._rest_api, self._rest_item)
        try:
            await ro.async_press()
        except JudoApiError as err:
            raise HomeAssistantError(
                f"Could not trigger {self._rest_item.translation_key}: {err}"
            ) from err
        await self._coordinator.async_request_refresh()


class MySelectEntity(MyEntity, SelectEntity):  # pylint: disable=W0223
    """Class that represents a select entity.

    Class that represents a select entity derived from SelectEntity
    and decorated with general parameters from MyEntity
    """

    def __init__(
        self,
        config_entry: MyConfigEntry,
        rest_item: RestItem,
        coordinator: MyCoordinator,
        idx,
    ) -> None:
        """Initialze MySelectEntity."""
        super().__init__(config_entry, rest_item, coordinator, idx)
        self.options = [item.translation_key for item in rest_item.resultlist or []]
        self._attr_current_option = self.options[0] if self.options else None

    @property
    def current_option(self):
        """Return the selected option."""
        if self._rest_item.type == TYPES.SELECT_NOIF:
            # Write-only selects always fall back to their first option.
            return self.options[0] if self.options else None
        return self._item_value

    async def async_select_option(self, option: str) -> None:
        """Write the selected option to the device and refresh HA."""
        ro = RestObject(self._rest_api, self._rest_item)
        try:
            await ro.async_add(option)
        except (JudoApiError, JudoDecodeError) as err:
            raise HomeAssistantError(
                f"Could not set {self._rest_item.translation_key}: {err}"
            ) from err
        await self._coordinator.async_request_refresh()
