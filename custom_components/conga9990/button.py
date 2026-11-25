"""Explicit robot actions and maintenance resets."""

from homeassistant.components.button import ButtonEntity

from .const import ACTION_BUTTONS, SCHEMA, name_for
from .entity import CongaEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([CongaButton(entry.runtime_data, dp) for dp in ACTION_BUTTONS]
                       + [CongaRunProfile(entry.runtime_data)])


class CongaRunProfile(CongaEntity, ButtonEntity):
    _attr_icon = "mdi:play-box"

    def __init__(self, coordinator):
        super().__init__(coordinator, "run_cleaning_profile", "Run cleaning profile")

    async def async_press(self):
        await self.coordinator.async_run_profile(self.coordinator.selected_profile)


class CongaButton(CongaEntity, ButtonEntity):
    def __init__(self, coordinator, dp_id):
        super().__init__(coordinator, SCHEMA[dp_id]["code"], name_for(dp_id))
        self.action_dp = dp_id
        self._attr_entity_registry_enabled_default = dp_id == "11"

    async def async_press(self):
        await self.coordinator.async_write(self.action_dp, True)
