# Security and Privacy

This integration holds a long-lived cloud credential and sends home data to a third party. Both
facts deserve explicit treatment.

## Where the API key lives

| Location | Contents | Protection |
|---|---|---|
| Config entry `entry.data["api_key"]` | Full key | Home Assistant's config-entry storage |
| `.storage/core.config_entries` | Full key as plain JSON | Filesystem permissions on the HA config directory; included in backups/snapshots |
| `entry.unique_id` | **Last 8 characters** of the key | Same file; visible in entry metadata |
| Entity attributes | Never | — |
| Device registry | Never (manufacturer/model only) | — |
| Integration options (`entry.options`) | Never | — |
| Logs | Never intentionally | — |
| Repository | Never | `.gitignore` + review |

Home Assistant does not encrypt `.storage` by default. Anyone with read access to the config
directory — or to a backup archive — can read the key. This is normal for HA integrations that use
API keys, but it means:

- Protect the HA config directory and backups like any other secret store.
- Encrypt backups or store them somewhere access-controlled.
- Do not publish `.storage` dumps, support bundles or full config directories in issues.

Key creation and management happen in Google AI Studio: <https://aistudio.google.com/apikey>.
Restrict the key to the Generative Language API where the console allows it, and use a key that is
dedicated to this integration so it can be revoked independently.

### The `unique_id` caveat

```python
await self.async_set_unique_id(api_key[-8:])
```

Using the last eight characters avoids storing a hash and makes duplicate detection trivial, but it
does place part of the secret in config-entry metadata. An eight-character suffix of a typical
Gemini key is not enough to reconstruct the key, but it is a fingerprint that can correlate
entries across backups or screenshots. A future version should use a salted hash (see
[09-github-and-roadmap.md](09-github-and-roadmap.md)).

### No key editing or reauth

The options flow deliberately does not expose the key. There is no reauth flow, so:

- Rotating a key means deleting and re-adding the entry.
- A revoked key is discovered only when a request fails (`invalid_auth` at setup time, generic
  request errors afterwards).
- The integration never validates the key in the background.

## No secrets in the repository

`.gitignore` covers the common leak vectors:

| Pattern | Protects against |
|---|---|
| `.env` | Local environment files with keys |
| `*.key` | PEM/key files |
| `secrets.yaml` | Home Assistant `!secret` values |
| `*.storage` | Copies of HA's `.storage` directory |
| `.venv/`, `venv/`, `env/` | Virtualenvs that may contain credentials in configs |
| `__pycache__/`, `*.py[cod]`, `build/`, `dist/`, `*.egg-info/` | Build artifacts |
| `.pytest_cache/`, `.coverage`, `htmlcov/` | Test artifacts that can embed values |
| `.idea/`, `.vscode/`, `.DS_Store`, `Thumbs.db` | Editor/OS files |

Good practices for contributors:

- Never hard-code a key, project ID or account email in source, tests, fixtures or docs.
- Use obvious placeholders (`"test-key"`) in tests and examples.
- Redact before pasting: key values, full request URLs with query parameters, transcripts, entity
  names and sensor values.
- Review `git diff --cached` before committing; a key pasted into a config snippet is easy to miss.
- If a key is committed, **revoke it first**, then rewrite history. Deleting the commit is not
  enough — GitHub caches objects and forks may retain them.

### Recommended automation (planned)

- `gitleaks` or `trufflehog` in CI, scanning both the working tree and commit history.
- A `SECURITY.md` with a private disclosure address.
- Dependabot for `google-genai` and GitHub Actions versions.
- `detect-secrets` pre-commit hook.

None of these are configured today.

## Logging and redaction

Current logging behaviour:

| Code | Level | Content |
|---|---|---|
| `config_flow` validation failure | `debug` | `"API key validation failed: %s"` with the exception |
| Unexpected validation error | `exception` | Full traceback |
| Chat send failure | `error` | Exception type and message |
| STT failure | `error` | Exception message |
| TTS failure | `error` | Exception message |
| Live connect | `debug` | Model name only |

What is **not** logged:

- The API key itself.
- Request headers.
- Prompt text, conversation content, transcripts or audio.
- Entity states returned by tools.

Residual risks:

- SDK exceptions can include request URLs, model IDs and response bodies. A `debug`/`error` log
  shared publicly may therefore reveal household context or account/project identifiers. Review
  logs before attaching them to an issue.
- `LOGGER.exception` in the config flow prints a traceback for unexpected errors; tracebacks can
  include local paths and library internals.
- There is **no diagnostics platform**, so there is no automated redaction. If one is added, it
  must redact `api_key`, the unique id suffix, prompts and any cached content.

### Enabling debug logging safely

```yaml
logger:
  logs:
    custom_components.gemini_live_assistant: debug
```

Debug logs from this integration are limited (model name, failure details), but Home Assistant's
own `homeassistant.components.conversation` and `homeassistant.helpers.llm` debug logs can contain
full prompts, tool arguments and entity states. Treat those as sensitive.

## Data sent to Google

Every request leaves the home network over HTTPS to Google's Generative Language API.

| Feature | Data sent | Notes |
|---|---|---|
| Conversation | System prompt, full conversation history, current utterance, tool declarations | History grows with the conversation |
| Tool calls | Tool name + arguments | May include entity names, areas, values |
| Tool results | Whatever HA returns, including entity states/attributes | `GetLiveContext` can include a broad snapshot of exposed entities |
| STT | Complete recorded audio clip + fixed prompt | Audio may contain speech from anyone in the room |
| TTS | Reply text + voice name | Text can contain personal data |
| Live (unwired) | Continuous microphone audio + system instruction + tool declarations | Would stream ambient audio for the whole session |

Implications:

- **Exposure settings are a privacy boundary.** `GetLiveContext` only sees entities exposed to the
  assistant, but that can still include presence, locks, alarms, energy and health-related sensors.
  Expose the minimum.
- **Audio is biometric-adjacent data.** Recordings may capture bystanders who did not consent.
  Prefer push-to-talk where that matters.
- **Third-party terms apply.** Google's API terms, quota rules and free-tier data-use policies
  govern retention and training. Check them for your account tier.
- **No local fallback.** If Google is unreachable, voice and chat stop working; nothing is queued
  or cached for later upload.
- **No telemetry beyond the API.** The integration itself has no analytics, crash reporting or
  update check.

## Threat model

| Threat | Impact | Current mitigation | Gap |
|---|---|---|---|
| Key stolen from `.storage` or a backup | Billed API usage, data access | Filesystem/backup controls | No encryption at rest, no per-key spend cap in the integration |
| Key committed to Git | Public exposure | `.gitignore` | No secret scanning in CI |
| Key leaked in logs or an issue | Exposure | Key never logged intentionally | No redaction tooling; SDK exception text may leak context |
| Malicious/compromised HA user | Control devices via Assist | HA authentication and permissions | The integration adds no extra authorisation |
| Indirect prompt injection (e.g. a crafted sensor name or broadcast text) | Model tricked into calling tools | HA validates tool arguments; exposure limits scope | No allow-list of "safe" tools; no confirmation for sensitive domains |
| Over-broad tool results | Private state sent to Google | Assist exposure | `GetLiveContext` can be broad |
| Compromised `google-genai` dependency | Key exfiltration / arbitrary code | Version pinned to `2.25.0` | No hash pinning, no Dependabot review process |
| Roommate/bystander audio capture | Privacy violation | Pipeline is push-to-talk in practice | Live mode would be always-on; not implemented |

### Prompt injection in context

Tool descriptions and entity names come from Home Assistant and are generally trusted, but a
malicious integration can register entities with adversarial names, and broadcast/TTS content can
carry attacker-controlled text. The model may follow such text as instructions. Home Assistant
still validates tool arguments and enforces exposure, so the blast radius is limited to actions the
assistant is already allowed to take. Reduce it further by:

- Exposing only necessary entities.
- Avoiding `lock`, `alarm_control_panel` and garage covers unless required.
- Reviewing what custom integrations add to the assistant.

## Hardening checklist

- [ ] Dedicated API key, used only by this integration.
- [ ] Key restricted to the Generative Language API where the console allows it.
- [ ] HA config directory and backups access-controlled and encrypted.
- [ ] `.storage` never shared in issues, forums or screenshots.
- [ ] Only necessary entities exposed to Assist.
- [ ] Sensitive domains (locks, alarms, garage) deliberately excluded or reviewed.
- [ ] Debug logs reviewed and redacted before sharing.
- [ ] Key rotated if it was ever pasted into a chat, log, commit or screenshot.
- [ ] `google-genai` version reviewed on upgrade (pinned in `manifest.json`).

## Incident response

If a key may have leaked:

1. **Revoke it immediately** in <https://aistudio.google.com/apikey>.
2. Create a replacement key.
3. In Home Assistant, delete the integration entry and add it again with the new key.
4. Review Google AI Studio / Cloud billing for unexpected usage.
5. If the leak was a Git commit: revoke first, then purge history (BFG/filter-repo), force-push,
   and ask GitHub Support to clear cached views if the repository was public.
6. Rotate any other secrets exposed in the same artifact (HA long-lived tokens, `secrets.yaml`).

## Planned security work

- Reauth flow and in-place key rotation.
- Salted-hash `unique_id` instead of the key suffix.
- Diagnostics platform with explicit redaction.
- Secret scanning and dependency updates in CI.
- Optional allow-list/deny-list of tool domains in the options flow.
- Optional confirmation for sensitive domains (if HA exposes a suitable hook).
- Documentation of exact Google data-retention behaviour per account tier.
