"""Gemini Live Assistant integration setup."""

from __future__ import annotations

from dataclasses import dataclass

from google.genai import Client
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_API_KEY

PLATFORMS = ["conversation", "stt", "tts"]


@dataclass
class GeminiRuntimeData:
    """Runtime objects for a config entry."""

    client: Client


GeminiConfigEntry = ConfigEntry[GeminiRuntimeData]


async def async_setup_entry(hass: HomeAssistant, entry: GeminiConfigEntry) -> bool:
    """Set up Gemini Live Assistant from a config entry."""
    client = await hass.async_add_executor_job(lambda: Client(api_key=entry.data[CONF_API_KEY]))
    entry.runtime_data = GeminiRuntimeData(client=client)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: GeminiConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
