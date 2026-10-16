"""RESTobject.

A REST object that contains a REST item and communicates with the REST-API.
It contains a REST Client for setting and getting REST response values.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import date
from typing import Any

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .configentry import MyConfigEntry
from .const import CONF, CONST, DEVICETYPES, FORMATS, TYPES
from .items import RestItem

_LOGGER = logging.getLogger(__name__)


class JudoApiError(Exception):
    """The device could not be reached or answered with an error."""


class JudoDecodeError(Exception):
    """The device answered, but the payload could not be interpreted."""


@dataclass(frozen=True, slots=True)
class ItemValue:
    """A decoded value together with the raw payload it came from."""

    value: Any
    raw: str


def _hex_field(raw: str, index: int, num_bytes: int, what: str) -> str:
    """Cut a field out of the raw hex payload, big-endian, byte order unchanged.

    The device sometimes answers with a truncated payload. Slicing that
    silently drops the *most significant* bytes once the result is reversed to
    little-endian, which turns e.g. 1057.516 m3 into 8.940 m3 without any
    error. So the length is checked before anything is cut.
    """
    needed = (index + num_bytes) * 2
    if len(raw) < needed:
        raise JudoDecodeError(
            f"{what}: payload too short, need {needed} hex chars for "
            f"{num_bytes} byte(s) at offset {index}, got {len(raw)} ({raw!r})"
        )
    field = raw[index * 2 : needed]
    try:
        bytes.fromhex(field)
    except ValueError as err:
        raise JudoDecodeError(f"{what}: field {field!r} is not valid hex") from err
    return field


def _to_int(field: str, endian: str) -> int:
    """Interpret a hex field as an unsigned integer with the given byte order."""
    return int.from_bytes(bytes.fromhex(field), endian)  # type: ignore[arg-type]


def _decode_text(field: str) -> str:
    """Decode a hex field as text, dropping padding."""
    return bytes.fromhex(field).decode("ascii", "replace").replace("\x00", "").strip()


def _decode_sw_version(field: str) -> str:
    """Decode the 3 byte software version.

    Layout is <letter> <minor> <major>, so reversed it reads major.minor+letter.
    The first byte is not a printable letter on every firmware (an i-soft PRO
    on 1.04 sends a non-printable byte there), and blindly decoding it put a
    replacement glyph into the state, so it is only appended when printable.
    """
    data = bytes.fromhex(field)[::-1]
    if len(data) < 2:
        raise JudoDecodeError(f"software version: expected 3 bytes, got {field!r}")
    version = f"{data[0]}.{data[1]:02d}"
    if len(data) > 2 and 0x21 <= data[2] <= 0x7E:
        version += chr(data[2])
    return version


def _decode_operating_time(field: str, endian: str) -> float:
    """Decode the 4 byte operating time counter into hours.

    Layout is <minutes> <hours> <days, 2 bytes>. The three parts used to be
    three separate MEASUREMENT sensors, so "operating hours" showed the 0..23
    remainder rather than the operating time.

    The byte order of the day counter is firmware dependent: an i-soft PRO on
    1.04 answers big-endian, while a payload captured from an i-soft on 2.21k
    only makes sense little-endian. Hence it comes from the item.
    """
    data = bytes.fromhex(field)
    if len(data) < 4:
        raise JudoDecodeError(f"operating time: expected 4 bytes, got {field!r}")
    minutes, hours = data[0], data[1]
    days = int.from_bytes(data[2:4], endian)  # type: ignore[arg-type]
    return days * 24 + hours + minutes / 60


def _decode_date(field: str) -> date:
    """Decode the 4 byte commissioning date.

    Layout is <day> <month> <year high> <year low>: the year is the one field
    in the whole API that is big-endian. Verified against a device reporting
    0d0507e9 -> 13.05.2025, cross-checked against its operating-day counter.
    """
    data = bytes.fromhex(field)
    if len(data) < 4:
        raise JudoDecodeError(f"date: expected 4 bytes, got {field!r}")
    day, month = data[0], data[1]
    year = int.from_bytes(data[2:4], "big")
    try:
        return date(year, month, day)
    except ValueError as err:
        raise JudoDecodeError(f"date: {day:02d}.{month:02d}.{year} is not a date") from err


def decode_item(rest_item: RestItem, raw: str, divider: float = 1) -> Any:
    """Decode the raw payload of a read command into the item's value.

    Raises JudoDecodeError if the payload does not match what the item expects,
    so that a garbled answer becomes an unavailable entity instead of a
    plausible looking wrong number.
    """
    what = rest_item.translation_key
    field = _hex_field(raw, rest_item.read_index, rest_item.read_bytes, what)

    match rest_item.format:
        case FORMATS.NUMBER:
            return _to_int(field, rest_item.read_endian) / divider
        case FORMATS.STATUS:
            number = _to_int(field, rest_item.read_endian)
            key = rest_item.get_translation_key_from_number(number)
            if key is None:
                raise JudoDecodeError(f"{what}: no status list to map {number}")
            return key
        case FORMATS.SW_VERSION:
            return _decode_sw_version(field)
        case FORMATS.DATE:
            return _decode_date(field)
        case FORMATS.DURATION:
            return _decode_operating_time(field, rest_item.read_endian)
        case FORMATS.TEXT:
            return _decode_text(field)
        case _:
            raise JudoDecodeError(f"{what}: cannot read format {rest_item.format}")


class RestAPI:
    """Connection to the REST API of the Judo connectivity module.

    The module serves a single request at a time, so every call is serialised
    through a lock. Without it a user writing a value while the coordinator is
    polling makes the device answer with truncated or stale payloads.
    """

    def __init__(self, config_entry: MyConfigEntry, hass: HomeAssistant) -> None:
        """Construct RestAPI.

        :param config_entry: HASS config entry
        :type config_entry: MyConfigEntry
        """
        self._ip = config_entry.data[CONF.HOST]
        self._port = config_entry.data[CONF.PORT]
        self._hass = hass
        self._auth = aiohttp.BasicAuth(
            config_entry.data[CONF.USERNAME], config_entry.data[CONF.PASSWORD]
        )
        self._api_url = f"http://{self._ip}:{self._port}/api/rest/"
        self._devicetype = None
        self._lock = asyncio.Lock()
        self._timeout = aiohttp.ClientTimeout(total=CONST.REQUEST_TIMEOUT)

    async def _request(self, command: str) -> str:
        """Run one REST command and return the raw hex payload."""
        url = self._api_url + command
        session = async_get_clientsession(self._hass)
        async with self._lock:
            _LOGGER.debug("Send command %s", command)
            try:
                response = await session.get(
                    url, auth=self._auth, timeout=self._timeout
                )
                if response.status != 200:
                    raise JudoApiError(
                        f"{command}: API returned status {response.status}"
                    )
                # The module labels its answer text/html, so the content type
                # check of aiohttp has to be switched off.
                payload = await response.json(content_type=None)
            except (TimeoutError, aiohttp.ClientError, ValueError) as err:
                raise JudoApiError(f"{command}: {err}") from err

        if not isinstance(payload, dict) or "data" not in payload:
            raise JudoApiError(f"{command}: answer without data field: {payload!r}")
        data = payload["data"]
        if not isinstance(data, str):
            raise JudoApiError(f"{command}: data is {type(data).__name__}, not a string")
        _LOGGER.debug("Content %s", data)
        return data

    async def async_get(self, command: str) -> str:
        """Get the raw response for a read command."""
        if command is None:
            raise JudoApiError("read command is None")
        return await self._request(command)

    async def async_set(self, command: str, towrite: str = "") -> None:
        """Append the payload to a write command and send it."""
        if command is None:
            raise JudoApiError("write command is None")
        await self._request(command + towrite)

    async def async_connect(self) -> str:
        """Read the device type to prove the device is reachable.

        The type sits in the first byte; devices answer this command with two
        bytes ("5800"), so the whole payload must not be looked up directly.
        An unknown id is not fatal - a device this integration has no name for
        still serves every other command.
        """
        res = await self.async_get("FF00")
        if len(res) < 2:
            raise JudoApiError(f"FF00: device type payload too short: {res!r}")
        devicetype = res[0:2].upper()
        if devicetype in DEVICETYPES:
            _LOGGER.info("Connected to %s %s", devicetype, DEVICETYPES[devicetype])
        else:
            _LOGGER.warning("Unknown Judo device detected, ID=%s", devicetype)
        self._devicetype = devicetype
        return devicetype

    def get_devicetype(self):
        """Return device type."""
        return self._devicetype


class RestObject:
    """RestObject.

    A REST object that contains a REST item and communicates with the REST.
    It contains a REST Client for setting and getting REST register values
    """

    def __init__(self, rest_api: RestAPI, rest_item: RestItem) -> None:
        """Construct RestObject.

        :param rest_api: The REST API
        :type rest_api: RestAPI
        :param rest_item: definition of rest item
        :type rest_item: RestItem
        """
        self._rest_item = rest_item
        self._rest_api = rest_api
        self._divider = 1
        if self._rest_item.params is not None:
            self._divider = self._rest_item.params.get("divider", 1)

    def order_hex_buffer(self, buffer: str, flip) -> str:
        """brings a hex buffer in the right order"""
        if flip is True:
            return bytes.fromhex(buffer)[::-1].hex()
        return bytes.fromhex(buffer)[::1].hex()

    def format_int_message(self, number: int, flip) -> str:
        """format int message as hex buffer to be sent to REST APPI"""
        numbytes = str(self._rest_item.write_bytes * 2)
        mask = "%0." + numbytes + "X"
        return self.order_hex_buffer(mask % number, flip)

    def format_str_message(self, text: str, flip) -> str:
        """format str message as hex buffer to be sent to REST APPI"""
        return self.order_hex_buffer(text.encode("utf-8").hex(), flip)

    async def async_read(self) -> ItemValue:
        """Read and decode this item. Raises on any problem."""
        if self._rest_item.format is FORMATS.BUTTON:
            raise JudoDecodeError(f"{self._rest_item.translation_key} is write only")
        raw = await self._rest_api.async_get(self._rest_item.address_read)
        return ItemValue(decode_item(self._rest_item, raw, self._divider), raw)

    async def async_press(self) -> None:
        """Trigger a button item."""
        await self._rest_api.async_set(self._rest_item.address_write, "")

    async def async_write(self, value) -> Any:
        """Write a value to the device and return what was written."""
        if self._rest_item.type == TYPES.SENSOR:
            raise JudoApiError(f"{self._rest_item.translation_key} is read only")

        match self._rest_item.format:
            case FORMATS.NUMBER:
                towrite = self.format_int_message(
                    int(float(value) * self._divider), True
                )
            case FORMATS.TEXT:
                towrite = self.format_str_message(str(value), True)
            case FORMATS.STATUS:
                number = self._rest_item.get_number_from_translation_key(value)
                if number is None or number < 0:
                    raise JudoApiError(
                        f"{self._rest_item.translation_key}: unknown option {value!r}"
                    )
                towrite = self.format_int_message(int(number * self._divider), True)
            case _:
                raise JudoApiError(
                    f"{self._rest_item.translation_key}: cannot write format "
                    f"{self._rest_item.format}"
                )

        await self._rest_api.async_set(self._rest_item.address_write, towrite)
        return value

    async def async_add(self, value) -> Any:
        """Add a value to the one currently stored in the device."""
        current = await self.async_read()
        if self._rest_item.format is FORMATS.STATUS:
            number = self._rest_item.get_number_from_translation_key(value)
            if number is None or number < 0:
                raise JudoApiError(
                    f"{self._rest_item.translation_key}: unknown option {value!r}"
                )
            new_value = float(number) + float(current.value)
        else:
            new_value = float(value) + float(current.value)

        towrite = self.format_int_message(int(new_value * self._divider), True)
        await self._rest_api.async_set(self._rest_item.address_write, towrite)
        return new_value
