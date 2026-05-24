# In-Chat Commands Reference

This reference describes the behavior, arguments, and edge cases of the in-chat commands available in the `euczelnia-bridge` Moodle messenger daemon. All commands start with the configured prefix (default is `!`).

---

## Commands Table

| Command | Subcommand | Arguments | Description |
|---------|------------|-----------|-------------|
| `!help` | None | None | Lists all available commands with brief descriptions. |
| `!status` | None | None | Displays daemon status information. |
| `!mode` | None | `stateless` \| `context` | Changes conversation history memory mode. |
| `!clear` | None | None | Clears the current context memory history. |
| `!model` | None | `<model_name>` | Changes the model used by the AI gateway. |
| `!cleanup` | None | `on` \| `off` | Configures sent message deletion on exit. |
| `!prompt` | `show` | None | Prints the current session instructions. |
| | `set` | `<text>` | Overwrites the session instructions. |
| | `append` | `<text>` | Appends new text to active session instructions. |
| | `undo` | None | Restores the previous session instructions. |
| `!knowledge` | `show` | None | Lists files loaded in the TF-IDF knowledge base. |
| `!disconnect`| None | None | Gracefully disconnects the daemon. |

---

## Command Details & Examples

### `!help`
- **Description**: Displays a list of all commands supported by the daemon.
- **Example**:
  ```
  !help
  ```

### `!status`
- **Description**: Displays the current configuration and operational status of the daemon.
- **Fields displayed**:
  - `Mode`: stateless or context
  - `Model`: current model name
  - `Cleanup`: on or off
  - `Messages in session`: count of messages processed in this runtime session
  - `Uptime`: human-readable running duration (e.g., `1h 12m 4s`)
- **Example**:
  ```
  !status
  ```

### `!mode`
- **Description**: Changes conversational history state tracking.
  - `stateless`: Each incoming message is sent to the AI gateway independently. No past conversation context is preserved.
  - `context`: The daemon retrieves the last `max_history_turns` messages from the SQLite database to send along with the query, providing conversational memory.
- **Example**:
  ```
  !mode context
  ```

### `!clear`
- **Description**: Clears conversational history boundaries. Only available in `context` mode. In details: it closes the current session record in the database and creates a new one, filtering past messages out of subsequent history retrievals.
- **Example**:
  ```
  !clear
  ```

### `!model`
- **Description**: Switches the completion model at runtime. If the model name is invalid on the AI gateway, subsequent completions will fail.
- **Example**:
  ```
  !model gpt-4o
  ```

### `!cleanup`
- **Description**: Configures whether the daemon should attempt to delete all messages sent by it during this session when disconnecting.
  - `on`: Deletes all sent messages from the Moodle conversation upon shutdown.
  - `off`: Sent messages remain in the conversation history.
- **Example**:
  ```
  !cleanup on
  ```

### `!prompt`
Configures session-specific guidelines for the AI assistant. These instructions are appended to the core system prompt.

- **`!prompt show`**: Prints the current custom instructions.
  - *Example*: `!prompt show`
- **`!prompt set <text>`**: Clears active custom instructions and sets them to `<text>`.
  - *Example*: `!prompt set Answer all questions as an economics professor.`
- **`!prompt append <text>`**: Appends `<text>` to the end of current instructions on a new line.
  - *Example*: `!prompt append Do not use formulas.`
- **`!prompt undo`**: Restores the previous instructions state (behaves like an undo stack). If no prior prompt exists, clears the custom instructions.
  - *Example*: `!prompt undo`

### `!knowledge show`
- **Description**: Displays a summary of the loaded text files used by the TF-IDF search module and how many chunks were generated from them.
- **Example**:
  ```
  !knowledge show
  ```

### `!disconnect`
- **Description**: Gracefully shuts down the daemon process. Writes a farewell greeting (`🤖 Disconnected`), runs message cleanup (if configured), updates `daemon_status.json`, and exits the process.
- **Example**:
  ```
  !disconnect
  ```
