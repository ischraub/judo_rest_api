"""Entity classes used in this integration."""

from __future__ import annotations

import logging

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.components.button import ButtonEntity
from homeassistant.components.number import NumberEntity
from homeassistant.components.select import SelectEntity
from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .configentry import MyConfigEntry
from .const import CONF, CONST, FORMATS, TYPES
from .coordinator import MyCoordinator
from .items import RestItem
from .restobject import (
    JudoApiError,
    JudoDecodeError,
    RestObject,
    holiday_is_active,
)

_LOGGER = logging.getLogger(__name__)

# The scene the device runs in holiday mode. Command 36 neither starts nor
# ends it; command 41 does.
HOLIDAY_SCENE = "scene_holiday"



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
                | FORMATS.SERIAL
                | FORMATS.HOLIDAY
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
            serial_number = str(device_info_values["serial_number"])

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


class MyLocalSelectEntity(MyEntity, SelectEntity, RestoreEntity):  # pylint: disable=W0223
    """A select whose value never leaves Home Assistant.

    The scene duration is not stored on the device: command 36 takes it along
    with the scene and nothing reads it back. So it lives here, and is
    restored after a restart.
    """

    def __init__(
        self,
        config_entry: MyConfigEntry,
        rest_item: RestItem,
        coordinator: MyCoordinator,
        idx,
    ) -> None:
        """Initialize MyLocalSelectEntity."""
        super().__init__(config_entry, rest_item, coordinator, idx)
        self._attr_options = [item.translation_key for item in rest_item.resultlist or []]
        self._default = (rest_item.params or {}).get("default")

    @property
    def available(self) -> bool:
        """Always available: this value does not come from the device."""
        return True

    @property
    def current_option(self):
        """Return the selected option."""
        value = self._item_value
        if value in self._attr_options:
            return value
        return self._default if self._default in self._attr_options else None

    async def async_added_to_hass(self) -> None:
        """Restore the option that was selected before the restart."""
        await super().async_added_to_hass()
        if self._item_value is not None:
            return
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state in self._attr_options:
            self._coordinator.async_set_value(self._rest_item.key, last_state.state)

    async def async_select_option(self, option: str) -> None:
        """Remember the option."""
        self._coordinator.async_set_value(self._rest_item.key, option)


class MySceneEntity(MyEntity, SelectEntity):  # pylint: disable=W0223
    """Pick the water scene the device runs.

    "Urlaub geniessen" is a scene like the others here, even though the device
    starts it with its own command and counts its duration in days rather than
    hours. Switching to it starts the holiday mode, switching away ends it, so
    the scene is the single place where this is steered.
    """

    def __init__(
        self,
        config_entry: MyConfigEntry,
        rest_item: RestItem,
        coordinator: MyCoordinator,
        idx,
    ) -> None:
        """Initialize MySceneEntity."""
        super().__init__(config_entry, rest_item, coordinator, idx)
        self._attr_options = [item.translation_key for item in rest_item.resultlist or []]

    @property
    def available(self) -> bool:
        """Stay operable even when the active scene cannot be read.

        Activating a scene does not depend on reading one. Command 69 needs
        device software newer than 1.5.31, and tying availability to it took
        the control away from everyone on older firmware.
        """
        return self.coordinator.last_update_success

    @property
    def current_option(self):
        """Return the scene the device reports as active, if it can say.

        Read from command 69, which needs device software newer than 1.5.31.
        On older firmware this stays unknown: the API has no other way to ask
        which scene is running, and echoing the scene last activated from here
        would claim more than it knows.
        """
        value = self._item_value
        return value if value in self._attr_options else None

    def _duration(self) -> int:
        """Return the duration to send, from the sibling duration item."""
        name = (self._rest_item.params or {}).get("duration_item")
        item = self._coordinator.item_by_translation_key(name) if name else None
        if item is None:
            raise HomeAssistantError(f"No duration item {name!r} configured")
        option = self._coordinator.value_of(item.key) or (item.params or {}).get(
            "default"
        )
        number = item.get_number_from_translation_key(option)
        if number is None or number < 0:
            raise HomeAssistantError(f"Unknown scene duration {option!r}")
        return number

    def _holiday_days(self) -> int:
        """Return the holiday duration in days, from the sibling item."""
        name = (self._rest_item.params or {}).get("days_item")
        item = self._coordinator.item_by_translation_key(name) if name else None
        if item is None:
            raise HomeAssistantError(f"No holiday duration item {name!r} configured")
        value = self._coordinator.value_of(item.key)
        if value is None:
            value = (item.params or {}).get("default", 1)
        days = int(float(value))
        if not 1 <= days <= 60:
            raise HomeAssistantError(
                f"Holiday duration {days} is not between 1 and 60 days"
            )
        return days

    async def async_select_option(self, option: str) -> None:
        """Run the chosen scene, starting or ending the holiday mode with it.

        The holiday mode is the "Urlaub geniessen" scene: the device runs it
        exactly while that scene is active. It has its own command because its
        duration is in days, but from here it is one more scene to pick.
        """
        ro = RestObject(self._rest_api, self._rest_item)
        # The scene item reads command 69 itself, so its raw answer already
        # says which scene is running.
        was_holiday = holiday_is_active(
            self._coordinator.raw_of(self._rest_item.key)
        )

        if option == HOLIDAY_SCENE:
            days = self._holiday_days()
            try:
                await ro.async_start_holiday(days)
            except (JudoApiError, JudoDecodeError) as err:
                raise HomeAssistantError(
                    f"Could not start holiday mode: {err}"
                ) from err
            _LOGGER.info("Started holiday mode for %s day(s)", days)
            await self._coordinator.async_request_refresh()
            return

        scene = self._rest_item.get_number_from_translation_key(option)
        if scene is None or scene < 0:
            raise HomeAssistantError(f"Unknown water scene {option!r}")
        duration = self._duration()

        if was_holiday:
            try:
                await ro.async_end_holiday()
            except (JudoApiError, JudoDecodeError) as err:
                raise HomeAssistantError(
                    f"Could not leave holiday mode: {err}"
                ) from err

        try:
            await ro.async_activate_scene(scene, duration)
            _LOGGER.info("Activated water scene %s for 0x%04X", option, duration)
        except (JudoApiError, JudoDecodeError) as err:
            if not was_holiday:
                raise HomeAssistantError(
                    f"Could not activate {option}: {err}"
                ) from err
            # Leaving holiday mode already returns the device to its base
            # scene, so the request did what it was for even if the device
            # refused this particular scene afterwards.
            _LOGGER.warning(
                "Left holiday mode, but the device refused scene %s: %s", option, err
            )
        await self._coordinator.async_request_refresh()


class MyBinarySensorEntity(MyEntity, BinarySensorEntity):
    """A yes/no reading from the device."""

    @property
    def is_on(self):
        """Return the reading."""
        return self._item_value


class MyLocalNumberEntity(MyEntity, NumberEntity, RestoreEntity):  # pylint: disable=W0223
    """A number whose value never leaves Home Assistant.

    The holiday duration is not a device setting until the mode is started, so
    it is held here and restored after a restart.
    """

    @property
    def available(self) -> bool:
        """Always available: this value does not come from the device."""
        return True

    @property
    def native_value(self):
        """Return the number."""
        value = self._item_value
        return value if value is not None else (self._rest_item.params or {}).get("default")

    async def async_added_to_hass(self) -> None:
        """Restore the value that was set before the restart."""
        await super().async_added_to_hass()
        if self._item_value is not None:
            return
        last_state = await self.async_get_last_state()
        if last_state is None:
            return
        try:
            self._coordinator.async_set_value(
                self._rest_item.key, float(last_state.state)
            )
        except (TypeError, ValueError):
            pass

    async def async_set_native_value(self, value: float) -> None:
        """Remember the value."""
        self._coordinator.async_set_value(self._rest_item.key, value)
