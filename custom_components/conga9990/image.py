"""Map image and calibrated navigation metadata, with explicit freshness."""

from datetime import datetime, timezone

from homeassistant.components.image import ImageEntity

from .entity import CongaEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([CongaSavedMap(entry.runtime_data)])


class CongaSavedMap(CongaEntity, ImageEntity):
    _attr_content_type = "image/png"

    def __init__(self, coordinator):
        ImageEntity.__init__(self, coordinator.hass)
        CongaEntity.__init__(self, coordinator, "saved_map", "Saved map")
        self._attr_icon = "mdi:map"

    @property
    def available(self):
        return super().available and self.coordinator.map_png is not None

    @property
    def image_last_updated(self):
        return self.coordinator.map_updated

    @property
    def extra_state_attributes(self):
        c = self.coordinator
        grid = c.map_grid
        age = (datetime.now(timezone.utc) - c.position_updated).total_seconds() if c.position_updated else None
        map_age = (datetime.now(timezone.utc)-c.map_received).total_seconds() if c.map_received else None
        return {"live": c.map_active.is_set() and map_age is not None and map_age <= 45,
                "map_received": c.map_received,
                "position_fresh": c.map_active.is_set() and c.position_source in ("local_path_push","local_p2p") and age is not None and age <= 30,
                "robot_position": c.position, "position_updated": c.position_updated,
                "position_source": c.position_source,
                "current_area": c.current_area,
                "map_id": grid.map_id if grid else None, "map_stable": grid.stable if grid else False,
                "map_width": grid.width if grid else None, "map_height": grid.height if grid else None,
                "rooms": list(grid.rooms) if grid else [], "profiles": sorted(c.profiles),
                "selected_profile": c.selected_profile}

    async def async_image(self):
        return self.coordinator.map_png
