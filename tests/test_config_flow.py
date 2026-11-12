"""Tests for the config flow."""

from __future__ import annotations

import inspect

import pytest

pytest.importorskip("homeassistant")
pytest.importorskip("voluptuous")
pytest.importorskip("google.genai")

from homeassistant import config_entries

from custom_components.gemini_live_assistant import config_flow


def test_config_flow_class_is_importable() -> None:
    """The config flow should be exposed as a Home Assistant ConfigFlow."""
    flow_class = config_flow.GeminiLiveAssistantConfigFlow

    assert issubclass(flow_class, config_entries.ConfigFlow)
    assert flow_class.VERSION == 1
    assert inspect.iscoroutinefunction(flow_class.async_step_user)


def test_options_flow_is_available() -> None:
    """The config flow should provide an options flow with an init step."""
    options_class = config_flow.GeminiLiveAssistantOptionsFlow

    assert callable(config_flow.GeminiLiveAssistantConfigFlow.async_get_options_flow)
    assert inspect.iscoroutinefunction(options_class.async_step_init)
