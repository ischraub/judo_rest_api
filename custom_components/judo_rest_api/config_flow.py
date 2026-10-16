"""Config flow."""

from types import SimpleNamespace
from typing import Any

import voluptuous as vol
from homeassistant import config_entries, exceptions
import homeassistant.helpers.config_validation as cv
from homeassistant.core import HomeAssistant

from .const import CONF, CONST
from .restobject import JudoApiError, RestAPI

SCAN_INTERVAL_SELECTOR = vol.All(vol.Coerce(int), vol.Range(min=CONST.MIN_SCAN_INTERVAL))


async def validate_input(hass: HomeAssistant, data: dict) -> dict[str, Any]:
    """Validate the input by actually talking to the device.

    Without this the setup succeeded for a wrong host or password and the
    user only noticed later, when every entity stayed empty.
    """
    if len(data[CONF.HOST]) < 3:
        raise InvalidHost

    rest_api = RestAPI(config_entry=SimpleNamespace(data=data), hass=hass)
    try:
        await rest_api.async_connect()
    except JudoApiError as err:
        raise ConnectionFailed(str(err)) from err

    return {"title": data[CONF.HOST]}


class ConfigFlow(config_entries.ConfigFlow, domain=CONST.DOMAIN):  # pylint: disable=W0223
    """Class config flow."""

    VERSION = 2

    def _postfix_in_use(self, postfix: str, ignore_entry_id: str | None = None) -> bool:
        """Return whether another entry already uses this device postfix.

        Entries sharing a postfix end up with identical unique ids and share
        one device in the registry.
        """
        for entry in self._async_current_entries():
            if entry.entry_id == ignore_entry_id:
                continue
            if entry.data.get(CONF.DEVICE_POSTFIX, "") == postfix:
                return True
        return False
    # Pick one of the available connection classes in homeassistant/config_entries.py
    # This tells HA if it should be asking for updates, or it'll be notified of updates
    # automatically. This example uses PUSH, as the dummy hub will notify HA of
    # changes.
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_PUSH

    async def async_step_user(self, user_input=None) -> config_entries.ConfigFlowResult:
        """Step for setup process."""
        # This goes through the steps to take the user through the setup process.
        # Using this it is possible to update the UI and prompt for additional
        # information. This example provides a single form (built from `DATA_SCHEMA`),
        # and when that has some validated input, it calls `async_create_entry` to
        # actually create the HA config entry. Note the "title" value is returned by
        # `validate_input` above.

        # DATA_SCHEMA = vol.Schema({("host"): str, ("port"): cv.port})
        # The caption comes from strings.json / translations/en.json.
        # strings.json can be processed into en.json with some HA commands.
        # did not find out how this works yet.
        data_schema = vol.Schema(
            schema={
                vol.Required(schema=CONF.HOST): str,
                vol.Optional(schema=CONF.PORT, default="80"): cv.port,
                vol.Optional(schema=CONF.USERNAME, default="admin"): str,
                vol.Optional(schema=CONF.PASSWORD, default="Connectivity"): str,
                vol.Optional(schema=CONF.DEVICE_POSTFIX, default=""): str,
                vol.Optional(
                    schema=CONF.SCAN_INTERVAL, default=int(CONST.SCAN_INTERVAL)
                ): SCAN_INTERVAL_SELECTOR,
            }
        )

        errors = {}
        if user_input is not None:
            # One config entry per host, otherwise two entries poll the same
            # device and fight over the same entity ids.
            await self.async_set_unique_id(str(user_input[CONF.HOST]))
            self._abort_if_unique_id_configured()

            if self._postfix_in_use(user_input.get(CONF.DEVICE_POSTFIX, "")):
                errors[CONF.DEVICE_POSTFIX] = "postfix_in_use"
            else:
                try:
                    info = await validate_input(self.hass, user_input)
                    return self.async_create_entry(title=info["title"], data=user_input)
                except InvalidHost:
                    errors[CONF.HOST] = "invalid_host"
                except ConnectionFailed:
                    errors["base"] = "cannot_connect"

        # If there is no user input or there were errors, show the form again,
        # #including any errors that were found with the input.
        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors,
            description_placeholders={
                CONF.HOST: "host",
                CONF.PORT: "port",
                CONF.USERNAME: "username",
                CONF.PASSWORD: "password",
                CONF.DEVICE_POSTFIX: "Device-Postfix",
                CONF.SCAN_INTERVAL: "scan_interval",
            },
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Trigger a reconfiguration flow."""
        errors: dict[str, str] = {}
        reconfigure_entry: config_entries.ConfigEntry[Any] = (
            self._get_reconfigure_entry()
        )

        if user_input:
            if self._postfix_in_use(
                user_input.get(CONF.DEVICE_POSTFIX, ""), reconfigure_entry.entry_id
            ):
                errors[CONF.DEVICE_POSTFIX] = "postfix_in_use"
            else:
                try:
                    await validate_input(self.hass, {**reconfigure_entry.data, **user_input})
                    return self.async_update_reload_and_abort(
                        entry=reconfigure_entry, data_updates=user_input
                    )
                except InvalidHost:
                    errors[CONF.HOST] = "invalid_host"
                except ConnectionFailed:
                    errors["base"] = "cannot_connect"

        schema_reconfigure = vol.Schema(
            schema={
                vol.Required(
                    schema=CONF.HOST, default=reconfigure_entry.data[CONF.HOST]
                ): str,
                vol.Optional(
                    schema=CONF.PORT, default=reconfigure_entry.data[CONF.PORT]
                ): cv.port,
                vol.Optional(
                    schema=CONF.USERNAME, default=reconfigure_entry.data[CONF.USERNAME]
                ): str,
                vol.Optional(
                    schema=CONF.PASSWORD, default=reconfigure_entry.data[CONF.PASSWORD]
                ): str,
                # reconfigure of device postfix leads to duplicated devices
                vol.Optional(
                    schema=CONF.DEVICE_POSTFIX,
                    default=reconfigure_entry.data[CONF.DEVICE_POSTFIX],
                ): str,
                vol.Optional(
                    schema=CONF.SCAN_INTERVAL,
                    default=int(
                        float(
                            reconfigure_entry.data.get(
                                CONF.SCAN_INTERVAL, CONST.SCAN_INTERVAL
                            )
                        )
                    ),
                ): SCAN_INTERVAL_SELECTOR,
            }
        )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=schema_reconfigure,
            errors=errors,
            description_placeholders={
                CONF.HOST: "host",
                CONF.PORT: "port",
                CONF.USERNAME: "username",
                CONF.PASSWORD: "password",
                CONF.DEVICE_POSTFIX: "Device-Postfix",
                CONF.SCAN_INTERVAL: "scan_interval",
            },
        )


class InvalidHost(exceptions.HomeAssistantError):
    """Error to indicate there is an invalid hostname."""


class ConnectionFailed(exceptions.HomeAssistantError):
    """Error to indicate there is an invalid hostname."""
