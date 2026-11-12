# Live Mode (Gemini Live API)

`live.py` is a **functional client library** for the Gemini Live API
(`BidiGenerateContent`). It is not wired into the integration: no platform imports it, no entity
or service exposes it, and the `enable_live` option has no runtime effect. This document describes
what exists, why it cannot simply be plugged into the conversation entity, and what a real
implementation needs.

> Status: **experimental / unwired**. Treat `live.py` as an internal building block or as sample
> code for a separate realtime pipeline, not as a shipped feature.

## What the Live API is

The Live API is a **stateful, bidirectional** session over WebSocket:

- The client streams microphone audio (PCM) continuously.
- The model streams synthesized audio back as it speaks.
- The model performs voice activity detection and can be interrupted mid-sentence.
- Input and output transcripts can be requested.
- Function calls can be issued mid-session and answered without ending the session.

This is fundamentally different from `generateContent`/`chats`, which are request/response with a
finite text (or audio) result.

## `live.py` API reference

### `LiveConfig`

```python
@dataclass(slots=True)
class LiveConfig:
    model: str
    voice: str = "Puck"
    system_instruction: str = ""
    tools: list[types.Tool] = field(default_factory=list)
    language_code: str | None = None
    transcribe: bool = True
```

| Field | Maps to |
|---|---|
| `model` | `client.aio.live.connect(model=...)` |
| `voice` | `SpeechConfig.voice_config.prebuilt_voice_config.voice_name` |
| `system_instruction` | `LiveConnectConfig.system_instruction` (omitted when empty) |
| `tools` | `LiveConnectConfig.tools` (omitted when empty) — raw `types.Tool` objects |
| `language_code` | `SpeechConfig.language_code` |
| `transcribe` | Enables both `input_audio_transcription` and `output_audio_transcription` |

`tools` must already be Gemini `types.Tool` instances. `live.py` does **not** convert Home
Assistant `llm.Tool` objects; a future bridge can reuse `entity._format_tool`, which already
returns `types.Tool`.

### `_build_config`

```python
types.LiveConnectConfig(
    response_modalities=["AUDIO"],
    system_instruction=config.system_instruction or None,
    speech_config=speech_config,
    tools=config.tools or None,
    input_audio_transcription=types.AudioTranscriptionConfig() if config.transcribe else None,
    output_audio_transcription=types.AudioTranscriptionConfig() if config.transcribe else None,
)
```

Notes:

- Response modality is hardcoded to **audio only**. There is no `TEXT` mode switch.
- Voice is a prebuilt voice name (`Puck`, `Kore`, …), matching the `VOICES` list.
- Transcription is all-or-nothing.
- No `realtime_input_config`, VAD tuning, activity handling, context-window compression or
  session-resumption options are set. Defaults apply.

### `LiveEvent`

```python
@dataclass(slots=True)
class LiveEvent:
    audio: bytes | None = None
    text: str | None = None
    input_transcript: str | None = None
    output_transcript: str | None = None
    tool_calls: list[LiveToolCall] = field(default_factory=list)
    turn_complete: bool = False
    interrupted: bool = False
```

`_to_event` maps one `types.LiveServerMessage` to one `LiveEvent`:

| Server message | Event field |
|---|---|
| `server_content.model_turn.parts[].inline_data.data` | `audio` |
| `server_content.model_turn.parts[].text` (not thought) | `text` |
| `server_content.input_transcription.text` | `input_transcript` |
| `server_content.output_transcription.text` | `output_transcript` |
| `server_content.turn_complete` | `turn_complete` |
| `server_content.interrupted` | `interrupted` |
| `tool_call.function_calls[]` | `tool_calls` (`LiveToolCall(name, call_id, arguments)`) |

Limitations of the normaliser, by design of the current code:

- **Single-value fields.** If one message contains several audio or text parts, later parts
  overwrite earlier ones (`event.audio = ...`, `event.text = ...`). Chunked audio must be consumed
  as it arrives; a single `LiveEvent` is not a complete turn.
- **No mime type is exposed.** The consumer must assume 16-bit PCM and know the sample rate
  (Live output is commonly 24 kHz; input default here is 16 kHz).
- **Thought text is suppressed.**
- **No usage metadata, no session-resumption handles, no errors** are surfaced in `LiveEvent`.

### `GeminiLiveSession`

| Method | Implementation | Purpose |
|---|---|---|
| `send_text(text)` | `send_client_content(turns=Content(role="user", parts=[Part.from_text]), turn_complete=True)` | Inject a text turn (useful for testing without a microphone) |
| `send_audio(pcm, mime_type="audio/pcm;rate=16000")` | `send_realtime_input(audio=Blob(...))` | Stream microphone frames |
| `end_audio()` | `send_realtime_input(audio_stream_end=True)` | Signal end of speech / push-to-talk release |
| `send_tool_responses(responses)` | `send_tool_response(function_responses=[FunctionResponse(name, id, response={"result": ...})])` | Answer one or more function calls |
| `receive()` | async generator over `session.receive()`, yielding `LiveEvent` | Consume model output |
| `close()` | `session.close()` | End the session |

`LiveToolResponse` carries `name`, `call_id` and an arbitrary `response` payload, wrapped as
`{"result": response}` in the `FunctionResponse`.

### `connect`

```python
@asynccontextmanager
async def connect(client: Client, config: LiveConfig) -> AsyncIterator[GeminiLiveSession]:
    async with client.aio.live.connect(model=config.model, config=_build_config(config)) as session:
        yield GeminiLiveSession(session)
```

Usage (standalone, outside Home Assistant):

```python
from google.genai import Client
from custom_components.gemini_live_assistant.live import LiveConfig, connect

client = Client(api_key="...")

async with connect(
    client, LiveConfig(model="models/gemini-3.1-flash-live-preview", voice="Kore")
) as session:
    await session.send_text("Say hello in one short sentence.")
    async for event in session.receive():
        if event.audio:
            play_pcm(event.audio)  # your audio sink
        if event.output_transcript:
            print("model:", event.output_transcript)
        if event.turn_complete:
            break
```

There is **no reconnect, retry, backoff or error handling** around `connect`. A dropped WebSocket
raises out of the context manager.

## Why the Home Assistant conversation entity is text-only

The obstacle is architectural, not a missing parameter.

1. **The `ConversationEntity` contract is text in, text out.**
   `_async_handle_message(user_input: ConversationInput, chat_log: ChatLog)` receives an utterance
   that has already been transcribed and returns a `ConversationResult` built from text turns.
   There is no audio parameter and no return channel for raw frames.

2. **Assist is a staged pipeline, not a duplex call.**
   Wake word → STT → conversation agent → TTS. Each stage finishes before the next starts. There
   is no continuous microphone stream, no barge-in and no overlapping playback while listening.
   Live mode requires all three simultaneously.

3. **`ChatLog` models text turns.**
   Its content types are `SystemContent`, `UserContent`, `AssistantContent` and
   `ToolResultContent`, all string-based. Audio parts are not representable, so `async_provide_llm_data`
   and `async_add_delta_content_stream` cannot carry a live session.

4. **The satellite owns the hardware, not the agent.**
   Microphone and speaker access belongs to `assist_satellite` entities / the device running the
   pipeline. A conversation agent cannot open the mic itself; there is no supported API for an
   integration to stream arbitrary audio through the pipeline.

5. **Lifecycle mismatch.**
   A Live session outlives a single request and must be kept open across turns, with interruption
   handling. Conversation entities are instantiated once but are expected to be request-scoped and
   stateless; there is no place to own a long-lived WebSocket plus audio buffers.

6. **Streaming that exists today is text streaming.**
   `_attr_supports_streaming = True` only means `AssistantContentDeltaDict` chunks are emitted. It
   does not imply audio streaming.

Consequently, `live.py` cannot be exposed by setting a flag. It needs its own transport (websocket
API + frontend, or a custom satellite) and its own session lifecycle.

## What is currently implemented vs missing

| Capability | Status |
|---|---|
| Connect/disconnect to `BidiGenerateContent` | Implemented in `live.py` |
| Audio in (16 kHz PCM), audio out, end-of-audio signal | Implemented in `live.py` |
| Text turns for testing | Implemented in `live.py` |
| Input/output transcripts | Implemented in `live.py` |
| Tool call events and tool responses | Implemented in `live.py` |
| Turn-complete and interruption flags | Implemented in `live.py` |
| HA tool → Live tool conversion | **Missing** (reuse `entity._format_tool`) |
| Executing live tool calls through HA | **Missing** |
| Mic capture / speaker playback | **Missing** (no dependency, no entity) |
| Session manager / reconnect / resumption | **Missing** |
| Entity, service or websocket API | **Missing** |
| Frontend card / satellite firmware | **Missing** |
| Options actually driving a live session | **Missing** (`enable_live`, `live_model`, `live_voice` are inert) |

## Roadmap for realtime voice

Phases are ordered by dependency; nothing below is implemented today.

### Phase 1 — Tool bridge (planned)

- New module (e.g. `live_tools.py`) that converts `chat_log.llm_api.tools` into
  `types.Tool` via `entity._format_tool`.
- A dispatcher that maps `LiveToolCall` → `llm.ToolInput`, calls HA's tool execution path, and
  builds `LiveToolResponse` objects.
- Unit-testable without audio.

### Phase 2 — Session service (planned)

- A `GeminiLiveSessionManager` keyed by session id, owned by the config entry.
- A service or websocket command to open/close a session and to push/pull audio frames.
- Session limits: idle timeout, maximum duration, reconnect with context resumption if supported by
  the SDK version.
- Structured error events instead of exceptions.

### Phase 3 — Audio transport (planned)

Two realistic options:

| Option | Pros | Cons |
|---|---|---|
| Browser frontend (Lovelace card + WebSocket audio) | Works on phones/tablets/desktop; `getUserMedia` + Web Audio; easy updates | Requires a custom card; browser tab must stay open; echo cancellation depends on the device |
| Custom satellite firmware (ESPHome or similar) | Always-on, room-bound, native wake word | Separate firmware project; harder distribution |

Both need: 16 kHz mono PCM capture, 24 kHz playback, jitter buffer, acoustic echo cancellation,
barge-in (stop playback on `interrupted`), and VAD or push-to-talk.

### Phase 4 — Home Assistant integration (planned)

- An entity or device representing the live session (state: idle/listening/thinking/speaking).
- Area/device awareness passed into `LiveConfig.system_instruction` or tool context.
- Optional transcript entities for accessibility and automation triggers.
- Automation events (`live_turn_complete`, `live_tool_called`) for debugging.

### Phase 5 — Hardening (planned)

- Reconnect/backoff, quota errors, provider-side session expiry.
- Cost controls (max session length, idle disconnect).
- Multi-room arbitration and announcement ducking.
- Diagnostics with redaction.

## Risks and open questions

| Risk | Detail |
|---|---|
| Latency | Live is faster than staged STT→LLM→TTS, but network RTT and tool round trips still dominate |
| Cost | Continuous audio streaming bills for audio tokens for the whole session, not just utterances |
| Echo | Playing model audio while the mic is open causes self-interruption without AEC |
| Privacy | An open mic streams ambient audio to Google continuously — a materially different consent model from push-to-talk |
| Provider limits | Live sessions have duration/connection limits; resumption support depends on model and SDK |
| HA API stability | Any audio bridge relies on non-public or fast-moving APIs; a custom card/websocket contract must be versioned |
| Two audio paths | A live path duplicates STT/TTS rather than reusing the entities; keeping both consistent is ongoing work |
| Testing | Audio code is hard to unit test; needs loopback fixtures and mocked sessions |

## Recommendation for now

Use the shipped text agent plus Gemini STT/TTS for voice
([06-stt-tts.md](06-stt-tts.md)). Keep `live.py` as the reference implementation. Do not enable
`enable_live` expecting behaviour — it only stores preference values for a future release.
