"""Async client for the Gemini Live API (BidiGenerateContent).

This module is a functional building block for a realtime voice assistant.
Home Assistant's standard conversation entity is text based; this client can
be used by a future custom audio pipeline/frontend to stream microphone audio
to Gemini Live and play the returned audio back.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

from google.genai import Client, types

from .const import LOGGER


@dataclass(slots=True)
class LiveConfig:
    """Configuration for a Gemini Live session."""

    model: str
    voice: str = "Puck"
    system_instruction: str = ""
    tools: list[types.Tool] = field(default_factory=list)
    language_code: str | None = None
    transcribe: bool = True


@dataclass(slots=True)
class LiveToolCall:
    """A function call requested by the model."""

    name: str
    call_id: str | None
    arguments: dict[str, Any]


@dataclass(slots=True)
class LiveToolResponse:
    """The local result of a tool call."""

    name: str
    call_id: str | None
    response: Any


@dataclass(slots=True)
class LiveEvent:
    """One normalized event from a Live session."""

    audio: bytes | None = None
    text: str | None = None
    input_transcript: str | None = None
    output_transcript: str | None = None
    tool_calls: list[LiveToolCall] = field(default_factory=list)
    turn_complete: bool = False
    interrupted: bool = False


def _build_config(config: LiveConfig) -> types.LiveConnectConfig:
    speech_config = types.SpeechConfig(
        voice_config=types.VoiceConfig(
            prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=config.voice)
        ),
        language_code=config.language_code,
    )
    return types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        system_instruction=config.system_instruction or None,
        speech_config=speech_config,
        tools=config.tools or None,
        input_audio_transcription=(types.AudioTranscriptionConfig() if config.transcribe else None),
        output_audio_transcription=(
            types.AudioTranscriptionConfig() if config.transcribe else None
        ),
    )


def _to_event(message: types.LiveServerMessage) -> LiveEvent:
    event = LiveEvent()
    if server_content := message.server_content:
        if model_turn := server_content.model_turn:
            for part in model_turn.parts or []:
                if part.inline_data and part.inline_data.data:
                    event.audio = part.inline_data.data
                if part.text and not part.thought:
                    event.text = part.text
        if input_tx := server_content.input_transcription:
            event.input_transcript = input_tx.text
        if output_tx := server_content.output_transcription:
            event.output_transcript = output_tx.text
        event.turn_complete = bool(server_content.turn_complete)
        event.interrupted = bool(server_content.interrupted)

    if tool_call := message.tool_call:
        for call in tool_call.function_calls or []:
            event.tool_calls.append(
                LiveToolCall(
                    name=call.name or "",
                    call_id=call.id,
                    arguments=dict(call.args or {}),
                )
            )
    return event


class GeminiLiveSession:
    """Wrapper around a google-genai Live session."""

    def __init__(self, session: types.Any) -> None:
        self._session = session

    async def send_text(self, text: str) -> None:
        await self._session.send_client_content(
            turns=types.Content(role="user", parts=[types.Part.from_text(text=text)]),
            turn_complete=True,
        )

    async def send_audio(self, pcm: bytes, mime_type: str = "audio/pcm;rate=16000") -> None:
        await self._session.send_realtime_input(audio=types.Blob(data=pcm, mime_type=mime_type))

    async def end_audio(self) -> None:
        await self._session.send_realtime_input(audio_stream_end=True)

    async def send_tool_responses(self, responses: Sequence[LiveToolResponse]) -> None:
        await self._session.send_tool_response(
            function_responses=[
                types.FunctionResponse(
                    name=item.name,
                    id=item.call_id,
                    response={"result": item.response},
                )
                for item in responses
            ]
        )

    async def receive(self) -> AsyncIterator[LiveEvent]:
        async for message in self._session.receive():
            yield _to_event(message)

    async def close(self) -> None:
        await self._session.close()


@asynccontextmanager
async def connect(client: Client, config: LiveConfig) -> AsyncIterator[GeminiLiveSession]:
    """Open a Gemini Live session."""
    LOGGER.debug("Connecting to Gemini Live model %s", config.model)
    async with client.aio.live.connect(model=config.model, config=_build_config(config)) as session:
        yield GeminiLiveSession(session)
