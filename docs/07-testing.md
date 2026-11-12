# Testing

## Current test suite

The repository has a `tests/` directory with **16 collected test items** across four files. All
tests are pure unit tests: they import the package directly and never perform network calls.

| File | Tests | Covers |
|---|---|---|
| `tests/conftest.py` | — | Inserts the repository root into `sys.path` so `custom_components.gemini_live_assistant` is importable without installing the package |
| `tests/test_const.py` | 9 (parametrised) | Model lists non-empty, all entries non-empty strings, every `RECOMMENDED_*` model present in its list, `RECOMMENDED_CONVERSATION_OPTIONS` contains prompt/model/LLM API |
| `tests/test_live.py` | 5 | `_build_config` requests `AUDIO` + configured voice + system instruction + transcription; transcription can be disabled; `_to_event` maps audio/text/transcripts/turn-complete/tool calls; thought text is suppressed; empty messages yield a default event |
| `tests/test_config_flow.py` | 2 | Config flow class is a `ConfigFlow` subclass with `VERSION == 1` and async `async_step_user`; options flow exists with async `async_step_init` |

Each test module starts with `pytest.importorskip(...)` for `homeassistant`, `voluptuous`,
`google.genai` and/or `google.genai.types`, so the suite **skips** rather than errors when the
dependencies are missing. CI installs `homeassistant` explicitly, so the tests run there.

### Not covered

| Area | Status |
|---|---|
| `entity.py` schema conversion (`_format_schema`, `_format_tool`) | No tests |
| `entity.py` message conversion (`_convert_content`, `_create_google_tool_response_parts`) | No tests |
| `entity.py` stream transform (`_transform_stream`) | No tests |
| Tool loop (`_async_handle_chat_log`, iteration limit, tool-result batching) | No tests |
| Config flow behaviour (validation errors, duplicate abort, options defaults) | Only class-shape tests |
| Setup/unload (`async_setup_entry`) | No tests |
| STT (`_pcm_to_wav`, mime selection, result mapping) | No tests |
| TTS (`_pcm_to_wav`, audio extraction, error paths) | No tests |
| Live send/receive methods and `connect()` context manager | Only config/event helpers |

## Tooling

`pyproject.toml` defines both tools:

```toml
[tool.ruff]
target-version = "py311"
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP", "SIM", "RUF"]
ignore = ["E501"]

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
```

- Ruff covers pycodestyle errors (`E`), Pyflakes (`F`), import sorting (`I`), bugbear (`B`),
  pyupgrade (`UP`), simplify (`SIM`) and Ruff-specific rules (`RUF`). Line length is enforced by
  `ruff format`, not by `E501` (ignored).
- `ruff format` also formats Python code fences inside Markdown files. Keep doc snippets in
  formatter-compatible style or run `ruff format docs` after editing.
- `asyncio_mode = "auto"` means plain `async def test_...` functions run without
  `@pytest.mark.asyncio`.
- Dev dependencies (`requirements-dev.txt`): `pytest>=7.4`, `pytest-asyncio>=0.23`,
  `pytest-cov>=4.1`, `ruff>=0.6`. `homeassistant` is **not** listed there; CI installs it ad hoc.
- `tests/conftest.py` does not use `pytest_homeassistant_custom_component`; there is no `hass`
  fixture, no `enable_custom_integrations`, and no config-entry fixture yet.

## Running locally

Use a virtual environment with **Python 3.12** to match CI. Home Assistant's dependency set is
sensitive to Python version.

```powershell
cd "E:\Github\Home Assistant\gemini-live-assistant"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
python -m pip install -r requirements-dev.txt homeassistant
```

```powershell
# Lint (required to match CI)
ruff check .
ruff format --check .

# Tests
pytest -q
pytest -q tests/test_live.py
pytest -q -k "build_config"
pytest -q --cov=custom_components.gemini_live_assistant --cov-report=term-missing
```

To reproduce the CI environment exactly, use Python 3.12 and run the same four commands the
workflow runs: `ruff check .`, `ruff format --check .`, `pip install -r requirements-dev.txt homeassistant`,
`pytest -q`.

### Known local issues

| Symptom | Cause | Action |
|---|---|---|
| `RuntimeError: httpx was already imported; call alias_httpx() ...` during collection | Import-order conflict between `homeassistant` and `httpx2` on some local installs (observed on Python 3.14) | Use a clean Python 3.12 venv as CI does, or uninstall the conflicting `httpx2` shim |
| `ERROR: file or directory not found: tests` | Running from the wrong directory | Run from the repository root; `testpaths` is relative |
| Tests silently skipped | `homeassistant`/`google-genai` not installed | Install both (or rely on CI) |

## Test strategy

### Layer 1 — Pure helpers (highest value, cheapest)

These functions are deterministic and need no Home Assistant runtime:

| Target | What to assert |
|---|---|
| `_camel_to_snake` | `"maxItems"` → `"max_items"`, leading underscores stripped |
| `_format_schema` | Unsupported keys dropped; `type` uppercased; invalid `format` dropped; `allOf` collapsed; non-string enum forced to `STRING` + stringified; empty object gets `json: STRING` |
| `_format_tool` | Produces exactly one `FunctionDeclaration`; `parameters is None` when the HA tool has no schema |
| `_escape_decode` | Recurses through list/dict; decodes `\\n`; leaves non-strings untouched |
| `_validate_tool_results` | Primitives preserved; unknown objects stringified |
| `_convert_content` | User/system → text part; assistant text + `function_call` parts; empty assistant gets a single-space part |
| `_create_google_tool_response_parts` | One `function_response` per result with `{data, error}`; batching order preserved |
| `_transform_stream` | Role emitted once; thought text skipped; tool call → `llm.ToolInput`; empty candidate list skipped |
| `tts._pcm_to_wav` | RIFF/WAVE header, mono, 2-byte samples, 24 000 Hz, payload length matches |
| `stt._pcm_to_wav` | Sample width `bit_rate // 8`, frame rate and channel count from metadata |

Example, matching the existing style:

```python
async def _fake_stream(chunks):
    for chunk in chunks:
        yield chunk


async def test_transform_stream_skips_thoughts():
    from types import SimpleNamespace

    from custom_components.gemini_live_assistant.entity import _transform_stream

    response = SimpleNamespace(
        candidates=[
            SimpleNamespace(
                content=SimpleNamespace(
                    parts=[SimpleNamespace(text="hidden", thought=True, function_call=None)]
                )
            )
        ]
    )

    deltas = [delta async for delta in _transform_stream(_fake_stream([response]))]

    assert deltas == [{"role": "assistant"}]
```

### Layer 2 — Platform behaviour with a fake client

Construct entities with a stub `entry` exposing `runtime_data.client` whose
`aio.models.generate_content` / `aio.chats.create` returns recorded objects.

- **STT:** feed a WAV stream, assert the mime type and prompt, assert the stripped text and echoed
  language, assert `HomeAssistantError` on SDK failure, assert the PCM fallback wraps to WAV.
- **TTS:** return one inline audio part, assert `("wav", bytes)` and header fields; return a text
  part and assert `"returned no audio"`; return empty data and assert `"empty audio"`.
- **Conversation:** stub `ChatLog` with a system content, one user message and a fake
  `llm_api.tools`; assert history ordering, `system_instruction`, and that `tools is None` when no
  API is selected.

### Layer 3 — Home Assistant integration tests (planned)

Add `pytest-homeassistant-custom-component` to `requirements-dev.txt` and use the `hass` fixture:

```python
from pytest_homeassistant_custom_component.common import MockConfigEntry


async def test_setup_and_unload(hass):
    entry = MockConfigEntry(
        domain="gemini_live_assistant",
        data={"api_key": "test-key"},
        options={"chat_model": "models/gemini-3.1-flash-lite"},
    )
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert "conversation" in hass.config.components
    assert await hass.config_entries.async_unload(entry.entry_id)
```

Also worth testing with the harness:

- Config flow: invalid key → `invalid_auth`; duplicate key → `already_configured`; valid key →
  entry with recommended options.
- Options flow: all fields present, ranges enforced, defaults echo current options.
- Conversation agent: mock `Client` and call `_async_handle_message`, asserting streaming deltas
  and the final `ConversationResult`.
- Tool loop: a fake chat that returns a function call once, then text; assert exactly two
  `send_message_stream` calls and correct `function_response` payload.

### Layer 4 — Manual smoke tests (required before release)

Automated tests cannot validate Google's live behaviour, audio devices or the Assist UI.

## Manual test plan in Home Assistant

### Setup

1. Copy `custom_components/gemini_live_assistant` into your HA config directory (or install via
   HACS) and restart.
2. Enable debug logging temporarily:

   ```yaml
   logger:
     logs:
       custom_components.gemini_live_assistant: debug
   ```

3. Check **Settings → Devices & Services** for the integration and that three entities exist.

### Config flow

| Step | Expected |
|---|---|
| Add integration, submit `not-a-key` | `Invalid API key.`; no entry created |
| Submit a valid key | Entry created, title `Gemini Live Assistant` |
| Add the same key again | `This API key is already configured.` |
| Open Configure | All eleven options render with current values |
| Set temperature `-1` / `3`, max tokens `10` / `40000` | Validation blocks submission (range 0–2 and 64–32000) |
| Set temperature `0.7`, max tokens `2048`, custom model ID | Save succeeds; values persist after reopening |

### Conversation (text)

1. **Settings → Voice assistants → Add assistant**, conversation agent = Gemini.
2. Open Assist, type `Hello, who are you?`
   - Response streams in (not one block at the end).
   - No tool call is made for a pure chat question.
3. Ask `What lights are on?`
   - Expect a `GetLiveContext`/`HassGetState` tool call in the debug log.
4. Expose one light, then say `Turn on the kitchen light.`
   - Light turns on; tool call and result appear in the log; answer confirms.
5. Say `Turn it off and set the brightness to 30%.`
   - Two sequential tool calls; loop completes in one user turn.
6. Ask to control an **unexposed** entity.
   - User gets a graceful failure, not an unhandled exception.
7. Reload the integration and repeat step 2.
   - Agent still selected and responds.

### STT / TTS

1. Select `Gemini STT` and `Gemini TTS` in the assistant.
2. Use the Assist microphone button: speak a short sentence.
   - Transcript appears; agent replies; audio plays.
3. Speak for ~30 seconds.
   - Request succeeds (or fails clearly if the clip exceeds limits).
4. Change `tts_voice` to `Kore`, reload the integration, repeat.
   - Voice changes. Without reload, the old voice persists.
5. Change `tts_model` to a chat model (e.g. `models/gemini-3.1-flash-lite`), reload, speak.
   - TTS fails with "returned no audio" in the log; revert afterwards.

### Live client (no microphone)

```python
# Run outside HA with a valid key; see 05-live-mode.md
async with connect(client, LiveConfig(model=MODEL, voice="Puck")) as session:
    await session.send_text("Say hello.")
    async for event in session.receive():
        assert event.audio or event.output_transcript or event.turn_complete
        if event.turn_complete:
            break
```

Expected: audio bytes, an output transcript, and a turn-complete event. This validates the Live
plumbing without an audio device.

### Unload / reload / removal

| Action | Expected |
|---|---|
| Reload entry | No errors; entities return; agent still selectable |
| Delete entry | Entities and agent disappear; no traceback |
| Restart HA | Entry loads without network calls at startup |

## Coverage targets

Suggested, not enforced:

| Area | Target |
|---|---|
| `entity.py` helpers | ≥ 90 % |
| `stt.py` / `tts.py` | ≥ 80 % |
| `config_flow.py` | ≥ 80 % |
| `live.py` helpers | ≥ 80 % |
| Overall | ≥ 75 % |

Add `--cov-fail-under=75` to pytest only after the suite reaches the threshold; enabling it now
would fail CI.
