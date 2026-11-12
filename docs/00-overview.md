# Gemini Live Assistant — Overview

`gemini_live_assistant` is a Home Assistant custom integration that connects Home Assistant's
Assist stack to Google's Gemini API. It ships three runtime platforms — a **conversation agent**,
a **speech-to-text entity** and a **text-to-speech entity** — plus an unwired but functional
**Gemini Live** client module intended for a future realtime voice pipeline.

| | |
|---|---|
| Domain | `gemini_live_assistant` |
| Version | `0.1.0` (`custom_components/gemini_live_assistant/manifest.json`) |
| Integration type | `service` |
| IoT class | `cloud_polling` (declared; the integration is actually request/response) |
| Runtime dependency | `google-genai==2.25.0` |
| Python | `>=3.11` (`pyproject.toml`), CI runs 3.12 |
| License | MIT |
| Distribution | HACS custom repository / manual copy |

## Goals

1. **A capable Assist conversation agent.** Give Home Assistant a cloud LLM agent that keeps
   Home Assistant in control of device actions instead of re-implementing device logic.
2. **Native smart-home control through the Assist LLM API.** All tool definitions and tool
   execution are delegated to Home Assistant (`homeassistant.helpers.llm`), so the integration
   automatically inherits whatever intents/tools the selected LLM API exposes.
3. **Voice building blocks.** Provide STT and TTS entities that work inside a standard Assist
   pipeline, using Gemini audio understanding and Gemini TTS.
4. **A path to realtime voice.** Keep a self-contained Gemini Live (`BidiGenerateContent`)
   client in `live.py` so a future duplex audio pipeline can be built without rewriting the
   text agent.
5. **Small, auditable surface.** Three platform modules, one shared LLM bridge and one Live
   client; no vendored SDK code, no polling loops, no database.

## Features

Legend: **Implemented** = present and used at runtime; **Available, unwired** = code exists but
nothing in the integration calls it; **Planned** = not implemented.

| Feature | Status | Where |
|---|---|---|
| Assist conversation agent (text) | Implemented | `conversation.py` |
| Streaming responses to the frontend/pipeline | Implemented (`_attr_supports_streaming = True`) | `conversation.py` |
| Tool / function calling with HA tools | Implemented | `entity.py` |
| Device control via `llm.LLM_API_ASSIST` (default) | Implemented | `conversation.py`, `config_flow.py` |
| Selectable LLM APIs (multi-select) | Implemented | `config_flow.py` |
| Configurable chat model, prompt, temperature, max tokens | Implemented | `config_flow.py` |
| STT entity (Gemini audio transcription) | Implemented | `stt.py` |
| TTS entity (Gemini TTS, PCM→WAV) | Implemented | `tts.py` |
| Gemini Live client (audio in/out, transcripts, tool calls) | Available, unwired | `live.py` |
| `enable_live` / live model / live voice options | Stored only — no runtime effect | `config_flow.py`, `const.py` |
| Diagnostics with redaction | Planned | — |
| Unit tests (constants, config-flow shape, Live helpers) | Implemented — 16 tests, platform modules untested | `tests/` |
| Integration tests with a Home Assistant harness | Planned | — |
| Options change triggers reload | Planned | — |

## What this integration is not

- It is **not** an official Google, Home Assistant or Nabu Casa product.
- It does **not** talk to the Vertex AI API; it authenticates with a plain Gemini API key
  (Google AI Studio) only.
- It does **not** implement its own device services or entity control. It cannot act on a device
  that Home Assistant has not exposed to the selected Assist LLM API.
- It does **not** currently run a hands-free realtime voice loop. `live.py` is a client library,
  not an entity, service or pipeline stage.
- It does **not** store conversation history beyond Home Assistant's own `ChatLog` and whatever
  the Assist pipeline keeps for the session.

## Disclaimer and trademarks

> **Unofficial project.** This integration is not affiliated with, endorsed by, or sponsored by
> Google LLC, Google AI, or Home Assistant / Nabu Casa.
>
> "Gemini", "Google", "Google AI Studio" and related marks are trademarks of Google LLC. They are
> used here only in a nominative, descriptive sense to indicate API compatibility. All other
> trademarks belong to their respective owners.

Use of the Gemini API is governed by Google's terms and quota/pricing rules. API usage is billed
to the account that owns the key and may be subject to free-tier data-usage terms. See
[08-security.md](08-security.md) for the data-flow and privacy implications.

## Supported Home Assistant versions

| Claim | Detail |
|---|---|
| Declared minimum | `2024.1.0` in `hacs.json` (`"homeassistant": "2024.1.0"`) |
| Realistic minimum | A 2024.6+ release, because the code relies on `ConfigEntry.runtime_data` |
| Streaming conversation API | Requires a release that provides `ChatLog.async_provide_llm_data`, `ChatLog.async_add_delta_content_stream` and `conversation.async_get_result_from_chat_log` (late-2024 / 2025.x API surface) |
| Actively validated | Whatever `homeassistant` release CI installs at run time (unpinned, so current stable) |
| Python | 3.11+ supported by the code; CI uses 3.12 |

> ⚠️ The `hacs.json` minimum is **stale relative to the code**. Installing on 2024.1.0 will fail
> at import/setup time. Treat a current 2025.x stable release as the supported target until the
> manifest is updated or a compatibility shim is added. This mismatch is tracked in
> [09-github-and-roadmap.md](09-github-and-roadmap.md).

## Requirements

- Home Assistant with the `conversation` integration (declared in `manifest.json`).
- `assist_pipeline` and `intent` are listed as `after_dependencies`, so they are loaded first when
  present, but are not hard requirements.
- Outbound HTTPS access to the Gemini API.
- A Gemini API key from <https://aistudio.google.com/apikey>.
- HACS (recommended) or manual copy into `custom_components/`.

## Repository layout

```
gemini-live-assistant/
├── custom_components/gemini_live_assistant/
│   ├── __init__.py        # entry setup, shared google-genai Client
│   ├── const.py           # domain, config keys, model/voice lists, defaults
│   ├── entity.py          # ChatLog ↔ Gemini bridge, schema conversion, tool loop
│   ├── conversation.py    # ConversationEntity (Assist agent)
│   ├── stt.py             # SpeechToTextEntity
│   ├── tts.py             # TextToSpeechEntity
│   ├── live.py            # Gemini Live (BidiGenerateContent) client — unwired
│   ├── config_flow.py     # user step + options flow
│   ├── manifest.json
│   ├── strings.json
│   └── translations/{en,uk}.json
├── docs/                  # this documentation set
├── tests/                 # unit tests (const, config flow shape, live helpers)
├── .github/workflows/ci.yml
├── hacs.json
├── pyproject.toml
├── requirements.txt
├── requirements-dev.txt
├── README.md
└── LICENSE
```

## Documentation map

| Document | Contents |
|---|---|
| [01-architecture.md](01-architecture.md) | Module responsibilities, startup and request flow, tool-call loop, diagrams |
| [02-gemini-api.md](02-gemini-api.md) | Text models, streaming, function calling, model names, API key handling |
| [03-home-control.md](03-home-control.md) | Assist LLM API, `async_provide_llm_data`, tools, delta stream, device control |
| [04-configuration.md](04-configuration.md) | Config flow, options reference, defaults, reload semantics |
| [05-live-mode.md](05-live-mode.md) | Gemini Live client, why HA conversation is text-only, realtime roadmap |
| [06-stt-tts.md](06-stt-tts.md) | STT and TTS entities, audio formats, pipeline wiring |
| [07-testing.md](07-testing.md) | Test strategy, ruff/pytest commands, manual QA checklist |
| [08-security.md](08-security.md) | Key storage, redaction, `.gitignore`, threat model |
| [09-github-and-roadmap.md](09-github-and-roadmap.md) | Repo conventions, CI, releases, phased roadmap |
