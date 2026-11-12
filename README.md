# Gemini Live Assistant

[![HACS](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A community Home Assistant conversation assistant powered by Google Gemini, with native smart-home control. Supports a text conversation agent (Assist) plus Gemini STT/TTS for voice pipelines, and includes a functional Gemini Live (realtime) client module.

> **Disclaimer:** This is NOT an official Google or Home Assistant product. "Gemini" and "Google" are trademarks of Google LLC, used only to indicate compatibility.

## Features

- **Conversation agent** for Home Assistant Assist — text chat with Gemini.
- **Smart-home control** through Home Assistant's Assist LLM API (turn on/off, lights, climate, sensors, scripts, scenes).
- **STT & TTS** entities using Gemini audio understanding and Gemini TTS.
- **Gemini Live client** (`live.py`) for realtime audio sessions (building block for a custom voice pipeline).
- Configurable model, system prompt, temperature, max tokens, voices.

## Installation (HACS)

1. Add this repository as a custom repository in HACS.
2. Install "Gemini Live Assistant".
3. Restart Home Assistant.
4. Settings → Devices & Services → Add Integration → **Gemini Live Assistant** → paste your Gemini API key.
5. Optionally open the integration's **Configure** to pick models, prompt and enable Home Assistant control.

## Manual installation

Copy `custom_components/gemini_live_assistant` to your Home Assistant `custom_components` directory, then restart.

## Getting an API key

Create one at <https://aistudio.google.com/apikey>.

## Usage

- Set the integration's conversation agent as the assistant in **Settings → Voice assistants**.
- Select the Gemini STT/TTS entities in the Assist pipeline for voice.
- Ensure the integration is exposed to Assist with the `assist` LLM API for device control.

## Live mode

Home Assistant's standard conversation entity is text based. The `live.py`
module implements the Gemini Live API (BidiGenerateContent) with audio in/out,
transcripts and tool calls. It is a ready building block for a custom
frontend/pipeline; wiring it into a fully hands-free HA voice loop is planned.

## Security

The API key is stored only in the Home Assistant config entry. No secrets are committed to this repository.

## License

MIT — see [LICENSE](LICENSE).
