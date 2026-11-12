"""Tests for the integration constants."""

from __future__ import annotations

import pytest

pytest.importorskip("homeassistant")

from custom_components.gemini_live_assistant import const


@pytest.mark.parametrize(
    ("models", "name"),
    [
        (const.CHAT_MODELS, "CHAT_MODELS"),
        (const.TTS_MODELS, "TTS_MODELS"),
        (const.LIVE_MODELS, "LIVE_MODELS"),
    ],
)
def test_model_lists_are_not_empty(models: list[str], name: str) -> None:
    """Every model list should expose at least one model."""
    assert models, f"{name} must not be empty"
    assert all(isinstance(model, str) and model for model in models)


def test_voices_are_not_empty() -> None:
    """At least one voice should be available."""
    assert const.VOICES
    assert all(isinstance(voice, str) and voice for voice in const.VOICES)


@pytest.mark.parametrize(
    ("recommended", "models"),
    [
        (const.RECOMMENDED_CHAT_MODEL, const.CHAT_MODELS),
        (const.RECOMMENDED_STT_MODEL, const.CHAT_MODELS),
        (const.RECOMMENDED_TTS_MODEL, const.TTS_MODELS),
        (const.RECOMMENDED_LIVE_MODEL, const.LIVE_MODELS),
    ],
)
def test_recommended_models_are_in_their_lists(recommended: str, models: list[str]) -> None:
    """Recommended defaults must be selectable from the corresponding list."""
    assert recommended in models


def test_recommended_conversation_options_contain_required_keys() -> None:
    """The default conversation options need the prompt, model and LLM API."""
    options = const.RECOMMENDED_CONVERSATION_OPTIONS

    assert const.CONF_CHAT_MODEL in options
    assert const.CONF_PROMPT in options
    assert const.CONF_LLM_HASS_API in options
    assert options[const.CONF_CHAT_MODEL] == const.RECOMMENDED_CHAT_MODEL
    assert options[const.CONF_PROMPT]
    assert options[const.CONF_LLM_HASS_API]
