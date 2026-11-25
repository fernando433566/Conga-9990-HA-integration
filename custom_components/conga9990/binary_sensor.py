"""Robot fault indicator."""

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity

from .entity import CongaEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([CongaProblem(entry.runtime_data)])


class CongaProblem(CongaEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator):
        super().__init__(coordinator, "problem", "Problem", "28")

    @property
    def is_on(self):
        return bool(self.value) if self.value is not None else None
