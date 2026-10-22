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


# Device types of the i-soft PRO family. Their software version carries a
# numeric third component ("1.5.32") where the other families carry a letter
# ("2.21k"), and the two cannot be told apart by the byte alone: patch level
# 33 is 0x21, which is a printable "!".
PRO_FAMILY = frozenset({"58", "4B", "4C"})

# Scene 3, "Urlaub geniessen". The holiday mode runs exactly while this scene
# is the active one, which command 69 byte 0 reports. Command 41 cannot say:
# read back it returns the stored configuration - a device with the mode off
# still answered 0106, flags "active" and six days - so its flag byte is what
# the next start will use, not what is running.
HOLIDAY_SCENE_NUMBER = 0x03

# Scene 0, "Alltag meistern", is the base scene the device falls back to. It
# has no duration - the Judo app offers none for it - so it is always sent
# with the "unendlich" value command 36 documents rather than with whatever
# the duration select happens to hold.
BASE_SCENE_NUMBER = 0x00
SCENE_DURATION_UNLIMITED = 0xFFFF

# Command 69 byte 1, "Aktive Szenenoptionen".
SCENE_OPTION_HOLIDAY = 0x20

# Command 69 byte 2, "Globaler Leckageschutzstatus".
LEAK_STATUS_MICRO_TEST = 0x08
LEAK_STATUS_MICRO_CLOSE = 0x10

# Command 41 byte 0. A different layout from either of the above: its bit 5 is
# the micro leakage option, while bit 5 of command 69's byte 1 is the holiday
# timer. The three registers must not be copied into one another.
HOLIDAY_FLAG_ACTIVE = 0x01
HOLIDAY_FLAG_MICRO_CLOSE = 0x20
HOLIDAY_FLAG_MICRO_AUTOTEST = 0x40
HOLIDAY_FLAG_PROTECTION_OFF = 0x80

# Statuses worth a second attempt rather than an immediate failure. 429 is
# documented by Judo: the module answers it with "Retry-After: 2" when the
# device control does not reply within 1.5 s.
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
# Statuses that mean the credentials were refused.
AUTH_STATUS = frozenset({401, 403})


class JudoApiError(Exception):
    """The device could not be reached or answered with an error."""

    def __init__(self, message: str, status: int | None = None, retryable: bool = False) -> None:
        """Record the HTTP status, if there was one, and whether to retry."""
        super().__init__(message)
        self.status = status
        self.retryable = retryable


class JudoAuthError(JudoApiError):
    """The device refused the credentials.

    Kept apart from any other failure so Home Assistant can ask for new
    credentials instead of retrying forever against a device that answers a
    perfectly healthy 401. A single 401 is still retried once: the module
    answered one whole nightly scan with 401 and was fine again afterwards.
    """


class JudoDecodeError(Exception):
    """The device answered, but the payload could not be interpreted."""


@dataclass(frozen=True, slots=True)
class ItemValue:
    """A decoded value together with the raw payload it came from."""

    value: Any
    raw: str


def _hex_field(
    raw: str, index: int, num_bytes: int, what: str, exact: bool = True
) -> str:
    """Cut a field out of the raw hex payload, byte order unchanged.

    For a numeric field the length must match exactly. A truncated payload
    sliced short drops the *most significant* bytes once the result is reversed
    to little-endian, which turns e.g. 1057.516 m3 into 8.940 m3 with no error
    at all, so a short answer has to fail instead.

    Text is different: the device answers some commands with fewer bytes than
    the maximum (the service contact is declared as 16 bytes but comes back as
    short as it is), and a short string is simply a short string. Those fields
    pass exact=False and take whatever is there.
    """
    start = index * 2
    needed = start + num_bytes * 2
    if exact and len(raw) < needed:
        raise JudoDecodeError(
            f"{what}: payload too short, need {needed} hex chars for "
            f"{num_bytes} byte(s) at offset {index}, got {len(raw)} ({raw!r})"
        )
    if len(raw) <= start:
        raise JudoDecodeError(
            f"{what}: payload {raw!r} has nothing at offset {index}"
        )
    field = raw[start:needed]
    if len(field) % 2:  # an odd number of hex chars is never a whole byte
        field = field[:-1]
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


def _decode_sw_version(field: str, devicetype: str | None = None) -> str:
    """Decode the 3 byte software version.

    Reversed the bytes read major, minor, then a third byte whose meaning
    differs by device family: on an i-soft it is a letter and the version
    reads "2.21k", on an i-soft PRO it is a number and the version reads
    "1.5.32".

    The family decides, not the byte. Guessing from the byte worked only while
    patch levels stayed below 33: 1.5.32 ends in 0x20, a space, but 1.5.33
    ends in 0x21, a printable "!", and would have been rendered as "1.05!".
    """
    data = bytes.fromhex(field)[::-1]
    if len(data) < 2:
        raise JudoDecodeError(f"software version: expected 3 bytes, got {field!r}")
    if len(data) < 3:
        return f"{data[0]}.{data[1]:02d}"
    if devicetype in PRO_FAMILY:
        return f"{data[0]}.{data[1]}.{data[2]}"
    if 0x21 <= data[2] <= 0x7E:
        return f"{data[0]}.{data[1]:02d}{chr(data[2])}"
    return f"{data[0]}.{data[1]}.{data[2]}"


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


def active_scene(status_raw: str | None) -> int | None:
    """Return the scene number command 69 reports as active."""
    if not status_raw:
        return None
    try:
        data = bytes.fromhex(status_raw)
    except ValueError:
        return None
    return data[0] if data else None


def holiday_flags(raw: str | None) -> int:
    """Return command 41's flag byte as the device reports it.

    Command 41 answers a request without data with its two bytes, flags and
    days, so the flags can be written back with a single bit changed instead
    of being rebuilt from elsewhere.
    """
    if not raw:
        return 0
    try:
        data = bytes.fromhex(raw)
    except ValueError:
        return 0
    return data[0] if data else 0


def decode_item(
    rest_item: RestItem, raw: str, divider: float = 1, devicetype: str | None = None
) -> Any:
    """Decode the raw payload of a read command into the item's value.

    Raises JudoDecodeError if the payload does not match what the item expects,
    so that a garbled answer becomes an unavailable entity instead of a
    plausible looking wrong number.
    """
    what = rest_item.translation_key
    field = _hex_field(
        raw,
        rest_item.read_index,
        rest_item.read_bytes,
        what,
        exact=rest_item.format is not FORMATS.TEXT,
    )

    match rest_item.format:
        case FORMATS.NUMBER:
            return _to_int(field, rest_item.read_endian) / divider
        case FORMATS.HOLIDAY:
            return _to_int(field, rest_item.read_endian) == HOLIDAY_SCENE_NUMBER
        case FORMATS.SERIAL:
            # An identifier, not a measurement: a string, so it can never be
            # rendered as "2825589796.0" or recorded as a statistic.
            return str(_to_int(field, rest_item.read_endian))
        case FORMATS.STATUS | FORMATS.SCENE:
            number = _to_int(field, rest_item.read_endian)
            key = rest_item.get_translation_key_from_number(number)
            if key is None:
                raise JudoDecodeError(f"{what}: no status list to map {number}")
            return key
        case FORMATS.SW_VERSION:
            return _decode_sw_version(field, devicetype)
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
        self._base_url = f"http://{self._ip}:{self._port}"
        self._api_url = self._base_url + "/api/rest/"
        self._devicetype = None
        self._lock = asyncio.Lock()
        self._timeout = aiohttp.ClientTimeout(total=CONST.REQUEST_TIMEOUT)

    async def _attempt(self, session, url: str, command: str):
        """Run one REST command once and return the parsed answer."""
        try:
            response = await session.get(url, auth=self._auth, timeout=self._timeout)
            if response.status == 429:
                # Judo documents a Retry-After of 2 seconds for this.
                raise JudoApiError(
                    f"{command}: device busy (429)",
                    status=429,
                    retryable=True,
                )
            if response.status != 200:
                error = (
                    JudoAuthError
                    if response.status in AUTH_STATUS
                    else JudoApiError
                )
                raise error(
                    f"{command}: API returned status {response.status}",
                    status=response.status,
                    retryable=response.status in (RETRYABLE_STATUS | AUTH_STATUS),
                )
            # The module labels its answer text/html, so the content type
            # check of aiohttp has to be switched off.
            return await response.json(content_type=None)
        except (TimeoutError, aiohttp.ClientError, ValueError) as err:
            raise JudoApiError(f"{command}: {err}", retryable=True) from err

    async def _request(self, command: str) -> str:
        """Run one REST command and return the raw hex payload.

        A transient failure is retried once. Without that a single hiccup took
        the whole scan down and put an error in the log, although the device
        was answering normally again a minute later.
        """
        url = self._api_url + command
        session = async_get_clientsession(self._hass)
        async with self._lock:
            _LOGGER.debug("Send command %s", command)
            delay = CONST.RETRY_DELAY
            for attempt in range(CONST.REQUEST_ATTEMPTS):
                if attempt:
                    await asyncio.sleep(delay)
                try:
                    payload = await self._attempt(session, url, command)
                    break
                except JudoApiError as err:
                    if not err.retryable or attempt == CONST.REQUEST_ATTEMPTS - 1:
                        raise
                    delay = CONST.BUSY_RETRY_DELAY if err.status == 429 else CONST.RETRY_DELAY
                    _LOGGER.debug("Retrying %s after %s", command, err)

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

    async def async_read_raw(self) -> str:
        """Fetch the raw payload of this item without decoding it."""
        if self._rest_item.format is FORMATS.BUTTON:
            raise JudoDecodeError(f"{self._rest_item.translation_key} is write only")
        return await self._rest_api.async_get(self._rest_item.address_read)

    def decode(self, raw: str):
        """Decode a raw payload for this item."""
        return decode_item(
            self._rest_item, raw, self._divider, self._rest_api.get_devicetype()
        )

    async def async_read(self) -> ItemValue:
        """Read and decode this item. Raises on any problem.

        Reading and decoding are also available separately, so a decode
        failure can still report the payload it choked on.
        """
        raw = await self.async_read_raw()
        return ItemValue(self.decode(raw), raw)

    async def async_press(self) -> None:
        """Trigger a button item."""
        await self._rest_api.async_set(self._rest_item.address_write, "")

    async def async_write_holiday(self, flags: int, days: int) -> None:
        """Write command 41: the flag byte and a duration in days.

        Command 41 only starts the mode. Writing it with the active bit
        cleared is refused with HTTP 500, "invalid argument" - there is no
        "off" through this command. The mode ends when another scene is
        activated with command 36.
        """
        if not 0 <= days <= 0xFF:
            raise JudoApiError(f"holiday duration {days} out of range")
        _LOGGER.info("Writing holiday mode flags 0x%02X, %s day(s)", flags, days)
        await self._rest_api.async_set(
            CONST.HOLIDAY_COMMAND, f"{flags & 0xFF:02X}{days:02X}"
        )

    async def async_read_holiday(self) -> str | None:
        """Read command 41 back: its flag byte and duration in days.

        Fetched when it is needed rather than polled, because what it reports
        is the stored configuration, not the running state - it is only good
        for writing the other flags back unchanged.
        """
        try:
            return await self._rest_api.async_get(CONST.HOLIDAY_COMMAND)
        except JudoApiError as err:
            _LOGGER.warning("Could not read the holiday configuration: %s", err)
            return None

    async def async_start_holiday(self, days: int) -> None:
        """Switch the holiday mode on for a number of days."""
        raw = await self.async_read_holiday()
        await self.async_write_holiday(holiday_flags(raw) | HOLIDAY_FLAG_ACTIVE, days)

    async def async_activate_scene(self, scene: int, duration: int) -> None:
        """Activate a water scene for a duration.

        Command 36 takes three data bytes: the scene number, then the duration
        as hours and minutes. They go on the wire unchanged - unlike every
        numeric setting in this API, which is little-endian - because the
        document lists the durations as 0100 for one hour and 0200 for two.
        """
        if not 0x00 <= scene <= 0xFF:
            raise JudoApiError(f"scene number {scene} out of range")
        if not 0x0000 <= duration <= 0xFFFF:
            raise JudoApiError(f"scene duration {duration} out of range")
        await self._rest_api.async_set(
            self._rest_item.address_write, f"{scene:02X}{duration:04X}"
        )

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
