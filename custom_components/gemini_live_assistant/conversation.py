"""Conversation platform for Gemini Live Assistant."""

from __future__ import annotations

import dataclasses
from typing import Literal

from homeassistant.components import conversation
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_LLM_HASS_API, CONF_PROMPT, MATCH_ALL
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, LOGGER
from .entity import GeminiLLMBaseEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Gemini conversation agent."""
    async_add_entities([GeminiConversationEntity(entry)])


class GeminiConversationEntity(
    conversation.ConversationEntity,
    conversation.AbstractConversationAgent,
    GeminiLLMBaseEntity,
):
    """Gemini conversation agent with Home Assistant control."""

    # The HA Assist chat frontend renders streamed tool-call deltas as
    # "[object Object]" in some versions. Returning the final response only is
    # safer and still shows the answer promptly.
    _attr_supports_streaming = False

    def __init__(self, entry: ConfigEntry) -> None:
        options = {**entry.data, **entry.options}
        super().__init__(
            entry,
            entry.runtime_data.client,
            name=entry.title,
            unique_id=f"{entry.entry_id}_conversation",
            options=options,
        )
        if options.get(CONF_LLM_HASS_API):
            self._attr_supported_features = conversation.ConversationEntityFeature.CONTROL

    @property
    def supported_languages(self) -> list[str] | Literal["*"]:
        return MATCH_ALL

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        conversation.async_set_agent(self.hass, self.entry, self)

    async def async_will_remove_from_hass(self) -> None:
        conversation.async_unset_agent(self.hass, self.entry)
        await super().async_will_remove_from_hass()

    async def _async_handle_message(
        self,
        user_input: conversation.ConversationInput,
        chat_log: conversation.ChatLog,
    ) -> conversation.ConversationResult:
        options = {**self.entry.data, **self.entry.options}
        try:
            await chat_log.async_provide_llm_data(
                user_input.as_llm_context(DOMAIN),
                options.get(CONF_LLM_HASS_API),
                options.get(CONF_PROMPT),
                user_input.extra_system_prompt,
            )
        except conversation.ConverseError as err:
            return err.as_conversation_result()

        await self._async_handle_chat_log(chat_log)

        # Defensive: the frontend expects a plain string as the assistant
        # speech. Coerce non-string content so it never renders as
        # "[object Object]".
        if chat_log.content:
            last = chat_log.content[-1]
            if (
                isinstance(last, conversation.AssistantContent)
                and last.content is not None
                and not isinstance(last.content, str)
            ):
                LOGGER.warning("Gemini returned non-string assistant content: %r", last.content)
                chat_log.content[-1] = dataclasses.replace(last, content=str(last.content))

        return conversation.async_get_result_from_chat_log(user_input, chat_log)
