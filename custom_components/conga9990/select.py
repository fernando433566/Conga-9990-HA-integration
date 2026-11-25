"""Enumerated settings from the observed product schema."""

from homeassistant.components.select import SelectEntity

from .const import SCHEMA, SETTING_SELECTS, name_for
from .entity import CongaEntity

LABELS = {"close": "Off", "both_work": "Vacuum and mop", "only_sweep": "Vacuum only",
          "only_mop": "Mop only", "seat": "Charging dock", "station": "Cleaning station",
          "select_room": "Selected rooms", "pose": "Go to position", "acrubbing": "Scrubbing",
          "espiral": "Spiral", "espiral_cuadrada": "Square spiral"}


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([CongaSelect(entry.runtime_data, dp) for dp in SETTING_SELECTS]
                       + [CongaCleaningProfile(entry.runtime_data)])


class CongaCleaningProfile(CongaEntity, SelectEntity):
    _attr_icon = "mdi:playlist-play"

    def __init__(self, coordinator):
        super().__init__(coordinator, "cleaning_profile", "Cleaning profile")

    @property
    def options(self):
        return sorted(self.coordinator.profiles) or ["No saved profiles"]

    @property
    def current_option(self):
        return self.coordinator.selected_profile

    async def async_select_option(self, option):
        from homeassistant.exceptions import HomeAssistantError
        if option not in self.coordinator.profiles:
            raise HomeAssistantError("Save a cleaning profile before selecting it")
        self.coordinator.selected_profile = option
        self.coordinator.async_update_listeners()


class CongaSelect(CongaEntity, SelectEntity):
    def __init__(self, coordinator, dp_id):
        super().__init__(coordinator, SCHEMA[dp_id]["code"], name_for(dp_id), dp_id)
        self._labels = {LABELS.get(value, value.replace("_", " ").capitalize()): value
                        for value in SCHEMA[dp_id]["property"]["range"]}
        self._attr_options = list(self._labels)

    @property
    def current_option(self):
        return next((label for label, value in self._labels.items() if value == self.value), None)

    async def async_select_option(self, option):
        await self.coordinator.async_write(self.dp_id, self._labels[option])
