"""Tests for the Gemini Live client helpers."""

from __future__ import annotations

import pytest

pytest.importorskip("homeassistant")
types = pytest.importorskip("google.genai.types")

from custom_components.gemini_live_assistant.live import (  # noqa: E402
    LiveConfig,
    _build_config,
    _to_event,
)

MODEL = "models/gemini-3.1-flash-live-preview"


def test_build_config_uses_audio_and_voice() -> None:
    """The Live connection should request audio output with the configured voice."""
    config = _build_config(
        LiveConfig(
            model=MODEL,
            voice="Kore",
            system_instruction="You are a helpful assistant.",
        )
    )

    assert config.response_modalities == ["AUDIO"]
    assert config.system_instruction == "You are a helpful assistant."
    assert config.speech_config is not None
    assert config.speech_config.voice_config is not None
    assert config.speech_config.voice_config.prebuilt_voice_config is not None
    assert config.speech_config.voice_config.prebuilt_voice_config.voice_name == "Kore"
    assert config.input_audio_transcription is not None
    assert config.output_audio_transcription is not None


def test_build_config_without_transcription() -> None:
    """Transcription configs should be omitted when disabled."""
    config = _build_config(LiveConfig(model=MODEL, transcribe=False))

    assert config.response_modalities == ["AUDIO"]
    assert config.input_audio_transcription is None
    assert config.output_audio_transcription is None


def test_to_event_maps_server_message() -> None:
    """A Live server message should be converted into a normalized event."""
    audio = b"\x01\x02\x03\x04"
    message = types.LiveServerMessage(
        server_content=types.LiveServerContent(
            model_turn=types.Content(
                role="model",
                parts=[
                    types.Part(text="Hello from Gemini"),
                    types.Part(
                        inline_data=types.Blob(
                            data=audio,
                            mime_type="audio/pcm;rate=24000",
                        )
                    ),
                ],
            ),
            input_transcription=types.Transcription(text="Turn on the kitchen light"),
            output_transcription=types.Transcription(text="Hello from Gemini"),
            turn_complete=True,
        ),
        tool_call=types.LiveServerToolCall(
            function_calls=[
                types.FunctionCall(
                    name="HassTurnOn",
                    id="call-123",
                    args={"name": "kitchen light"},
                )
            ]
        ),
    )

    event = _to_event(message)

    assert event.audio == audio
    assert event.text == "Hello from Gemini"
    assert event.input_transcript == "Turn on the kitchen light"
    assert event.output_transcript == "Hello from Gemini"
    assert event.turn_complete is True
    assert event.interrupted is False
    assert len(event.tool_calls) == 1

    tool_call = event.tool_calls[0]
    assert tool_call.name == "HassTurnOn"
    assert tool_call.call_id == "call-123"
    assert tool_call.arguments == {"name": "kitchen light"}


def test_to_event_ignores_thought_text() -> None:
    """Thought parts must not be exposed as spoken text."""
    message = types.LiveServerMessage(
        server_content=types.LiveServerContent(
            model_turn=types.Content(
                role="model",
                parts=[types.Part(text="internal reasoning", thought=True)],
            )
        )
    )

    event = _to_event(message)

    assert event.text is None
    assert event.audio is None


def test_to_event_with_empty_message() -> None:
    """An empty message should produce a default event."""
    event = _to_event(types.LiveServerMessage())

    assert event.audio is None
    assert event.text is None
    assert event.input_transcript is None
    assert event.output_transcript is None
    assert event.tool_calls == []
    assert event.turn_complete is False
    assert event.interrupted is False
