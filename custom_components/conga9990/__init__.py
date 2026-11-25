"""Native local integration for the observed Cecotec Conga 9990 profile."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant


async def async_setup(hass, config):
    from pathlib import Path
    from homeassistant.components import frontend
    from homeassistant.components.http import StaticPathConfig
    from .services import async_setup_services
    from .intents import async_setup_intents
    async_setup_services(hass)
    async_setup_intents(hass)
    url = "/conga9990/conga-map-card.js"
    await hass.http.async_register_static_paths([
        StaticPathConfig(url, str(Path(__file__).parent / "www" / "conga-map-card.js"), False),
        StaticPathConfig("/conga9990/conga-vacuum.svg",
                         str(Path(__file__).parent / "www" / "conga-vacuum.svg"), False),
    ])
    frontend.add_extra_js_url(hass, url + "?v=0.4.4")
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    from homeassistant.core import callback
    from .coordinator import CongaCoordinator
    from .const import PLATFORMS

    coordinator = CongaCoordinator(hass, entry)
    await coordinator.async_load_profiles()
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    task = entry.async_create_background_task(hass, coordinator.async_map_listener(), "conga_map_updates")
    @callback
    def cancel_map_listener():
        task.cancel()

    entry.async_on_unload(cancel_map_listener)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    from .const import PLATFORMS

    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
