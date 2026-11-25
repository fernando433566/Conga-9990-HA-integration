"""Read-only data points and maintenance percentages."""

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.helpers.entity import EntityCategory

from .const import CONSUMABLES, SCHEMA, name_for
from .entity import CongaEntity


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = entry.runtime_data
    ids = [dp for dp, spec in SCHEMA.items() if spec["property"]["type"] in ("value", "bitmap")
           and (spec["mode"] == "ro" or dp in CONSUMABLES or dp == "28")]
    ids += [dp for dp, spec in SCHEMA.items() if spec["property"]["type"] == "enum" and spec["mode"] == "ro"]
    entities = [CongaSensor(coordinator, dp) for dp in ids]
    entities += [CongaConsumable(coordinator, dp, label) for dp, label in CONSUMABLES.items()]
    entities.append(CongaDataPoints(coordinator))
    entities.append(CongaLocation(coordinator))
    async_add_entities(entities)


class CongaLocation(CongaEntity, SensorEntity):
    _attr_icon = "mdi:map-marker-radius"

    def __init__(self, coordinator):
        super().__init__(coordinator,"robot_location","Current area")

    @property
    def available(self):
        return super().available and self.coordinator.position_fresh

    @property
    def native_value(self):
        return self.coordinator.current_area


class CongaSensor(CongaEntity, SensorEntity):
    def __init__(self, coordinator, dp_id):
        super().__init__(coordinator, SCHEMA[dp_id]["code"], name_for(dp_id), dp_id)
        prop = SCHEMA[dp_id]["property"]
        if prop["type"] == "value":
            self._attr_native_unit_of_measurement = {"㎡": "m²"}.get(prop.get("unit"), prop.get("unit"))
            self._attr_state_class = SensorStateClass.MEASUREMENT
            if dp_id == "8":
                self._attr_device_class = SensorDeviceClass.BATTERY
            elif prop.get("unit") == "min":
                self._attr_device_class = SensorDeviceClass.DURATION
        if dp_id in CONSUMABLES:
            self._attr_icon = "mdi:tools"

    @property
    def native_value(self):
        value = self.value
        scale = SCHEMA[self.dp_id]["property"].get("scale", 0)
        return value / (10 ** scale) if scale and isinstance(value, (int, float)) else value

    @property
    def extra_state_attributes(self):
        if self.dp_id == "28" and isinstance(self.value, int):
            labels = SCHEMA["28"]["property"]["label"]
            return {"faults": [label for i, label in enumerate(labels) if self.value & (1 << i)]}
        return None


class CongaConsumable(CongaEntity, SensorEntity):
    _attr_native_unit_of_measurement = "%"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:tools"

    def __init__(self, coordinator, dp_id, label):
        super().__init__(coordinator, f"{SCHEMA[dp_id]['code']}_percentage", f"{label} life", dp_id)

    @property
    def native_value(self):
        if not isinstance(self.value, (int, float)):
            return None
        maximum = SCHEMA[self.dp_id]["property"]["max"]
        return max(0, min(100, int(self.value * 100 / maximum)))


class CongaDataPoints(CongaEntity, SensorEntity):
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:database-eye"

    def __init__(self, coordinator):
        super().__init__(coordinator, "data_points", "Reported data points")
        self._attr_entity_registry_enabled_default = False

    @property
    def native_value(self):
        return len(self.coordinator.data)

    @property
    def extra_state_attributes(self):
        return {"data_points": dict(self.coordinator.data)}
