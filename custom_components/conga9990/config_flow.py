"""Configure a robot after checking its local authentication."""

import asyncio

from homeassistant import config_entries
from homeassistant.helpers import selector

import voluptuous as vol

from .const import DOMAIN, PROFILE
from .protocol.local import LocalClient, LocalProtocolError
from .protocol.map_client import MapClient


def map_fields():
    return {
        vol.Optional("map_owner_uid"): str,
        vol.Optional("map_file_token"): selector.TextSelector(selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)),
    }


def validate_map_fields(data):
    if data.get("map_owner_uid") or data.get("map_file_token"):
        MapClient(data["host"],data["device_id"],data["local_key"],
                  data.get("map_owner_uid",""),data.get("map_file_token",""))


class CongaConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_reconfigure(self, user_input=None):
        entry = self._get_reconfigure_entry()
        errors = {}
        if user_input is not None:
            try:
                data = await LocalClient(user_input["host"], user_input["local_key"]).status()
                if "5" not in data or "8" not in data:
                    errors["base"] = "unsupported_device"
                else:
                    try:
                        validate_map_fields({**entry.data,**user_input})
                    except ValueError:
                        errors["base"] = "invalid_map_credentials"
                    if errors:
                        return self.async_show_form(step_id="reconfigure",errors=errors,data_schema=vol.Schema({
                            vol.Required("host",default=entry.data["host"]):str,
                            vol.Required("local_key"):selector.TextSelector(selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)),
                            **map_fields()}))
                    return self.async_update_reload_and_abort(entry, data_updates=user_input)
            except ValueError:
                errors["local_key"] = "invalid_key"
            except LocalProtocolError:
                errors["base"] = "invalid_auth"
            except (OSError, TimeoutError, asyncio.IncompleteReadError):
                errors["base"] = "cannot_connect"
        return self.async_show_form(step_id="reconfigure", errors=errors, data_schema=vol.Schema({
            vol.Required("host", default=entry.data["host"]): str,
            vol.Required("local_key"): selector.TextSelector(selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)),
            **map_fields(),
        }))

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            await self.async_set_unique_id(user_input["device_id"])
            self._abort_if_unique_id_configured()
            try:
                data = await LocalClient(user_input["host"], user_input["local_key"]).status()
                if "5" not in data or "8" not in data:
                    errors["base"] = "unsupported_device"
                else:
                    try:
                        validate_map_fields(user_input)
                    except ValueError:
                        errors["base"] = "invalid_map_credentials"
                    if errors:
                        return self.async_show_form(step_id="user",errors=errors,data_schema=vol.Schema({
                            vol.Required("host"):str,vol.Required("device_id"):str,
                            vol.Required("local_key"):selector.TextSelector(selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)),
                            **map_fields()}))
                    return self.async_create_entry(title=PROFILE["model"], data=user_input)
            except ValueError:
                errors["local_key"] = "invalid_key"
            except LocalProtocolError:
                errors["base"] = "invalid_auth"
            except (OSError, TimeoutError, asyncio.IncompleteReadError):
                errors["base"] = "cannot_connect"
        return self.async_show_form(step_id="user", errors=errors, data_schema=vol.Schema({
            vol.Required("host"): str,
            vol.Required("device_id"): str,
            vol.Required("local_key"): selector.TextSelector(selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)),
            **map_fields(),
        }))
