"""Shared Gemini conversation/LLM handling."""

from __future__ import annotations

import codecs
from collections.abc import AsyncGenerator, Callable
from typing import Any, cast

import probatio
from google.genai import Client
from google.genai import types as genai_types
from google.genai.errors import APIError, ClientError
from google.genai.types import (
    AutomaticFunctionCallingConfig,
    Content,
    ContentDict,
    FunctionDeclaration,
    GenerateContentConfig,
    Part,
    Schema,
    Tool,
    ToolListUnion,
)
from homeassistant.components import conversation
from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import llm
from homeassistant.helpers.entity import Entity

from .const import (
    CONF_CHAT_MODEL,
    CONF_LIVE_MODEL,
    CONF_LIVE_VOICE,
    CONF_MAX_TOKENS,
    CONF_TEMPERATURE,
    DOMAIN,
    LOGGER,
    MAX_TOOL_ITERATIONS,
    RECOMMENDED_CHAT_MODEL,
    RECOMMENDED_LIVE_MODEL,
    RECOMMENDED_MAX_TOKENS,
    RECOMMENDED_TEMPERATURE,
)

SUPPORTED_SCHEMA_KEYS = {
    "type",
    "format",
    "description",
    "nullable",
    "enum",
    "max_items",
    "min_items",
    "properties",
    "required",
    "items",
}

ERROR_GETTING_RESPONSE = "Sorry, I had a problem getting a response from Gemini."


def _camel_to_snake(name: str) -> str:
    return "".join(["_" + c.lower() if c.isupper() else c for c in name]).lstrip("_")


def _format_schema(schema: dict[str, Any]) -> Schema:
    if subschemas := schema.get("allOf"):
        for subschema in subschemas:
            if "type" in subschema:
                return _format_schema(subschema)
        return _format_schema(subschemas[0])

    result: dict[str, Any] = {}
    for key, val in schema.items():
        key = _camel_to_snake(key)
        if key not in SUPPORTED_SCHEMA_KEYS:
            continue
        if key == "type":
            val = val.upper()
        elif key == "format":
            if schema.get("type") == "string" and val not in ("enum", "date-time"):
                continue
            if schema.get("type") == "number" and val not in ("float", "double"):
                continue
            if schema.get("type") == "integer" and val not in ("int32", "int64"):
                continue
            if schema.get("type") not in ("string", "number", "integer"):
                continue
        elif key == "items":
            val = _format_schema(val)
        elif key == "properties":
            val = {k: _format_schema(v) for k, v in val.items()}
        result[key] = val

    if result.get("enum") and result.get("type") != "STRING":
        result["type"] = "STRING"
        result["enum"] = [str(item) for item in result["enum"]]

    if result.get("type") == "OBJECT" and not result.get("properties"):
        result["properties"] = {"json": {"type": "STRING"}}
        result["required"] = []
    return cast(Schema, result)


def _format_tool(tool: llm.Tool, custom_serializer: Callable[[Any], Any] | None) -> Tool:
    if tool.parameters.schema:
        parameters = _format_schema(
            probatio.to_openapi(tool.parameters, custom_serializer=custom_serializer)
        )
    else:
        parameters = None
    return Tool(
        function_declarations=[
            FunctionDeclaration(
                name=tool.name,
                description=tool.description,
                parameters=parameters,
            )
        ]
    )


def _escape_decode(value: Any) -> Any:
    if isinstance(value, str):
        return codecs.escape_decode(bytes(value, "utf-8"))[0].decode("utf-8")
    if isinstance(value, list):
        return [_escape_decode(item) for item in value]
    if isinstance(value, dict):
        return {k: _escape_decode(v) for k, v in value.items()}
    return value


def _validate_tool_results(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, list):
        return [_validate_tool_results(item) for item in value]
    if isinstance(value, dict):
        return {k: _validate_tool_results(v) for k, v in value.items()}
    return str(value)


def _create_google_tool_response_parts(
    parts: list[conversation.ToolResultContent],
) -> list[Part]:
    return [
        Part.from_function_response(
            name=tool_result.tool_name,
            response=_validate_tool_results(
                {"data": tool_result.result.data, "error": tool_result.result.error}
            ),
        )
        for tool_result in parts
    ]


def _convert_content(
    content: (
        conversation.UserContent | conversation.AssistantContent | conversation.SystemContent
    ),
) -> Content:
    if content.role != "assistant":
        return Content(
            role=content.role,
            parts=[Part.from_text(text=content.content or "")],
        )
    assert isinstance(content, conversation.AssistantContent)
    parts: list[Part] = []
    if content.content:
        parts.append(Part.from_text(text=content.content))
    for tool_call in content.tool_calls or []:
        parts.append(
            Part.from_function_call(
                name=tool_call.tool_name,
                args=_escape_decode(tool_call.tool_args),
            )
        )
    return Content(role="model", parts=parts or [Part.from_text(text=" ")])


async def _transform_stream(
    result: Any,
) -> AsyncGenerator[conversation.AssistantContentDeltaDict]:
    new_message = True
    async for response in result:
        if not response.candidates:
            continue
        candidate = response.candidates[0]
        response_parts = (
            candidate.content.parts
            if candidate.content is not None and candidate.content.parts is not None
            else []
        )
        if new_message:
            yield {"role": "assistant"}
            new_message = False
        for part in response_parts:
            chunk: conversation.AssistantContentDeltaDict = {}
            if part.text and not part.thought:
                chunk["content"] = part.text
            if part.function_call:
                tool_call = part.function_call
                chunk["tool_calls"] = [
                    llm.ToolInput(
                        tool_name=tool_call.name or "",
                        tool_args=_escape_decode(tool_call.args),
                    )
                ]
            if chunk:
                yield chunk


class GeminiLLMBaseEntity(Entity):
    """Base entity that runs a Gemini chat with Home Assistant tools."""

    def __init__(
        self,
        entry: ConfigEntry,
        client: Client,
        unique_id: str,
        options: dict[str, Any] | None = None,
    ) -> None:
        self.entry = entry
        self._client = client
        self._attr_unique_id = unique_id
        self.options = dict(options or {})
        self._attr_device_info = dr.DeviceInfo(
            identifiers={(DOMAIN, unique_id)},
            translation_key="gemini_live_assistant",
            manufacturer="Google",
            model=self.options.get(CONF_CHAT_MODEL, RECOMMENDED_CHAT_MODEL).split("/")[-1],
            entry_type=dr.DeviceEntryType.SERVICE,
        )

    def _create_config(self) -> GenerateContentConfig:
        return GenerateContentConfig(
            temperature=self.options.get(CONF_TEMPERATURE, RECOMMENDED_TEMPERATURE),
            max_output_tokens=self.options.get(CONF_MAX_TOKENS, RECOMMENDED_MAX_TOKENS),
            automatic_function_calling=AutomaticFunctionCallingConfig(
                disable=True, maximum_remote_calls=None
            ),
        )

    async def _async_handle_chat_log(
        self,
        chat_log: conversation.ChatLog,
        max_iterations: int = MAX_TOOL_ITERATIONS,
    ) -> None:
        """Generate an answer for the chat log, including tool calls."""
        tools: ToolListUnion | None = None
        if chat_log.llm_api:
            tools = [
                _format_tool(tool, chat_log.llm_api.custom_serializer)
                for tool in chat_log.llm_api.tools
            ]

        prompt_content = cast(conversation.SystemContent, chat_log.content[0])
        if not prompt_content.content:
            raise HomeAssistantError("Invalid prompt content")

        messages: list[Content | ContentDict] = []
        tool_results: list[conversation.ToolResultContent] = []
        for chat_content in chat_log.content[1:-1]:
            if chat_content.role == "tool_result":
                tool_results.append(chat_content)  # type: ignore[arg-type]
                continue
            if tool_results:
                messages.append(
                    Content(role="user", parts=_create_google_tool_response_parts(tool_results))
                )
                tool_results.clear()
            if (
                not isinstance(chat_content, conversation.ToolResultContent)
                and chat_content.content == ""
            ):
                messages.append(
                    _convert_content(
                        cast(
                            conversation.UserContent | conversation.AssistantContent,
                            chat_content,
                        )
                    )
                )
                continue
            messages.append(_convert_content(chat_content))  # type: ignore[arg-type]

        if messages and (
            (isinstance(messages[0], Content) and messages[0].role != "user")
            or (isinstance(messages[0], dict) and messages[0].get("role") != "user")
        ):
            messages.insert(0, Content(role="user", parts=[Part.from_text(text=" ")]))

        if tool_results:
            messages.append(
                Content(role="user", parts=_create_google_tool_response_parts(tool_results))
            )

        config = self._create_config()
        config.tools = tools or None
        config.system_instruction = prompt_content.content

        model = self.options.get(CONF_CHAT_MODEL, RECOMMENDED_CHAT_MODEL)
        chat = self._client.aio.chats.create(model=model, history=messages, config=config)
        user_message = chat_log.content[-1]
        assert isinstance(user_message, conversation.UserContent)
        chat_request: Any = user_message.content

        for _iteration in range(max_iterations):
            try:
                generator = await chat.send_message_stream(message=chat_request)
            except (APIError, ClientError, ValueError) as err:
                LOGGER.error("Error sending message: %s %s", type(err), err)
                raise HomeAssistantError(ERROR_GETTING_RESPONSE) from err

            chat_request = list(
                _create_google_tool_response_parts(
                    [
                        content
                        async for content in chat_log.async_add_delta_content_stream(
                            self.entity_id, _transform_stream(generator)
                        )
                        if isinstance(content, conversation.ToolResultContent)
                    ]
                )
            )
            if not chat_log.unresponded_tool_results:
                break

    async def _async_handle_live_chat_log(self, chat_log: conversation.ChatLog) -> None:
        """Run one request/response turn through the Gemini Live API.

        A short-lived WebSocket session is opened, the user text is sent, tool
        calls are executed, the spoken answer is collected from the output
        transcript, and the session is closed. This uses the Live model quotas
        (unlimited requests on the free tier) instead of the text model.
        """
        tools: list[genai_types.Tool] | None = None
        if chat_log.llm_api:
            tools = [
                _format_tool(tool, chat_log.llm_api.custom_serializer)
                for tool in chat_log.llm_api.tools
            ]

        prompt = chat_log.content[0].content or ""
        user_message = chat_log.content[-1]
        if not isinstance(user_message, conversation.UserContent):
            raise HomeAssistantError("Invalid user message")
        user_text = user_message.content or ""

        model = self.options.get(CONF_LIVE_MODEL, RECOMMENDED_LIVE_MODEL)
        voice = self.options.get(CONF_LIVE_VOICE, "Puck")
        config = genai_types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            system_instruction=prompt or None,
            tools=tools or None,
            speech_config=genai_types.SpeechConfig(
                voice_config=genai_types.VoiceConfig(
                    prebuilt_voice_config=genai_types.PrebuiltVoiceConfig(voice_name=voice)
                )
            ),
            input_audio_transcription=genai_types.AudioTranscriptionConfig(),
            output_audio_transcription=genai_types.AudioTranscriptionConfig(),
        )

        text = ""
        try:
            async with self._client.aio.live.connect(model=model, config=config) as session:
                await session.send_client_content(
                    turns=genai_types.Content(
                        role="user",
                        parts=[genai_types.Part.from_text(text=user_text)],
                    ),
                    turn_complete=True,
                )
                stream = session.receive()
                while True:
                    message = await stream.__anext__()
                    if message.tool_call:
                        if chat_log.llm_api is None:
                            raise HomeAssistantError("No LLM API configured")
                        responses = []
                        for call in message.tool_call.function_calls or []:
                            tool_input = llm.ToolInput(
                                tool_name=call.name or "",
                                tool_args=dict(call.args or {}),
                            )
                            result = await chat_log.llm_api.async_call_tool(tool_input)
                            payload = (
                                {"result": result.data}
                                if not result.error
                                else {"error": str(result.data)}
                            )
                            responses.append(
                                genai_types.FunctionResponse(
                                    name=call.name,
                                    id=call.id,
                                    response=payload,
                                )
                            )
                        await session.send_tool_response(function_responses=responses)
                        continue
                    if message.server_content:
                        if (
                            message.server_content.output_transcription
                            and message.server_content.output_transcription.text
                        ):
                            text += message.server_content.output_transcription.text
                        if message.server_content.turn_complete:
                            break
        except (APIError, ClientError, ValueError, StopAsyncIteration) as err:
            LOGGER.error("Gemini Live request failed: %s", err)
            raise HomeAssistantError(ERROR_GETTING_RESPONSE) from err

        chat_log.async_add_assistant_content_without_tools(
            conversation.AssistantContent(
                agent_id=self.entity_id,
                content=text.strip() or "Готово.",
            )
        )
