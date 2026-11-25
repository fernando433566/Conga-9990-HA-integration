"""Coordinate authenticated local polling and acknowledged writes."""

import asyncio
import base64
import hashlib
import os
import tempfile
from datetime import datetime, timedelta, timezone
import logging
from pathlib import Path

from homeassistant.exceptions import HomeAssistantError
from homeassistant.core import callback
from homeassistant.components import persistent_notification
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.helpers.storage import Store

from .const import DOMAIN, SCHEMA
from .protocol.local import LocalClient, LocalProtocolError
from .protocol.map import MapFormatError, decode_map, make_png
from .protocol.manual import ManualControl
from .protocol.navigation import decode_command, room_command, spot_command, zone_command, validate_profile, resolve_profile_name
from .protocol.path import decode_path
from .protocol.map_client import MapClient

LOGGER = logging.getLogger(__name__)

ACTIVE_MAP_STATES = {"smart", "zone_clean", "goto_pos", "select_room", "part_clean",
                     "game", "mapping", "manual", "cleaning_to_continue", "goto_charge"}
FAULT_NAMES = {"no_dust_box": "Depósito de polvo ausente", "dustbox_out": "Depósito de polvo retirado",
               "dustbox_full": "Depósito de polvo lleno", "dustbox_fullout": "Depósito lleno o retirado",
               "no_dust_water_box": "Depósito mixto ausente", "wheel_trap": "Rueda atascada",
               "collision_stuck": "Paragolpes bloqueado", "dust_station_full": "Revisar bolsa o estación de vaciado",
               "low_power": "Batería baja", "battery_err": "Error de batería", "poweroff": "Apagado",
               "middle_sweep": "Error del cepillo central", "side_sweep": "Error del cepillo lateral",
               "fan_speed": "Error del ventilador", "trapped": "Robot atascado", "pick_up": "Robot levantado",
               "water_box_empty": "Depósito de agua vacío", "findcharge_fail": "No se encuentra la base",
               "lidar_speed_err": "Error de velocidad del láser", "lidar_cover": "Láser tapado",
               "lidar_point_err": "Error del sensor láser", "front_wall_dirty": "Sensor frontal sucio",
               "psd_dirty": "Sensor de distancia sucio", "tile_error": "Error de inclinación",
               "forbid_area": "Robot en zona restringida", "land_check": "Error de detección del suelo"}


def validate_value(dp_id, value):
    spec = SCHEMA.get(str(dp_id))
    if spec is None or "w" not in spec["mode"]:
        raise HomeAssistantError("This data point is not writable")
    prop = spec["property"]
    kind = prop["type"]
    if kind == "bool":
        valid = isinstance(value, bool)
    elif kind == "enum":
        valid = value in prop["range"]
    elif kind == "value":
        valid = (isinstance(value, (int, float)) and not isinstance(value, bool)
                 and prop["min"] <= value <= prop["max"]
                 and (value - prop["min"]) % prop.get("step", 1) == 0)
    elif kind == "raw" and str(dp_id) == "15":
        try:
            code, _ = decode_command(value)
            valid = code in (0x58, 0x60, 0x62)
        except (ValueError, TypeError):
            valid = False
    else:
        valid = False
    if not valid:
        raise HomeAssistantError("Value is outside the observed device schema")


class CongaCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, entry):
        super().__init__(hass, LOGGER, name=DOMAIN, config_entry=entry,
                         update_interval=timedelta(seconds=15))
        self.entry = entry
        self.client = LocalClient(entry.data["host"], entry.data["local_key"])
        self.io_lock = asyncio.Lock()
        self.map_path = Path(hass.config.path(".storage", DOMAIN, f"{entry.entry_id}.map"))
        self.map_png = None
        self.map_updated = None
        self._map_stamp = None
        self.map_grid = None
        self.position = None
        self.position_updated = None
        self.position_source = None
        self.path_path = self.map_path.with_suffix(".path")
        self._path_stamp = None
        self.path_id = None
        self.path_points = []
        self.profiles = {}
        self.selected_profile = None
        self.profile_store = Store(hass, 1, f"{DOMAIN}_{entry.entry_id}_profiles")
        self.command_lock = asyncio.Lock()
        self.manual = ManualControl(self._async_write_values)
        self.map_commands = set()
        self.map_lock = asyncio.Lock()
        self.map_received = None
        self._stream_map_signature = None
        self._map_digest = None
        self.map_client = None
        self.map_active = asyncio.Event()
        self._map_stream_task = None
        self._last_fault = None
        if entry.data.get("map_owner_uid") and entry.data.get("map_file_token"):
            self.map_client = MapClient(entry.data["host"],entry.data["device_id"],entry.data["local_key"],
                                        entry.data["map_owner_uid"],entry.data["map_file_token"])

    async def async_load_profiles(self):
        saved = await self.profile_store.async_load()
        if isinstance(saved, dict):
            for name, profile in saved.get("profiles", {}).items():
                try:
                    self.profiles[name] = validate_profile(profile)
                except (ValueError, TypeError, KeyError):
                    LOGGER.warning("Ignoring an invalid saved cleaning profile")

    def _load_saved_map(self):
        try:
            stat = self.map_path.stat()
        except FileNotFoundError:
            self._map_stamp = None
            self.map_png = self.map_updated = self.map_grid = None
            return
        stamp = (stat.st_mtime_ns, stat.st_size)
        if stamp == self._map_stamp:
            return
        self._map_stamp = stamp
        try:
            if stat.st_size > 2 * 1024 * 1024:
                raise MapFormatError("Saved map file exceeds the supported profile limit")
            raw = self.map_path.read_bytes()
            grid = decode_map(raw, max_cells=1024 * 1024)
            self._map_digest = hashlib.sha256(raw).digest()
            if self.map_grid and self.map_grid.signature != grid.signature:
                self.position = self.position_updated = None
                self.position_source = None
                self.path_id = None
                self.path_points = []
            self.map_grid = grid
            self.map_png = make_png(grid.width, grid.height, grid.cells)
            self.map_updated = datetime.fromtimestamp(stat.st_mtime, timezone.utc)
        except (OSError, MapFormatError, ValueError):
            self.map_png = self.map_updated = self.map_grid = None
            LOGGER.warning("Saved map does not match the supported map profile")

    async def _async_update_data(self):
        try:
            async with self.io_lock:
                data = await self.client.status()
            async with self.map_lock:
                await self.hass.async_add_executor_job(self._load_saved_navigation)
            merged = {**(self.data or {}), **data}
            self._sync_report(merged)
            return merged
        except (OSError, TimeoutError, asyncio.IncompleteReadError, LocalProtocolError) as exc:
            self._set_map_active(False)
            raise UpdateFailed(f"Local robot query failed: {exc}") from exc

    @callback
    def _set_map_active(self, active):
        if active:
            self.map_active.set()
        else:
            self.map_active.clear()
            if self._map_stream_task and not self._map_stream_task.done():
                self._map_stream_task.cancel()

    @callback
    def _sync_report(self, data):
        faults = data.get("28")
        self._set_map_active(data.get("5") in ACTIVE_MAP_STATES and not faults)
        if not isinstance(faults, int) or isinstance(faults, bool) or faults < 0 or faults == self._last_fault:
            return
        self._last_fault = faults
        notification_id = f"conga9990_{self.entry.entry_id}_fault"
        if not faults:
            persistent_notification.async_dismiss(self.hass, notification_id)
            return
        labels = SCHEMA["28"]["property"]["label"]
        names = [FAULT_NAMES.get(label, label.replace("_", " "))
                 for i, label in enumerate(labels) if faults & (1 << i)]
        if faults >> len(labels):
            names.append("Código de avería no identificado")
        persistent_notification.async_create(
            self.hass, "\n".join(f"- {name}" for name in names) + f"\n\nCódigo del robot: `{faults}`.",
            title=f"{self.entry.title}: avería", notification_id=notification_id)

    @callback
    def async_set_updated_data(self, data):
        self._sync_report(data)
        super().async_set_updated_data(data)

    def _load_saved_navigation(self):
        self._load_saved_map()
        if self.map_grid is None:
            return
        try:
            stat = self.path_path.stat()
            stamp = (stat.st_mtime_ns, stat.st_size, self.map_grid.signature)
            if stamp == self._path_stamp:
                return
            if stat.st_size > 128 * 1024:
                raise ValueError("Saved path exceeds bounds")
            path = decode_path(self.path_path.read_bytes())
            if not path["points"]:
                return
            # This narrow saved-file profile was observed as a paired map/path
            # with matching identifiers. Refuse other combinations.
            if path["path_id"] != self.map_grid.map_id:
                raise ValueError("Saved map/path pairing not established")
            x, y = path["points"][-1]
            x += self.map_grid.origin[0]; y += self.map_grid.origin[1]
            if not 0 <= x < self.map_grid.width or not 0 <= y < self.map_grid.height:
                raise ValueError("Saved position outside map")
            self._path_stamp = stamp
            self.path_id = path["path_id"]
            self.path_points = path["points"]
            # Never replace a newer live report with the saved snapshot.
            updated = datetime.fromtimestamp(stat.st_mtime, timezone.utc)
            if self.position_updated is None or self.position_updated < updated:
                self.position = {"x": x, "y": y, "angle": path["angle"], "map_id": self.map_grid.map_id}
                self.position_updated = updated
                self.position_source = "saved_path"
        except FileNotFoundError:
            pass
        except (OSError, ValueError, TypeError):
            LOGGER.debug("Ignoring incompatible saved path")

    async def async_write(self, dp_id, value):
        validate_value(dp_id, value)
        try:
            async with self.io_lock:
                await self.client.set_dps({str(dp_id): value})
                updated = await self.client.status()
        except (OSError, TimeoutError, asyncio.IncompleteReadError, LocalProtocolError) as exc:
            raise HomeAssistantError(f"Local robot command failed: {exc}") from exc
        self.async_set_updated_data(updated)

    async def _async_write_values(self, values):
        for dp, value in values.items():
            validate_value(dp, value)
        try:
            async with self.io_lock:
                await self.client.set_dps(values)
        except (OSError, TimeoutError, asyncio.IncompleteReadError, LocalProtocolError) as exc:
            raise HomeAssistantError(f"Local robot command failed: {exc}") from exc

    async def async_manual_move(self, direction, duration=.3):
        if self.command_lock.locked():
            raise HomeAssistantError("Another navigation command is running")
        async with self.command_lock:
            try:
                await self.manual.step(direction, duration)
            except ValueError as exc:
                raise HomeAssistantError(str(exc)) from exc
        await self.async_request_refresh()

    async def async_manual_stop(self):
        await self.manual.stop()

    async def async_clean_home(self):
        if self.command_lock.locked():
            raise HomeAssistantError("Another navigation command is running")
        async with self.command_lock:
            await self._async_write_values({"4": "smart"})
            await self._async_write_values({"1": True})
        await self.async_request_refresh()

    def _require_map(self, map_id=None):
        if self.map_grid is None or not self.map_grid.resolution:
            raise HomeAssistantError("A calibrated map is required for targeted cleaning")
        if self.map_client and (self.map_received is None or (datetime.now(timezone.utc)-self.map_received).total_seconds()>45):
            raise HomeAssistantError("Wait for the current robot map before targeted cleaning")
        if map_id is not None and self.map_grid.map_id != map_id:
            raise HomeAssistantError("The selection belongs to another map; select it again")
        return self.map_grid

    def _validate_rooms(self, room_ids):
        grid = self._require_map()
        known = {room["id"] for room in grid.rooms}
        if not room_ids or not set(room_ids) <= known:
            raise HomeAssistantError("Select rooms present in the current map")

    async def _async_start_selection(self, mode, encoded):
        if self.command_lock.locked():
            raise HomeAssistantError("Another navigation command is running")
        async with self.command_lock:
            # The Conga panel sends selection and settings in one combined
            # command. Do not append a generic whole-house start or mode write.
            async with self.io_lock:
                try:
                    validate_value("15", encoded)
                    await self.client.set_dps({"15": encoded})
                    data = await self.client.status()
                except (OSError, TimeoutError, asyncio.IncompleteReadError, LocalProtocolError) as exc:
                    raise HomeAssistantError(f"Targeted cleaning command failed: {exc}") from exc
            self.async_set_updated_data(data)

    async def async_clean_rooms(self, room_ids, repeats=1):
        self._validate_rooms(room_ids)
        try:
            encoded = room_command(room_ids, repeats)
        except ValueError as exc:
            raise HomeAssistantError(str(exc)) from exc
        await self._async_start_selection("select_room", encoded)

    async def async_clean_spot(self, x, y, map_id):
        try:
            rx, ry = self._require_map(map_id).pixel_to_robot(x, y)
            encoded = spot_command(rx, ry)
        except ValueError as exc:
            raise HomeAssistantError(str(exc)) from exc
        await self._async_start_selection("pose", encoded)

    def _zone_coordinates(self, zones):
        grid = self._require_map()
        result = []
        for zone in zones:
            if len(zone) != 4:
                raise HomeAssistantError("A zone must have four corners")
            result.append([list(grid.pixel_to_robot(*point, traversable=False)) for point in zone])
        return result

    async def async_clean_zones(self, zones, map_id, repeats=1):
        self._require_map(map_id)
        try:
            encoded = zone_command(self._zone_coordinates(zones), repeats)
        except (ValueError, TypeError) as exc:
            raise HomeAssistantError(str(exc)) from exc
        await self._async_start_selection("zone", encoded)

    async def async_save_profile(self, name, room_ids=None, zones=None, repeats=1, fan_speed="normal",
                                 clean_pattern="auto", water_level="close", carpet_boost=False, y_mop=False):
        name = name.strip()
        name = resolve_profile_name(name,self.profiles) or name
        if not name or len(name) > 80 or (name not in self.profiles and len(self.profiles) >= 32):
            raise HomeAssistantError("Choose a profile name (maximum 32 profiles, 80 characters)")
        grid = self._require_map()
        try:
            if room_ids:
                self._validate_rooms(room_ids)
            profile = {"room_ids": room_ids or [], "zones": self._zone_coordinates(zones or []),
                       "repeats": repeats, "fan_speed": fan_speed, "map_id": grid.map_id,
                       "map_signature": grid.signature, "clean_pattern": clean_pattern,
                       "water_level": water_level, "carpet_boost": carpet_boost, "y_mop": y_mop}
            profile = validate_profile(profile)
        except (ValueError, TypeError) as exc:
            raise HomeAssistantError(str(exc)) from exc
        updated = {**self.profiles, name: profile}
        await self.profile_store.async_save({"profiles": updated})
        self.profiles = updated
        self.selected_profile = name
        self.async_update_listeners()

    async def async_delete_profile(self, name):
        if name not in self.profiles:
            raise HomeAssistantError("Unknown cleaning profile")
        updated = dict(self.profiles)
        del updated[name]
        await self.profile_store.async_save({"profiles": updated})
        self.profiles = updated
        if self.selected_profile == name:
            self.selected_profile = None
        self.async_update_listeners()

    async def async_run_profile(self, name):
        name = resolve_profile_name(name,self.profiles)
        profile = self.profiles.get(name)
        if profile is None:
            raise HomeAssistantError("Unknown cleaning profile; no cleaning was started")
        grid = self._require_map(profile["map_id"])
        if profile.get("map_signature") != grid.signature:
            raise HomeAssistantError("Map calibration changed; save the profile again")
        options = {key: profile[key] for key in ("fan_speed", "clean_pattern", "water_level", "carpet_boost", "y_mop") if key in profile}
        if profile.get("room_ids"):
            self._validate_rooms(profile["room_ids"])
            mode, encoded = "select_room", room_command(profile["room_ids"], profile.get("repeats", 1), **options)
        else:
            mode, encoded = "zone", zone_command(profile["zones"], profile.get("repeats", 1), **options)
        await self._async_start_selection(mode, encoded)

    async def async_process_map_updates(self, dps):
        """Merge pushes without replacing status with a partial DP report."""
        if "15" in dps:
            try:
                code, _ = decode_command(dps["15"])
                self.map_commands.add(code)
            except ValueError:
                LOGGER.debug("Ignoring unsupported map command report")
        if "14" in dps and self.map_grid is not None and self.map_active.is_set():
            try:
                raw = base64.b64decode(dps["14"], validate=True)
                path = decode_path(raw)
                if not path["points"]:
                    self.position = self.position_updated = None
                    self.position_source = "empty_path"
                    self.async_set_updated_data({**(self.data or {}), **dps})
                    return
                if not path["initial"] and self.path_id != path["path_id"]:
                    raise ValueError("Incremental path without its initial packet")
                # Path id and map id are separate identifiers. An initial path
                # establishes this session; a map change clears it above.
                points = path["points"]
                if path["initial"]:
                    self.path_points = points
                else:
                    self.path_points = (self.path_points + points)[-16384:]
                self.path_id = path["path_id"]
                x, y = points[-1]
                grid = self.map_grid
                if not grid.resolution:
                    raise ValueError("Uncalibrated map")
                px, py = x + grid.origin[0], y + grid.origin[1]
                if not 0 <= px < grid.width or not 0 <= py < grid.height:
                    raise ValueError("Position outside current map")
                self.position = {"x": px, "y": py, "angle": path["angle"], "map_id": grid.map_id}
                self.position_updated = datetime.now(timezone.utc)
                self.position_source = "local_path_push"
            except (ValueError, TypeError):
                LOGGER.debug("Ignoring unsupported or uncalibrated path data")
        self.async_set_updated_data({**(self.data or {}), **dps})

    async def async_map_listener(self):
        while True:
            await self.map_active.wait()
            try:
                if self.map_client:
                    self._stream_map_signature = None
                    stream = self.map_client.stream(self.async_receive_map_file)
                else:
                    stream = self.client.listen_map_updates(self.async_process_map_updates)
                self._map_stream_task = asyncio.create_task(stream)
                await self._map_stream_task
            except asyncio.CancelledError:
                if asyncio.current_task().cancelling():
                    raise
            except (OSError, TimeoutError, asyncio.IncompleteReadError, LocalProtocolError, ValueError):
                LOGGER.debug("Map/path stream disconnected; retrying")
            finally:
                self._map_stream_task = None
            await asyncio.sleep(2 if self.map_client else 5)

    def _store_stream_file(self, path, data):
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".conga-stream-", delete=False) as output:
                temporary = Path(output.name)
                output.write(data)
            os.replace(temporary,path)
            return path.stat()
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()

    async def async_receive_map_file(self, name, data):
        """Apply complete authenticated P2P files; an empty route is not a pose."""
        if not self.map_active.is_set():
            return
        if name == "map.bin.stream":
            async with self.map_lock:
                digest = hashlib.sha256(data).digest()
                if digest != self._map_digest or self.map_grid is None:
                    def prepare():
                        grid = decode_map(data,max_cells=1024*1024)
                        png = make_png(grid.width,grid.height,grid.cells)
                        stat = self._store_stream_file(self.map_path,data)
                        return grid,png,stat
                    grid,png,stat = await self.hass.async_add_executor_job(prepare)
                    if self.map_grid and self.map_grid.signature != grid.signature:
                        self.position = self.position_updated = self.position_source = None
                        self.path_id = None; self.path_points = []
                    self.map_grid,self.map_png = grid,png
                    self._map_digest = digest
                    self._map_stamp = (stat.st_mtime_ns,stat.st_size)
                    self.map_updated = datetime.fromtimestamp(stat.st_mtime,timezone.utc)
                self.map_received = datetime.now(timezone.utc)
                self._stream_map_signature = self.map_grid.signature
        elif name == "cleanPath.bin.stream":
            path = decode_path(data)
            async with self.map_lock:
                grid = self.map_grid
                if grid is None or self._stream_map_signature != grid.signature:
                    return
                await self.hass.async_add_executor_job(self._store_stream_file,self.path_path,data)
                self.path_id,self.path_points = path["path_id"],path["points"]
                if not path["points"]:
                    self.position = self.position_updated = None
                    self.position_source = "empty_path"
                else:
                    # Full cleanPath files and maps in this authenticated
                    # stream have independent IDs (observed map 30161/path 15).
                    # Pair only with a map received in this stream session.
                    x,y = path["points"][-1]
                    x += grid.origin[0]; y += grid.origin[1]
                    if not 0 <= x < grid.width or not 0 <= y < grid.height:
                        raise ValueError("Streamed position outside current map")
                    self.position = {"x":x,"y":y,"angle":path["angle"],"map_id":grid.map_id}
                    self.position_updated = datetime.now(timezone.utc)
                    self.position_source = "local_p2p"
        else:
            # A navigation/planned route is not a measured robot position.
            return
        self.async_update_listeners()

    @property
    def position_fresh(self):
        return (self.map_active.is_set() and self.position is not None and self.position_updated is not None
                and self.position_source in ("local_path_push","local_p2p")
                and (datetime.now(timezone.utc)-self.position_updated).total_seconds()<=30)

    @property
    def current_area(self):
        if not self.position_fresh or self.map_grid is None:
            return None
        grid = self.map_grid
        x,y = self.position["x"],self.position["y"]
        if not 0<=x<grid.width or not 0<=y<grid.height:
            return None
        room_id = grid.cells[int(y)*grid.width+int(x)] >> 3
        for room in grid.rooms:
            if room["id"]==room_id: return room["name"]
        rx,ry = x-grid.origin[0],y-grid.origin[1]
        matching = []
        for name,profile in self.profiles.items():
            if profile["map_id"]!=grid.map_id or profile.get("map_signature")!=grid.signature:
                continue
            for zone in profile.get("zones",[]):
                xs,ys = [p[0] for p in zone],[p[1] for p in zone]
                if min(xs)<=rx<=max(xs) and min(ys)<=ry<=max(ys):
                    matching.append(((max(xs)-min(xs))*(max(ys)-min(ys)),name))
        return min(matching)[1] if matching else None
