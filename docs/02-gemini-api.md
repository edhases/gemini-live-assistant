# Gemini API Usage

The integration talks to Google's Gemini API through the official `google-genai` Python SDK,
pinned to **`2.25.0`** in `manifest.json` and `requirements.txt`. It uses the **Gemini Developer
API** with an API key (Google AI Studio). Vertex AI / service-account authentication is not
supported.

## Client and authentication

A single client is created per config entry:

```python
# __init__.py
client = Client(api_key=entry.data[CONF_API_KEY])
entry.runtime_data = GeminiRuntimeData(client=client)
```

All platforms use `entry.runtime_data.client`. The API key is read from `entry.data["api_key"]`,
never from `entry.options`.

Obtain a key at <https://aistudio.google.com/apikey>. Key handling, storage and redaction are
covered in [08-security.md](08-security.md).

### Validation

The config flow performs a real, minimal call before creating the entry:

```python
client = Client(api_key=api_key)
await self.hass.async_add_executor_job(lambda: list(client.models.list(config={"page_size": 1})))
```

- Runs in an executor because the synchronous `models.list` blocks.
- `page_size: 1` keeps it cheap and avoids paginating the whole catalogue.
- `APIError`, `ClientError`, `ValueError` → `invalid_auth`.
- Any other exception → `cannot_connect`.
- On success the entry's `unique_id` is set to the **last 8 characters** of the key, which
  prevents adding the same key twice.

## Model identifiers

Gemini model IDs are sent to the API **with the `models/` prefix**. The constants and the
selectors both preserve it; the UI strips it for display only
(`m.split("/")[-1]`).

### Text / conversation models (`CHAT_MODELS`)

| Model ID | Notes |
|---|---|
| `models/gemini-3.1-flash-lite` | **Recommended default** for chat and STT (`RECOMMENDED_CHAT_MODEL`, `RECOMMENDED_STT_MODEL`) |
| `models/gemini-3.1-flash` | Higher-capability Flash tier |
| `models/gemini-2.5-flash` | Previous-generation Flash |
| `models/gemini-2.5-pro` | Highest quality, highest latency/cost of the list |

The options selector uses `custom_value=True`, so any model ID available to the key can be typed
in even if it is not in this list. The list is a convenience, not a hard restriction.

The same list is reused for the **STT model selector** (`CONF_STT_MODEL`), which is intentional:
speech-to-text is implemented as a multimodal `generateContent` call on a text/vision model, not
as a dedicated speech model. See [06-stt-tts.md](06-stt-tts.md).

### TTS models (`TTS_MODELS`)

| Model ID | Notes |
|---|---|
| `models/gemini-3.1-flash-tts-preview` | **Recommended default** (`RECOMMENDED_TTS_MODEL`) |
| `models/gemini-2.5-flash-preview-tts` | Previous-generation TTS preview |

TTS models are called with `response_modalities=["AUDIO"]` and a `SpeechConfig`.

### Live models (`LIVE_MODELS`)

| Model ID | Notes |
|---|---|
| `models/gemini-3.1-flash-live-preview` | **Recommended default** (`RECOMMENDED_LIVE_MODEL`) |
| `models/gemini-2.5-flash-native-audio-preview-12-2025` | Native-audio preview |

These are only used by the unwired `live.py` client and are stored in options. Nothing in the
current runtime calls the Live API. See [05-live-mode.md](05-live-mode.md).

> Model availability, preview status and quotas change on Google's schedule. If a pinned default
> disappears from your key's catalogue, switch to another entry in the selector or type a current
> model ID. The integration does not query `/models` at runtime.

## Text generation: `chats.create` + streaming

The conversation agent uses a **chat session over a reconstructed history**, not a single-shot
`generateContent` call:

```python
# entity.py (abridged)
config = self._create_config()
config.tools = tools or None
config.system_instruction = prompt_content.content

chat = self._client.aio.chats.create(
    model=self.options.get(CONF_CHAT_MODEL, RECOMMENDED_CHAT_MODEL),
    history=messages,
    config=config,
)

generator = await chat.send_message_stream(message=chat_request)
```

Why `chats` rather than `generate_content`:

- The full multi-turn history is supplied on every request, so the SDK handles role ordering and
  content assembly.
- `send_message_stream` returns an async iterator of chunks, which is what HA's streaming
  conversation API needs.
- Tool follow-ups are naturally expressed as further `send_message_stream` calls on the same
  session.

`history` contains everything except the system prompt and the newest user message. The system
prompt is passed separately as `config.system_instruction`, which is the correct placement for a
Gemini system instruction and keeps it out of the visible transcript.

### Generation config

```python
GenerateContentConfig(
    temperature=self.options.get(CONF_TEMPERATURE, 1.0),
    max_output_tokens=self.options.get(CONF_MAX_TOKENS, 3000),
    automatic_function_calling=AutomaticFunctionCallingConfig(
        disable=True, maximum_remote_calls=None
    ),
)
```

| Field | Default | Meaning |
|---|---|---|
| `temperature` | `1.0` | Sampling randomness; options UI clamps to `0.0–2.0` |
| `max_output_tokens` | `3000` | Output cap per model turn; options UI clamps to `64–32000` |
| `system_instruction` | `llm.DEFAULT_INSTRUCTIONS_PROMPT` | Set from `ChatLog` index 0 |
| `tools` | `None` or a list of `Tool` | Built from `chat_log.llm_api.tools` |
| `automatic_function_calling` | disabled | The SDK must not execute tools; HA does |

### Streaming

`send_message_stream` yields `GenerateContentResponse` objects. The integration only inspects
`response.candidates[0]`:

```python
response_parts = candidate.content.parts or []
for part in response_parts:
    if part.text and not part.thought:
        chunk["content"] = part.text
    if part.function_call:
        chunk["tool_calls"] = [llm.ToolInput(...)]
```

Behaviour worth knowing:

- **Thought parts are dropped.** Gemini thinking models may emit `part.thought = True`; those are
  not user-visible and are filtered.
- **Multiple parts per chunk are possible.** Each part becomes its own delta; text and a function
  call can arrive in the same chunk.
- **The assistant role header is emitted exactly once**, lazily, on the first candidate that has
  content. This satisfies HA's delta protocol.
- **Empty candidate lists are skipped**, which happens for some safety/metadata events.
- **No retry logic.** A mid-stream failure propagates to the caller as `HomeAssistantError`.
- **No `streamGenerateContent` REST calls are made directly.** The SDK chooses the transport
  (`streamGenerateContent?alt=sse` under the hood); the integration only sees the async iterator.

### Error handling

```python
except (APIError, ClientError, ValueError) as err:
    LOGGER.error("Error sending message: %s %s", type(err), err)
    raise HomeAssistantError(ERROR_GETTING_RESPONSE) from err
```

`ERROR_GETTING_RESPONSE` is `"Sorry, I had a problem getting a response from Gemini."`. This
covers auth failures, quota exhaustion (`429`), invalid model IDs, malformed history and SDK
validation errors. The detail is logged but not shown to the user. There is no distinction between
retryable and permanent failures.

## Function / tool calling

The integration implements Gemini's **manual function-calling protocol**. Automatic execution is
disabled.

### Declaration (HA → Gemini)

Each Home Assistant `llm.Tool` becomes one `FunctionDeclaration`:

```python
Tool(
    function_declarations=[
        FunctionDeclaration(
            name=tool.name,
            description=tool.description,
            parameters=_format_schema(probatio.to_openapi(tool.parameters, custom_serializer=...)),
        )
    ]
)
```

Schema normalisation rules (camel→snake keys, uppercased types, enum stringification, empty-object
placeholder, `allOf` collapsing) are described in
[01-architecture.md](01-architecture.md#tool-schema-conversion).

### Model request (Gemini → HA)

A tool request arrives as `part.function_call` with `name` and `args`. It is converted to
`llm.ToolInput(tool_name=..., tool_args=...)` and pushed into the delta stream. Home Assistant then
validates and executes it.

### Tool result (HA → Gemini)

Results are **not** sent as a new top-level turn with a `tool` role. They are wrapped in a
**user-role** content containing `function_response` parts:

```python
Content(
    role="user",
    parts=[
        Part.from_function_response(
            name=tool_result.tool_name,
            response={"data": tool_result.result.data, "error": tool_result.result.error},
        )
    ],
)
```

This matches how Gemini expects function responses in multi-turn histories. Multiple results from
the same turn are batched into a single `Content` with several parts, preserving parallel tool
calls.

### Assistant history replay

When an earlier assistant turn contained tool calls, they are replayed with
`Part.from_function_call(name=..., args=...)`. Tool arguments pass through `_escape_decode`, which
un-escapes double-encoded strings such as `\\n` and works recursively through lists and dicts.
Without this, argument values fetched from a frontend round trip could reach HA as literal escaped
text.

## Live API (BidiGenerateContent)

`live.py` uses the same `Client` but a different transport:

```python
async with client.aio.live.connect(model=config.model, config=_build_config(config)) as session:
    yield GeminiLiveSession(session)
```

The live config requests `response_modalities=["AUDIO"]`, an optional prebuilt voice, optional
tools, and optional input/output audio transcription. Full details, event shapes and the send/
receive API are in [05-live-mode.md](05-live-mode.md). Nothing in `conversation.py`, `stt.py` or
`tts.py` imports this module.

## Quotas, cost and latency

- Every chat turn is at least one API request; every tool call adds another round trip. A single
  user request that turns on two lights can cost 3+ requests.
- The conversation agent sends the **entire history** each turn, so token usage grows with
  conversation length. HA's pipeline controls how much history is retained.
- Streaming reduces perceived latency but not token cost.
- STT uploads the full recorded clip; TTS requests one clip per utterance.
- Free-tier keys may be rate-limited and may have different data-usage terms than paid keys.
  Check Google's current pricing and terms before relying on this in a home setting.
- There is no client-side rate limiting, caching or backoff. `429` responses surface as the generic
  error message.

## Changing models safely

1. Open **Settings → Devices & Services → Gemini Live Assistant → Configure**.
2. Pick a model from the dropdown or type a full `models/...` ID (the chat, STT and live selectors
   accept custom values; TTS accepts custom values too via the shared `_model_selector`).
3. Save. The conversation agent picks the new value up on the next message; STT/TTS need the
   integration reloaded because they cache the model at entity construction.

If a model ID is wrong, the first request fails with the generic error and the real cause appears
in the Home Assistant log (`Error sending message: ...` / `Gemini STT request failed: ...`).
