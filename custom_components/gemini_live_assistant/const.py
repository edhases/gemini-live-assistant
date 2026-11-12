"""Constants for the Gemini Live Assistant integration."""

from __future__ import annotations

import logging

from homeassistant.const import CONF_LLM_HASS_API, CONF_PROMPT
from homeassistant.helpers import llm

LOGGER = logging.getLogger(__package__)

DOMAIN = "gemini_live_assistant"
DEFAULT_TITLE = "Gemini Live Assistant"

CONF_API_KEY = "api_key"
CONF_CHAT_MODEL = "chat_model"
CONF_STT_MODEL = "stt_model"
CONF_TTS_MODEL = "tts_model"
CONF_TTS_VOICE = "tts_voice"
CONF_TEMPERATURE = "temperature"
CONF_MAX_TOKENS = "max_tokens"
CONF_ENABLE_LIVE = "enable_live"
CONF_LIVE_MODEL = "live_model"
CONF_LIVE_VOICE = "live_voice"

# Text model used for the conversation agent and for audio transcription.
RECOMMENDED_CHAT_MODEL = "models/gemini-3.8-flash"
RECOMMENDED_STT_MODEL = "models/gemini-3.5-transcribe"
RECOMMENDED_TTS_MODEL = "models/gemini-3.8-flash-tts"
RECOMMENDED_LIVE_MODEL = "models/gemini-3.8-live"

# Curated fallbacks. The options flow also queries the live model list from
# the Gemini API and always allows typing a custom model name.
CHAT_MODELS = [
    "models/gemini-3.8-flash",
    "models/gemini-3.7-flash",
    "models/gemini-3.6-flash",
    "models/gemini-3.5-flash",
    "models/gemini-3.5-flash-lite",
    "models/gemini-3.1-flash-lite",
    "models/gemini-3.1-pro-preview",
    "models/gemini-2.5-flash",
    "models/gemini-2.5-pro",
    "models/gemini-4-argon",
    "models/gemini-4-carbon",
    "models/gemini-flash-latest",
    "models/gemini-pro-latest",
]

STT_MODELS = [
    "models/gemini-3.5-transcribe",
    "models/gemini-3.8-flash",
    "models/gemini-3.1-flash-lite",
    "models/gemini-2.5-flash",
]

TTS_MODELS = [
    "models/gemini-3.8-flash-tts",
    "models/gemini-3.8-flash-lite-tts",
    "models/gemini-3.1-flash-tts-preview",
    "models/gemini-2.5-flash-preview-tts",
]

LIVE_MODELS = [
    "models/gemini-3.8-live",
    "models/gemini-3.8-live-extended-thinking",
    "models/gemini-3.1-flash-live-preview",
    "models/gemini-2.5-flash-native-audio-preview-12-2025",
]

VOICES = [
    "Puck",
    "Charon",
    "Kore",
    "Fenrir",
    "Aoede",
    "Leda",
    "Orus",
    "Zephyr",
]

RECOMMENDED_TEMPERATURE = 1.0
RECOMMENDED_MAX_TOKENS = 3000
DEFAULT_STT_PROMPT = "Transcribe the attached audio"

RECOMMENDED_PROMPT = (
    "You are a helpful, concise smart home assistant. Use the available tools to "
    "control devices and answer questions.\n"
    "When the user asks about a specific device, area, or system (for example the "
    "inverter), call GetLiveContext with the matching name, area, or domain filter "
    "and use only that data. Do not request the whole home unless the user "
    "explicitly asks for a whole-home overview.\n"
    "Prefer filtering by area or domain over requesting everything. Keep answers "
    "short, natural, and in the user's language."
)

RECOMMENDED_CONVERSATION_OPTIONS = {
    CONF_PROMPT: RECOMMENDED_PROMPT,
    CONF_LLM_HASS_API: [llm.LLM_API_ASSIST],
    CONF_CHAT_MODEL: RECOMMENDED_CHAT_MODEL,
    CONF_TEMPERATURE: RECOMMENDED_TEMPERATURE,
    CONF_MAX_TOKENS: RECOMMENDED_MAX_TOKENS,
    CONF_ENABLE_LIVE: False,
    CONF_LIVE_MODEL: RECOMMENDED_LIVE_MODEL,
    CONF_LIVE_VOICE: "Puck",
}

MAX_TOOL_ITERATIONS = 10
TIMEOUT_MILLIS = 15000
