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
        wav.setnchannels(int(metadata.channels))
        wav.setsampwidth(int(metadata.bit_rate) // 8)
        wav.setframerate(int(metadata.sample_rate))
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

    @property
    def _model(self) -> str:
        options = {**self.entry.data, **self.entry.options}
        return options.get(CONF_STT_MODEL, RECOMMENDED_STT_MODEL)

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
    ) -> stt.SpeechResult:
        audio = bytearray()
        async for chunk in stream:
            audio.extend(chunk)

        data = bytes(audio)
        if metadata.codec == stt.AudioCodecs.PCM:
            # The Assist pipeline streams raw PCM, so always add a WAV header
            # even when the format is advertised as WAV.
            data = _pcm_to_wav(data, metadata)
            mime = "audio/wav"
        else:
            mime = _MIME_BY_FORMAT.get(metadata.format, "audio/ogg")

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

        text = ""
        if response.candidates and response.candidates[0].content:
            for part in response.candidates[0].content.parts or []:
                if part.audio_transcription and part.audio_transcription.text:
                    text += part.audio_transcription.text
        if not text:
            text = (response.text or "").strip()

        return stt.SpeechResult(
            text=text,
            language=metadata.language,
            result=stt.SpeechResultState.SUCCESS,
        )
