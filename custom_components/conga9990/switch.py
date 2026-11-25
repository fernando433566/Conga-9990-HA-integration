"""Schema-verified boolean settings."""

from homeassistant.components.switch import SwitchEntity

from .const import SCHEMA, SETTING_SWITCHES, name_for
from .entity import CongaEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([CongaSwitch(entry.runtime_data, dp) for dp in SETTING_SWITCHES])


class CongaSwitch(CongaEntity, SwitchEntity):
    def __init__(self, coordinator, dp_id):
        super().__init__(coordinator, SCHEMA[dp_id]["code"], name_for(dp_id), dp_id)

    @property
    def is_on(self):
        return self.value if isinstance(self.value, bool) else None

    async def async_turn_on(self, **kwargs):
        await self.coordinator.async_write(self.dp_id, True)

    async def async_turn_off(self, **kwargs):
        await self.coordinator.async_write(self.dp_id, False)
