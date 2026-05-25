# Configuration Reference

The behavior of the `euczelnia-bridge` daemon is controlled by configuration options defined in `config/config.json`. This document describes every field, its expected type, default value, and runtime behavior.

---

## Configuration Fields

### `poll_interval_seconds`
- **Type**: `float`
- **Default**: `12.0`
- **Description**: The interval (in seconds) between polling requests to eUczelnia Moodle to fetch new messages.
- **Runtime Mutable**: No (requires daemon restart).
- **Considerations**: Setting this value too low (e.g., `< 5.0`) may trigger rate limits on the university CAS or Moodle webservers.

### `mode`
- **Type**: `string`
- **Default**: `"stateless"`
- **Allowed Values**: `"stateless"`, `"context"`
- **Description**: Initial conversational memory mode.
  - `stateless`: Messages are answered individually.
  - `context`: History is retrieved from the database to provide chat memory.
- **Runtime Mutable**: Yes (via in-chat `!mode` command).

### `max_history_turns`
- **Type**: `integer`
- **Default**: `20`
- **Description**: Maximum number of past messages to fetch from the database when operating in `context` mode.
- **Runtime Mutable**: No (requires daemon restart).

### `cleanup_on_disconnect`
- **Type**: `boolean`
- **Default**: `false`
- **Description**: Determines whether the daemon deletes all messages it sent during the session when shutting down.
- **Runtime Mutable**: Yes (via in-chat `!cleanup` command).

### `command_prefix`
- **Type**: `string`
- **Default**: `Icon prefix "!"`
- **Description**: Character prefix used to identify in-chat commands.
- **Runtime Mutable**: No (requires daemon restart).

### `sentinel_start`
- **Type**: `string`
- **Default**: `"«AI»"`
- **Description**: Marker prepended to AI assistant responses. The daemon uses these markers to identify and skip its own replies to avoid infinite feedback loops.
- **Runtime Mutable**: No.
- **Warning**: Do not modify this unless you also update Moodle integration templates.

### `sentinel_end`
- **Type**: `string`
- **Default**: `"«/AI»"`
- **Description**: Marker appended to AI assistant responses.
- **Runtime Mutable**: No.

### `data_dir`
- **Type**: `string`
- **Default**: `"./data"`
- **Description**: Directory where runtime state, logs, status, and SQLite databases are stored.
- **Runtime Mutable**: No.

### `engine`
- **Type**: `string`
- **Default**: `"hermes"`
- **Allowed Values**: `"hermes"`, `"openai"`
- **Description**: The completions engine backend to use.
  - `hermes`: Spawns the local `hermes` CLI subprocess, routing queries through the Hermes agent loop (with tool-calling, web search, file access, and reasoning).
  - `openai`: Calls the OpenAI-compatible HTTP completions API.
- **Runtime Mutable**: No (requires daemon restart).

### `knowledge_files`
- **Type**: `array of strings`
- **Default**: `[]`
- **Description**: List of file paths to load into the TF-IDF search database at startup. Paths can be absolute or relative to the package root.
- **Runtime Mutable**: No.

---

## AI Gateway Configuration

The `ai_gateway` section configures connection details for the OpenAI-compatible completions API.

```json
"ai_gateway": {
  "base_url": "http://localhost:11434/v1",
  "api_key": "local-key",
  "model": "gpt-4o-mini"
}
```

### `ai_gateway.base_url`
- **Type**: `string`
- **Default**: `"http://localhost:11434/v1"` (Ollama default)
- **Description**: The base API endpoint of your completions gateway. For OpenAI, use `"https://api.openai.com/v1"`.

### `ai_gateway.api_key`
- **Type**: `string`
- **Default**: `"local-key"`
- **Description**: The authorization token/API key used to authenticate with the completions gateway.

### `ai_gateway.model`
- **Type**: `string`
- **Default**: `"gpt-4o-mini"`
- **Description**: The name of the model to use for generating text completions.
- **Runtime Mutable**: Yes (via in-chat `!model` command).
