"""Config flow for Gemini Live Assistant."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from google.genai import Client
from google.genai.errors import APIError, ClientError
from homeassistant import config_entries
from homeassistant.const import CONF_LLM_HASS_API, CONF_PROMPT
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import llm
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import (
    CHAT_MODELS,
    CONF_API_KEY,
    CONF_CHAT_MODEL,
    CONF_ENABLE_LIVE,
    CONF_LIVE_MODEL,
    CONF_LIVE_VOICE,
    CONF_MAX_TOKENS,
    CONF_STT_MODEL,
    CONF_TEMPERATURE,
    CONF_TTS_MODEL,
    CONF_TTS_VOICE,
    DOMAIN,
    LIVE_MODELS,
    RECOMMENDED_CHAT_MODEL,
    RECOMMENDED_CONVERSATION_OPTIONS,
    RECOMMENDED_LIVE_MODEL,
    RECOMMENDED_MAX_TOKENS,
    RECOMMENDED_STT_MODEL,
    RECOMMENDED_TEMPERATURE,
    RECOMMENDED_TTS_MODEL,
    TTS_MODELS,
    VOICES,
)

_LOGGER = logging.getLogger(__name__)


def _model_selector(models: list[str]) -> SelectSelector:
    return SelectSelector(
        SelectSelectorConfig(
            options=[SelectOptionDict(value=m, label=m.split("/")[-1]) for m in models],
            mode=SelectSelectorMode.DROPDOWN,
            custom_value=True,
        )
    )


def _voice_selector() -> SelectSelector:
    return SelectSelector(SelectSelectorConfig(options=VOICES, mode=SelectSelectorMode.DROPDOWN))


class GeminiLiveAssistantConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Gemini Live Assistant."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            api_key = user_input[CONF_API_KEY].strip()
            try:
                client = Client(api_key=api_key)
                await self.hass.async_add_executor_job(
                    lambda: list(client.models.list(config={"page_size": 1}))
                )
            except (APIError, ClientError, ValueError) as err:
                _LOGGER.debug("API key validation failed: %s", err)
                errors["base"] = "invalid_auth"
            except Exception:
                _LOGGER.exception("Unexpected error validating Gemini API key")
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(api_key[-8:])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title="Gemini Live Assistant",
                    data={CONF_API_KEY: api_key},
                    options=RECOMMENDED_CONVERSATION_OPTIONS,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_API_KEY): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    )
                }
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> GeminiLiveAssistantOptionsFlow:
        return GeminiLiveAssistantOptionsFlow(config_entry)


class GeminiLiveAssistantOptionsFlow(config_entries.OptionsFlow):
    """Options for the Gemini conversation agent."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self.config_entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        options = {**self.config_entry.data, **self.config_entry.options}
        llm_apis = [
            SelectOptionDict(value=api.id, label=api.name) for api in llm.async_get_apis(self.hass)
        ]
        selected_apis = options.get(CONF_LLM_HASS_API) or [llm.LLM_API_ASSIST]

        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_CHAT_MODEL,
                    default=options.get(CONF_CHAT_MODEL, RECOMMENDED_CHAT_MODEL),
                ): _model_selector(CHAT_MODELS),
                vol.Optional(
                    CONF_PROMPT,
                    default=options.get(CONF_PROMPT, llm.DEFAULT_INSTRUCTIONS_PROMPT),
                ): TextSelector(TextSelectorConfig(multiline=True)),
                vol.Optional(
                    CONF_LLM_HASS_API,
                    default=selected_apis,
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=llm_apis,
                        multiple=True,
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Optional(
                    CONF_TEMPERATURE,
                    default=options.get(CONF_TEMPERATURE, RECOMMENDED_TEMPERATURE),
                ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=2.0)),
                vol.Optional(
                    CONF_MAX_TOKENS,
                    default=options.get(CONF_MAX_TOKENS, RECOMMENDED_MAX_TOKENS),
                ): vol.All(vol.Coerce(int), vol.Range(min=64, max=32000)),
                vol.Optional(
                    CONF_ENABLE_LIVE,
                    default=options.get(CONF_ENABLE_LIVE, False),
                ): bool,
                vol.Optional(
                    CONF_LIVE_MODEL,
                    default=options.get(CONF_LIVE_MODEL, RECOMMENDED_LIVE_MODEL),
                ): _model_selector(LIVE_MODELS),
                vol.Optional(
                    CONF_LIVE_VOICE,
                    default=options.get(CONF_LIVE_VOICE, "Puck"),
                ): _voice_selector(),
                vol.Optional(
                    CONF_STT_MODEL,
                    default=options.get(CONF_STT_MODEL, RECOMMENDED_STT_MODEL),
                ): _model_selector(CHAT_MODELS),
                vol.Optional(
                    CONF_TTS_MODEL,
                    default=options.get(CONF_TTS_MODEL, RECOMMENDED_TTS_MODEL),
                ): _model_selector(TTS_MODELS),
                vol.Optional(
                    CONF_TTS_VOICE,
                    default=options.get(CONF_TTS_VOICE, "Puck"),
                ): _voice_selector(),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
