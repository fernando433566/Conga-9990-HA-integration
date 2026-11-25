"""Native vacuum activity and schema-verified commands."""

from homeassistant.components.vacuum import Segment, StateVacuumEntity, VacuumActivity, VacuumEntityFeature
from homeassistant.exceptions import HomeAssistantError

from .entity import CongaEntity

FAN = {"Off": "close", "Quiet": "gentle", "Normal": "normal", "Turbo": "strong", "Max": "max"}


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([CongaVacuum(entry.runtime_data)])


class CongaVacuum(CongaEntity, StateVacuumEntity):
    _attr_supported_features = (VacuumEntityFeature.STATE | VacuumEntityFeature.START |
                               VacuumEntityFeature.STOP | VacuumEntityFeature.PAUSE |
                               VacuumEntityFeature.RETURN_HOME | VacuumEntityFeature.LOCATE |
                               VacuumEntityFeature.FAN_SPEED)
    _attr_fan_speed_list = list(FAN)

    def __init__(self, coordinator):
        super().__init__(coordinator, "vacuum", None)

    @property
    def supported_features(self):
        grid = self.coordinator.map_grid
        areas = bool(grid and (grid.rooms or any(p["map_id"] == grid.map_id for p in self.coordinator.profiles.values())))
        return self._attr_supported_features | (VacuumEntityFeature.CLEAN_AREA if areas else 0)

    async def async_get_segments(self):
        grid = self.coordinator.map_grid
        if not grid:
            return []
        return ([Segment(id=f"room:{room['id']}", name=room["name"], group="Habitaciones") for room in grid.rooms]
                + [Segment(id=f"profile:{name}", name=name, group="Perfiles") for name, profile in self.coordinator.profiles.items()
                   if profile["map_id"] == grid.map_id])

    async def async_clean_segments(self, segment_ids, **kwargs):
        known = {segment.id for segment in await self.async_get_segments()}
        if not segment_ids or not set(segment_ids) <= known:
            raise HomeAssistantError("Select areas available on the current robot map")
        profiles = [value[8:] for value in segment_ids if value.startswith("profile:")]
        if profiles:
            if len(segment_ids) != 1:
                raise HomeAssistantError("Run one cleaning profile at a time")
            await self.coordinator.async_run_profile(profiles[0])
        else:
            await self.coordinator.async_clean_rooms([int(value[5:]) for value in segment_ids])

    @property
    def activity(self):
        data = self.coordinator.data
        if data.get("28", 0):
            return VacuumActivity.ERROR
        state = data.get("5")
        if state in ("charging", "charge_done", "charging_to_continue", "collecting_dust"):
            return VacuumActivity.DOCKED
        if state == "goto_charge":
            return VacuumActivity.RETURNING
        if state == "paused":
            return VacuumActivity.PAUSED
        if state in ("standby", "sleep", "pos_arrived", "pos_unarrive"):
            return VacuumActivity.IDLE
        if state in ("smart", "zone_clean", "goto_pos", "select_room", "part_clean", "game",
                     "mapping", "manual", "cleaning_to_continue"):
            return VacuumActivity.CLEANING
        return None

    @property
    def fan_speed(self):
        return next((label for label, value in FAN.items() if value == self.coordinator.data.get("9")), None)

    @property
    def extra_state_attributes(self):
        return {"battery_level": self.coordinator.data.get("8"), "robot_status": self.coordinator.data.get("5")}

    async def async_start(self):
        await self.coordinator.async_write("1", True)

    async def async_stop(self, **kwargs):
        await self.coordinator.async_write("1", False)

    async def async_pause(self):
        await self.coordinator.async_write("2", True)

    async def async_return_to_base(self, **kwargs):
        await self.coordinator.async_write("3", True)

    async def async_locate(self, **kwargs):
        await self.coordinator.async_write("11", True)

    async def async_set_fan_speed(self, fan_speed, **kwargs):
        if fan_speed not in FAN:
            raise ValueError("Unknown fan speed")
        await self.coordinator.async_write("9", FAN[fan_speed])

    async def async_manual_move(self, direction, duration=.3):
        await self.coordinator.async_manual_move(direction, duration)

    async def async_manual_stop(self):
        await self.coordinator.async_manual_stop()

    async def async_clean_home(self):
        await self.coordinator.async_clean_home()

    async def async_clean_rooms(self, room_ids, repeats=1):
        await self.coordinator.async_clean_rooms(room_ids, repeats)

    async def async_clean_spot(self, x, y, map_id):
        await self.coordinator.async_clean_spot(x, y, map_id)

    async def async_clean_zones(self, zones, map_id, repeats=1):
        await self.coordinator.async_clean_zones(zones, map_id, repeats)

    async def async_save_profile(self, **kwargs):
        await self.coordinator.async_save_profile(**kwargs)

    async def async_run_profile(self, name):
        await self.coordinator.async_run_profile(name)

    async def async_delete_profile(self, name):
        await self.coordinator.async_delete_profile(name)
