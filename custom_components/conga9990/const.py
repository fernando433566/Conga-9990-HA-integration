"""Integration constants and the data-point profile observed on this robot."""

import json
from pathlib import Path

from homeassistant.const import Platform

DOMAIN = "conga9990"
PLATFORMS = [Platform.VACUUM, Platform.SENSOR, Platform.BINARY_SENSOR,
             Platform.SWITCH, Platform.SELECT, Platform.NUMBER, Platform.BUTTON, Platform.IMAGE]
PROFILE = json.loads(Path(__file__).with_name("profile.json").read_text())
SCHEMA = {str(item["id"]): item for item in PROFILE["schema"]}
SETTING_SWITCHES = ("25", "27", "38", "39", "45", "46", "47", "50", "101", "104", "108")
SETTING_SELECTS = ("4", "10", "36", "41", "42", "44", "52", "53", "103", "105")
SETTING_NUMBERS = ("26", "37", "51")
ACTION_BUTTONS = ("11", "13", "18", "20", "22", "24", "49", "109", "142", "143", "144", "145")
CONSUMABLES = {"17": "Side brush", "19": "Main brush", "21": "Filter", "23": "Mop"}
NAMES = {
    "5": "Status", "6": "Cleaning time", "7": "Cleaned area", "8": "Battery",
    "10": "Water level", "11": "Locate", "13": "Reset map", "17": "Side brush remaining",
    "18": "Reset side brush", "19": "Main brush remaining", "20": "Reset main brush",
    "21": "Filter remaining", "22": "Reset filter", "23": "Mop remaining", "24": "Reset mop",
    "25": "Do not disturb", "26": "Volume", "27": "Resume cleaning", "28": "Fault flags",
    "29": "Total cleaned area", "30": "Total cleanings", "31": "Total cleaning time",
    "37": "Dust collection frequency", "38": "Dust collection", "40": "Mop status",
    "41": "Work mode", "44": "Carpet behavior", "45": "Carpet boost", "47": "Child lock",
    "49": "Self cleaning", "50": "Drying", "51": "Self cleaning interval",
    "52": "Self cleaning strength", "53": "Movement speed", "103": "Charging base type",
    "104": "Y mopping", "105": "Cleaning pattern", "108": "Sound", "109": "Quick mapping",
    "142": "Deep cleaning", "143": "Edge cleaning", "144": "Spiral cleaning", "145": "Square cleaning",
}


def name_for(dp_id: str) -> str:
    return NAMES.get(dp_id, SCHEMA[dp_id]["code"].replace("_", " ").capitalize())
