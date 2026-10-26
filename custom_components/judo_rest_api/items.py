"""Item classes."""

from homeassistant.helpers.entity import EntityCategory

from .const import DeviceConstants, FormatConstants, TypeConstants


class StatusItem:
    """An item of a status, e.g. error code and error text along with a precise description.

    A class is intentionally defined here because the assignment via dictionaries would not work so elegantly in the end,
    especially when searching backwards. (At least I don't know how...)
    """

    def __init__(
        self,
        number: int,
        translation_key: str | None = None,
    ) -> None:
        """Initialise StatusItem."""
        self._number = number
        self._translation_key = translation_key

    @property
    def number(self) -> int:
        """Return number."""
        return self._number

    @number.setter
    def number(self, value: int) -> None:
        """Set number."""
        self._number = value

    @property
    def translation_key(self) -> str:
        """Return translation_key."""
        return self._translation_key

    @translation_key.setter
    def translation_key(self, val: str) -> None:
        """Set translation_key."""
        self._translation_key = val


class RestItem:
    """Immutable description of a single value in the REST API.

    This is a *description only*. The instances live in module level lists in
    jdconst.py and are therefore shared by every config entry, so they must
    never carry a measured value. Values live in the coordinator, keyed by
    :attr:`key`.
    """

    def __init__(
        self,
        translation_key: str,
        mformat: FormatConstants,
        mtype: TypeConstants,
        device: DeviceConstants,
        address_read: int = None,
        read_index=0,
        read_bytes=1,
        address_write: int = None,
        write_index=0,
        write_bytes=1,
        resultlist=None,
        params: dict = None,
        entity_category: EntityCategory = None,
        read_endian: str = "little",
        response_bytes: int | None = None,
        alt_response: dict[int, int] | None = None,
    ) -> None:
        """Initialise RestItem."""
        self._translation_key = translation_key
        self._address_read = address_read
        self._read_index = read_index
        self._read_bytes = read_bytes
        self._address_write = address_write
        self._write_index = write_index
        self._write_bytes = write_bytes
        self._format = mformat
        self._type = mtype
        self._device = device
        self._entity_category = entity_category
        self._resultlist = resultlist
        self._params = params
        self._read_endian = read_endian
        self._response_bytes = response_bytes
        self._alt_response = alt_response or {}

    @property
    def params(self) -> dict:
        """Return state."""
        return self._params

    @params.setter
    def params(self, val: dict):
        self._params = val

    @property
    def key(self) -> str:
        """Return the key this item's value is stored under in the coordinator."""
        return self._device + "_" + self._translation_key

    @property
    def response_bytes(self) -> int | None:
        """Return how long this command's whole answer has to be.

        Set where the answer carries several fields at fixed offsets. A
        shorter answer there is not a truncated one but a different message,
        and reading the old offsets out of it yields rubbish rather than an
        error.
        """
        return self._response_bytes

    @property
    def alt_response(self) -> dict[int, int]:
        """Return the other answer lengths this command has, and their shift.

        Maps a length in bytes to how many bytes are missing from the front,
        so a field's offset in the short answer is its usual one minus that.
        A field that falls before the start is simply not in it.
        """
        return self._alt_response

    @property
    def read_endian(self) -> str:
        """Return the byte order of the field to read ("little" or "big")."""
        return self._read_endian

    @property
    def format(self) -> FormatConstants:
        """Return format."""
        return self._format

    @property
    def type(self):
        """Return type."""
        return self._type

    @property
    def device(self) -> DeviceConstants:
        """Return device."""
        return self._device

    @device.setter
    def device(self, val: DeviceConstants):
        """Return device."""
        self._device = val

    @property
    def entity_category(self) -> EntityCategory:
        """Return entity category."""
        return self._entity_category

    @property
    def translation_key(self) -> str:
        """Return translation_key."""
        return self._translation_key

    @translation_key.setter
    def translation_key(self, val: str) -> None:
        """Set translation_key."""
        self._translation_key = val

    @property
    def resultlist(self):
        """Return resultlist."""
        return self._resultlist

    def get_translation_key_from_number(self, val: int) -> str:
        """Get errortext from coresponding number."""
        if val is None:
            return None
        if self._resultlist is None:
            return None
        for _useless, item in enumerate(self._resultlist):
            if val == item.number:
                return item.translation_key
        return "unbekannt <" + str(val) + ">"

    def get_number_from_translation_key(self, val: str) -> int:
        """Get number of coresponding errortext."""
        if val is None:
            return None
        if self._resultlist is None:
            return None
        for _useless, item in enumerate(self._resultlist):
            if val == item.translation_key:
                return item.number
        return -1

    @property
    def address_read(self) -> int:
        """Return address."""
        return self._address_read

    @address_read.setter
    def address_read(self, val: int):
        """Set address."""
        self._address_read = val

    @property
    def read_index(self) -> int:
        """Return address."""
        return self._read_index

    @read_index.setter
    def read_index(self, val: int):
        """Set address."""
        self._read_index = val

    @property
    def read_bytes(self) -> int:
        """Return address."""
        return self._read_bytes

    @read_bytes.setter
    def read_bytes(self, val: int):
        """Set address."""
        self._read_bytes = val

    @property
    def address_write(self) -> int:
        """Return address."""
        return self._address_write

    @address_write.setter
    def address_write(self, val: int):
        """Set address."""
        self._address_write = val

    @property
    def write_index(self) -> int:
        """Return address."""
        return self._write_index

    @write_index.setter
    def write_index(self, val: int):
        """Set address."""
        self._write_index = val

    @property
    def write_bytes(self) -> int:
        """Return address."""
        return self._write_bytes

    @write_bytes.setter
    def write_bytes(self, val: int):
        """Set address."""
        self._write_bytes = val
