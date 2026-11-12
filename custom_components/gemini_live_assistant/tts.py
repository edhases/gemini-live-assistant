"""Text-to-speech platform using Gemini TTS."""

from __future__ import annotations

import io
import wave
from typing import Any, Literal

from google.genai.types import (
    GenerateContentConfig,
    PrebuiltVoiceConfig,
    SpeechConfig,
    VoiceConfig,
)
from homeassistant.components import tts
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_TTS_MODEL,
    CONF_TTS_VOICE,
    LOGGER,
    RECOMMENDED_TTS_MODEL,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Gemini TTS entity."""
    async_add_entities([GeminiTTSEntity(entry)])


def _pcm_to_wav(data: bytes, sample_rate: int = 24000) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(data)
    return buffer.getvalue()


class GeminiTTSEntity(tts.TextToSpeechEntity):
    """Gemini text-to-speech entity."""

    _attr_has_entity_name = False
    _attr_name = "Gemini TTS"

    def __init__(self, entry: ConfigEntry) -> None:
        self.entry = entry
        self._client = entry.runtime_data.client
        self._attr_unique_id = f"{entry.entry_id}_tts"

    @property
    def _model(self) -> str:
        options = {**self.entry.data, **self.entry.options}
        return options.get(CONF_TTS_MODEL, RECOMMENDED_TTS_MODEL)

    @property
    def _voice(self) -> str:
        options = {**self.entry.data, **self.entry.options}
        return options.get(CONF_TTS_VOICE, "Puck")

    @property
    def default_language(self) -> str:
        return "en"

    @property
    def supported_languages(self) -> list[str] | Literal["*"]:
        return "*"

    async def async_get_tts_audio(
        self,
        message: str,
        language: str,
        options: dict[str, Any],
    ) -> tts.TtsAudioType:
        voice = options.get("voice") or self._voice
        config = GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=SpeechConfig(
                voice_config=VoiceConfig(
                    prebuilt_voice_config=PrebuiltVoiceConfig(voice_name=voice)
                )
            ),
        )
        try:
            response = await self._client.aio.models.generate_content(
                model=self._model,
                contents=message,
                config=config,
            )
        except Exception as err:
            LOGGER.error("Gemini TTS request failed: %s", err)
            raise HomeAssistantError("Gemini TTS request failed") from err

        try:
            candidate = response.candidates[0]
            inline = candidate.content.parts[0].inline_data
            pcm = inline.data
        except (IndexError, AttributeError, TypeError) as err:
            raise HomeAssistantError("Gemini TTS returned no audio") from err
        if not pcm:
            raise HomeAssistantError("Gemini TTS returned empty audio")

        return ("wav", _pcm_to_wav(pcm))
