"""Export protocol and schema coverage without connection credentials."""

from .const import SCHEMA


async def async_get_config_entry_diagnostics(hass, entry):
    coordinator = entry.runtime_data
    return {"model": "Conga 9990 AI Spin Revolution", "protocol": "local authenticated 6699",
            "last_update_success": coordinator.last_update_success,
            "reported_data_point_ids": sorted(coordinator.data, key=int),
            "schema": list(SCHEMA.values()),
            "map_download_implemented": True,
            "native_map_configured": coordinator.map_client is not None,
            "map_last_received": coordinator.map_received,
            "position_source": coordinator.position_source}
