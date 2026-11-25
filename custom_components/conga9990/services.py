"""Targeted entity actions usable from dashboards, scripts and automations."""
import voluptuous as vol

from homeassistant.helpers import config_validation as cv, service

from .const import DOMAIN
from .protocol.manual import DIRECTIONS


def async_setup_services(hass):
    common = {vol.Optional("repeats", default=1): vol.All(vol.Coerce(int), vol.Range(min=1, max=3))}
    actions = {
        "manual_move": {vol.Required("direction"): vol.In(DIRECTIONS),
                        vol.Optional("duration", default=.3): vol.All(vol.Coerce(float), vol.Range(min=.1, max=1))},
        "manual_stop": {},
        "clean_home": {},
        "clean_rooms": {vol.Required("room_ids"): [cv.positive_int], **common},
        "clean_spot": {vol.Required("x"): vol.Coerce(float), vol.Required("y"): vol.Coerce(float),
                       vol.Required("map_id"): cv.positive_int},
        "clean_zones": {vol.Required("zones"): [[[vol.Coerce(float)]]],
                        vol.Required("map_id"): cv.positive_int, **common},
        "save_profile": {vol.Required("name"): cv.string, vol.Optional("room_ids"): [cv.positive_int],
                         vol.Optional("zones"): [[[vol.Coerce(float)]]], **common,
                         vol.Optional("fan_speed", default="normal"): vol.In(("close", "gentle", "normal", "strong")),
                         vol.Optional("clean_pattern", default="auto"): vol.In(("auto", "thorough", "border", "scrub", "spiral", "square_spiral", "quiet")),
                         vol.Optional("water_level", default="close"): vol.In(("close", "low", "middle", "high")),
                         vol.Optional("carpet_boost", default=False): cv.boolean,
                         vol.Optional("y_mop", default=False): cv.boolean},
        "run_profile": {vol.Required("name"): cv.string},
        "delete_profile": {vol.Required("name"): cv.string},
    }
    for name, schema in actions.items():
        service.async_register_platform_entity_service(hass, DOMAIN, name, entity_domain="vacuum",
                                                      schema=schema, func=f"async_{name}")
