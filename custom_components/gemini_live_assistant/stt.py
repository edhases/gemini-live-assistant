"""Speech-to-text platform using Gemini audio understanding."""

from __future__ import annotations

import io
import wave
from typing import Literal

from google.genai.types import GenerateContentConfig, Part
from homeassistant.components import stt
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_STT_MODEL,
    DEFAULT_STT_PROMPT,
    LOGGER,
    RECOMMENDED_STT_MODEL,
)

_MIME_BY_FORMAT = {
    stt.AudioFormats.WAV: "audio/wav",
    stt.AudioFormats.OGG: "audio/ogg",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Gemini STT entity."""
    async_add_entities([GeminiSTTEntity(entry)])


def _pcm_to_wav(data: bytes, metadata: stt.SpeechMetadata) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(metadata.channels)
        wav.setsampwidth(metadata.bit_rate // 8)
        wav.setframerate(metadata.sample_rate)
        wav.writeframes(data)
    return buffer.getvalue()


class GeminiSTTEntity(stt.SpeechToTextEntity):
    """Gemini speech-to-text entity."""

    _attr_has_entity_name = False
    _attr_name = "Gemini STT"

    def __init__(self, entry: ConfigEntry) -> None:
        self.entry = entry
        self._client = entry.runtime_data.client
        self._attr_unique_id = f"{entry.entry_id}_stt"
        options = {**entry.data, **entry.options}
        self._model = options.get(CONF_STT_MODEL, RECOMMENDED_STT_MODEL)

    @property
    def supported_languages(self) -> list[str] | Literal["*"]:
        return "*"

    @property
    def supported_formats(self) -> list[stt.AudioFormats]:
        return [stt.AudioFormats.WAV, stt.AudioFormats.OGG]

    @property
    def supported_codecs(self) -> list[stt.AudioCodecs]:
        return [stt.AudioCodecs.PCM, stt.AudioCodecs.OPUS]

    @property
    def supported_bit_rates(self) -> list[stt.AudioBitRates]:
        return [stt.AudioBitRates.BITRATE_16]

    @property
    def supported_sample_rates(self) -> list[stt.AudioSampleRates]:
        return [
            stt.AudioSampleRates.SAMPLERATE_16000,
            stt.AudioSampleRates.SAMPLERATE_22000,
            stt.AudioSampleRates.SAMPLERATE_32000,
            stt.AudioSampleRates.SAMPLERATE_44100,
            stt.AudioSampleRates.SAMPLERATE_48000,
        ]

    @property
    def supported_channels(self) -> list[stt.AudioChannels]:
        return [stt.AudioChannels.CHANNEL_MONO]

    async def async_process_audio_stream(
        self, metadata: stt.SpeechMetadata, stream: stt.AudioStream
    ) -> stt.SpeechToTextResult:
        audio = bytearray()
        async for chunk in stream:
            audio.extend(chunk)

        data = bytes(audio)
        mime = _MIME_BY_FORMAT.get(metadata.format)
        if mime is None:
            if metadata.codec == stt.AudioCodecs.PCM:
                data = _pcm_to_wav(data, metadata)
                mime = "audio/wav"
            else:
                mime = "audio/wav"

        try:
            response = await self._client.aio.models.generate_content(
                model=self._model,
                contents=[
                    Part.from_bytes(data=data, mime_type=mime),
                    DEFAULT_STT_PROMPT,
                ],
                config=GenerateContentConfig(temperature=0.0),
            )
        except Exception as err:
            LOGGER.error("Gemini STT request failed: %s", err)
            raise HomeAssistantError("Gemini STT request failed") from err

        text = (response.text or "").strip()
        return stt.SpeechResult(
            text=text,
            language=metadata.language,
            result=stt.SpeechResultState.SUCCESS,
        )
