"""Assist profile actions routed through HA's authenticated entity services."""
import voluptuous as vol

from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry, intent

from .const import DOMAIN


def vacuum_target(hass):
    entries = [entry for entry in hass.config_entries.async_entries(DOMAIN)
               if entry.state is ConfigEntryState.LOADED]
    if len(entries) != 1:
        raise intent.IntentHandleError("No hay una única Conga disponible")
    registry = entity_registry.async_get(hass)
    vacuums = [entry.entity_id for entry in registry.entities.values()
               if entry.config_entry_id == entries[0].entry_id and entry.domain == "vacuum"
               and entry.platform == DOMAIN and not entry.disabled_by]
    if len(vacuums) != 1:
        raise intent.IntentHandleError("No se encuentra la entidad de la Conga")
    return vacuums[0]


class CongaRunProfileIntent(intent.IntentHandler):
    intent_type = "CongaRunProfile"
    slot_schema = {vol.Required("conga_profile"): str}

    async def async_handle(self, intent_obj):
        slots = self.async_validate_slots(intent_obj.slots)
        name = slots["conga_profile"]["value"]
        hass = intent_obj.hass
        target = vacuum_target(hass)
        try:
            await hass.services.async_call(DOMAIN,"run_profile",{"entity_id":target,"name":name},
                                           blocking=True,context=intent_obj.context)
        except HomeAssistantError as exc:
            raise intent.IntentHandleError(str(exc)) from exc
        response = intent_obj.create_response()
        response.async_set_speech(f"He enviado el perfil {name} a la Conga.")
        return response


class CongaManualMoveIntent(intent.IntentHandler):
    intent_type = "CongaManualMove"
    slot_schema = {vol.Required("conga_direction"): vol.In(("forward","backward","turn_left","turn_right","stop"))}

    async def async_handle(self, intent_obj):
        direction = self.async_validate_slots(intent_obj.slots)["conga_direction"]["value"]
        target = vacuum_target(intent_obj.hass)
        data = {"entity_id":target}
        if direction != "stop": data.update(direction=direction,duration=.3)
        try:
            await intent_obj.hass.services.async_call(DOMAIN,"manual_stop" if direction=="stop" else "manual_move",
                                                       data,blocking=True,context=intent_obj.context)
        except HomeAssistantError as exc:
            raise intent.IntentHandleError(str(exc)) from exc
        response = intent_obj.create_response()
        response.async_set_speech("Orden de movimiento enviada.")
        return response


def async_setup_intents(hass):
    intent.async_register(hass,CongaRunProfileIntent())
    intent.async_register(hass,CongaManualMoveIntent())
