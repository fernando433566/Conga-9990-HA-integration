"""Numeric configuration values from the observed schema."""

from homeassistant.components.number import NumberEntity, NumberMode

from .const import SCHEMA, SETTING_NUMBERS, name_for
from .entity import CongaEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([CongaNumber(entry.runtime_data, dp) for dp in SETTING_NUMBERS])


class CongaNumber(CongaEntity, NumberEntity):
    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator, dp_id):
        super().__init__(coordinator, SCHEMA[dp_id]["code"], name_for(dp_id), dp_id)
        prop = SCHEMA[dp_id]["property"]
        factor = 10 ** prop.get("scale", 0)
        self._factor = factor
        self._attr_native_min_value = prop["min"] / factor
        self._attr_native_max_value = prop["max"] / factor
        self._attr_native_step = prop.get("step", 1) / factor
        self._attr_native_unit_of_measurement = {"㎡": "m²"}.get(prop.get("unit"), prop.get("unit"))

    @property
    def native_value(self):
        return self.value / self._factor if isinstance(self.value, (int, float)) else None

    async def async_set_native_value(self, value):
        await self.coordinator.async_write(self.dp_id, int(round(value * self._factor)))
