"""Shared device registration and availability."""

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, PROFILE


class CongaEntity(CoordinatorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, key, name, dp_id=None):
        super().__init__(coordinator)
        self.dp_id = dp_id
        # Pairing again changes the protocol ID, but the owner's dashboard and
        # entity registry should continue to identify the same physical robot.
        device_id = coordinator.entry.data.get("registry_device_id", coordinator.entry.data["device_id"])
        self._attr_unique_id = f"{device_id}_{key}"
        self._attr_name = name
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, device_id)},
                                            name=coordinator.entry.title,
                                            manufacturer="Cecotec", model=PROFILE["model"])
        self._attr_entity_registry_enabled_default = dp_id is None or dp_id in coordinator.data

    @property
    def available(self):
        return super().available and (self.dp_id is None or self.dp_id in self.coordinator.data)

    @property
    def value(self):
        return self.coordinator.data.get(self.dp_id)
