# Home Control via the Assist LLM API

Gemini does not touch Home Assistant entities directly. The integration exposes Home Assistant's
own LLM tool surface to Gemini, and Home Assistant executes every action. This document describes
that contract, the code path, and what the model can and cannot do.

## The division of labour

| Layer | Responsibility |
|---|---|
| `helpers.llm` (Home Assistant) | Defines tools, their Pydantic parameter models and descriptions; resolves which entities are exposed; executes intents; enforces assistant permissions |
| `conversation.ChatLog` | Carries the system prompt, user/assistant turns, tool calls and tool results for one conversation |
| `conversation.py` | Supplies LLM context and options via `async_provide_llm_data`, sets the `CONTROL` feature flag |
| `entity.py` | Converts HA tools to Gemini `FunctionDeclaration`s, streams model output back into the `ChatLog`, relays tool results, loops |
| Gemini | Chooses a tool and arguments; phrases the final answer |

There is no device-specific code in this repository: no service calls, no entity lookups, no
domain switch statements. That is deliberate — it means the agent gains support for new domains
as soon as Home Assistant's Assist intents do.

## Enabling control

Control is enabled by selecting at least one LLM API in the options flow:

```python
# conversation.py
if options.get(CONF_LLM_HASS_API):
    self._attr_supported_features = conversation.ConversationEntityFeature.CONTROL
```

`RECOMMENDED_CONVERSATION_OPTIONS` sets `CONF_LLM_HASS_API` to `[llm.LLM_API_ASSIST]`, so a
freshly created entry is control-capable by default. The options selector is populated from
`llm.async_get_apis(self.hass)`, so any registered LLM API (Assist, or a custom one from another
integration) can be chosen, and multiple APIs can be selected at once.

Consequences of clearing the selection:

- `chat_log.llm_api` is `None`, so `config.tools` is `None`.
- `ConversationEntityFeature.CONTROL` is not advertised, and voice assistants will not consider
  the agent able to control devices.
- Gemini still answers questions, but cannot act.

## `chat_log.async_provide_llm_data`

This is the single integration point with Home Assistant's LLM layer:

```python
await chat_log.async_provide_llm_data(
    user_input.as_llm_context(DOMAIN),
    options.get(CONF_LLM_HASS_API),
    options.get(CONF_PROMPT),
    user_input.extra_system_prompt,
)
```

| Argument | Source | Effect |
|---|---|---|
| `llm_context` | `user_input.as_llm_context(DOMAIN)` | Tells HA which integration/platform is asking, plus language, device id and context (area/device of the satellite) |
| `llm_api_id` | `CONF_LLM_HASS_API` (a list) | Selects the API(s); `None`/empty means no tools |
| `prompt` | `CONF_PROMPT` | System prompt text |
| `extra_system_prompt` | `ConversationInput` | Additional instructions injected by the pipeline/frontend for this request |

What HA does with it:

1. Resolves the selected LLM API(s) and merges their `custom_instructions`.
2. Builds the `SystemContent` at `chat_log.content[0]`. `entity.py` later asserts this exists and
   raises `HomeAssistantError("Invalid prompt content")` if it is empty.
3. Appends a `UserContent` for the current utterance.
4. Attaches `chat_log.llm_api`, exposing `.tools` and `.custom_serializer`.
5. Raises `conversation.ConverseError` for unusable configurations (unknown API id, no API
   available, etc.). `conversation.py` converts that into a normal
   `ConversationResult` via `err.as_conversation_result()` instead of failing the request.

Because HA composes the API's custom instructions with the configured prompt, the prompt field is
best used for persona, tone and verbosity. Repeating tool rules there tends to conflict with the
API's own instructions.

## Tools

`entity.py` builds the tool list from the live `ChatLog`, never from a static registry:

```python
if chat_log.llm_api:
    tools = [
        _format_tool(tool, chat_log.llm_api.custom_serializer) for tool in chat_log.llm_api.tools
    ]
```

Each `llm.Tool` becomes exactly one `Tool(function_declarations=[...])` with the tool's name,
description and converted parameter schema. No tools are added, removed or renamed by this
integration.

With the default `llm.LLM_API_ASSIST`, the available tools are Home Assistant's Assist intent
tools. Typical examples (the exact set depends on the HA version and which integrations are
loaded):

| Tool (example) | Used for |
|---|---|
| `HassTurnOn` | Lights, switches, fans, media players, scripts, scenes, input booleans |
| `HassTurnOff` | The same domains |
| `HassLightSet` | Brightness, colour, colour temperature |
| `HassClimateSetTemperature` | Thermostats / climate targets |
| `HassSetVolume` | Media player volume |
| `HassMediaPause`, `HassMediaNext`, `HassMediaUnpause` | Playback control |
| `HassVacuumStart`, `HassVacuumReturnToBase` | Vacuums |
| `HassBroadcast` | Announcements to media players |
| `GetLiveContext` | "What's the state of …", whole-home summaries |
| `HassGetState` | Specific entity state/attribute queries |

Treat this table as illustrative, not authoritative: the authoritative list is whatever
`chat_log.llm_api.tools` contains at request time. A custom LLM API registered by another
integration will present a different set.

> The description and parameter schema of each tool are passed to Gemini verbatim (apart from the
> schema normalisation described in [01-architecture.md](01-architecture.md#tool-schema-conversion)).
> Vague descriptions in a custom API produce vague tool selection.

## Tool execution and `async_add_delta_content_stream`

Streamed model output is handed back to HA:

```python
chat_log.async_add_delta_content_stream(
    self.entity_id,
    _transform_stream(generator),
)
```

This async generator is where the real work happens:

1. It consumes the normalised deltas (`{"role": ...}`, `{"content": ...}`,
   `{"tool_calls": [...]}`).
2. For each `tool_calls` entry it validates the arguments against the tool's Pydantic model.
3. It executes the corresponding intent through Home Assistant, honouring exposure and assistant
   permissions.
4. It appends the assistant message and a `ToolResultContent` to the `ChatLog`.
5. It yields the `ChatLog` content objects, including `ToolResultContent`, back to the caller.

`entity.py` uses only the yielded `ToolResultContent` items, converts them to
`function_response` parts, and sends them as the next model input. Everything else is already in
the log.

### Result envelope

```json
{
  "data": { "success": true, "result": { ... } },
  "error": null
}
```

Both fields are always present. On a failed tool call, `error` carries the message (for example an
unknown entity or a permission denial) and `data` may be empty. The model is responsible for
turning that into a user-facing sentence; the integration does not raise or retry.

### Why results are user-role content

Gemini's function-calling protocol expects `function_response` parts inside a `user` turn, not a
dedicated `tool` role. `_create_google_tool_response_parts` builds one `Content(role="user",
parts=[...])` for the batch, so parallel tool calls in a single model turn are answered together.

## The loop

```python
for _iteration in range(max_iterations):  # max_iterations = MAX_TOOL_ITERATIONS = 10
    generator = await chat.send_message_stream(message=chat_request)
    chat_request = list(_create_google_tool_response_parts([...]))
    if not chat_log.unresponded_tool_results:
        break
```

- Iteration 1 sends the user's text.
- Iterations 2..n send function responses for the tools the model just requested.
- The loop exits as soon as HA reports no unresponded tool results, or after 10 iterations.
- On the 10th iteration the loop simply ends; the user gets the model's last text (which may be
  empty). There is no "too many tool calls" message.
- `TIMEOUT_MILLIS = 15000` exists in `const.py` but is not applied to this loop.

Because Gemini is instructed to call one or more tools per turn, a typical exchange is:

```
user: "Turn on the kitchen lights and set them to 40%"
model → HassTurnOn(kitchen lights)
HA    → {"data": {"success": true, ...}}
model → HassLightSet(kitchen lights, brightness=102)
HA    → {"data": {"success": true, ...}}
model → "Done — kitchen lights on at 40%."
```

## What "supported device control" means

The integration supports **whatever the selected Assist LLM API exposes**, subject to Home
Assistant's own exposure settings:

- **Domains:** `light`, `switch`, `fan`, `cover`, `climate`, `media_player`, `vacuum`, `lock`,
  `script`, `scene`, `input_*`, `humidifier`, `water_heater`, and others — contingent on the
  intents present in your HA version.
- **By name, area or floor:** Assist resolves friendly names and areas. The LLM context includes
  the satellite's area/device when the pipeline provides it, so "turn on the light" can resolve
  relative to the room.
- **State queries:** `GetLiveContext`/`HassGetState` let the model report sensor values and
  on/off states rather than guessing.
- **Security-sensitive domains:** locks, covers and alarms are governed entirely by HA's intent
  implementation and exposure rules. This integration adds no confirmation step, no allow-list and
  no domain filtering of its own.

To restrict control:

1. **Settings → Voice assistants → Expose** — choose which entities the assistant may see.
2. Select a narrower LLM API in the integration options, if you have one registered.
3. Deselect all LLM APIs to make the agent read-only.

## Failure modes and how they appear

| Situation | User sees | Log |
|---|---|---|
| No LLM API selected | Normal chat answer, no actions | — |
| Tool raises (unknown entity, denied) | Model's phrasing of the error, often "I couldn't do that" | HA intent log; `error` in the response envelope |
| Gemini returns `429`/`401`/invalid model | `Sorry, I had a problem getting a response from Gemini.` | `Error sending message: <type> <detail>` |
| Tool loop exceeds 10 iterations | Last model text, possibly empty | — |
| `ChatLog` has no system content | `Invalid prompt content` error | — |
| Model hallucinated a tool name | HA rejects it; error returned to the model, which may retry | — |

## Limitations

- **No local/offline control.** Every turn requires Gemini.
- **No custom intents.** If HA has no tool for an action, the agent cannot do it.
- **No per-tool confirmation UI.** Confirmation, if any, comes from Home Assistant's intent
  handling, not this integration.
- **No partial streaming of tool intents.** The user sees text deltas only; tool execution happens
  between model turns.
- **No explicit timeout.** A hung tool call or slow model response is bounded only by the SDK /
  aiohttp defaults and the Assist pipeline's own timeout.
- **Latency.** Each tool round trip is a full model request with the accumulated history.
