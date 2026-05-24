# eUczelnia Bridge

An AI assistant integration for the university e-Uczelnia Moodle messenger chat.

### What is this?
eUczelnia Bridge is a self-contained automation system that acts as an intelligent intermediary between your university Moodle chat and an AI language model. It includes Playwright automation to securely log into the university's CAS portal, capture session cookies, and spawn a lightweight background daemon that polls a chat thread and replies to messages automatically.

### Why use this?
- **Automated Responses**: Run a 24/7 AI tutor, student assistant, or responder directly inside any Moodle chat without keeping a browser window open.
- **Contextual Memory**: Maintain continuous, multi-turn conversations using local SQLite databases for chat history.
- **Local Knowledge Integration**: Instantly reference syllabus docs, lecture notes, or project guides using an integrated standard-library TF-IDF search database.
- **Dynamic Control**: Change AI behavior, swap models, clear history, or inspect status directly in the chat using Moodle-native text commands.

---

## Architecture Overview

```mermaid
graph TD
    User[Moodle Chat User] -->|Sends message| Moodle[eUczelnia Moodle]
    Daemon[UczelniaDaemon] -->|Polls chat messages| Moodle
    Daemon -->|Queries text| KB[Knowledge Base]
    Daemon -->|Completion request| OpenAI[AI Gateway]
    Daemon -->|Sends reply| Moodle
```

---

## Requirements

- **Python**: 3.11 or newer
- **Playwright**: For automated Casper (CAS) headless login
- **Dependencies**: Listed in `requirements.txt`

---

## Quick Start (5 Steps)

### Step 1: Install
Clone this package and run the installation script:
```bash
bash install.sh
```

### Step 2: Configure Credentials
Edit the `config/.env` file and insert your CAS credentials:
```env
EUCZELNIA_USERNAME=your_cas_username
EUCZELNIA_PASSWORD=your_cas_password
```

### Step 3: Run CAS Login
Run the browser automation to obtain an active session key and session cookies:
```bash
./venv/bin/python login/login.py --output data/session.json
```
This writes session credentials to `data/session.json`.

### Step 4: Resolve Conversation ID
List your conversations to obtain the target `conversation_id`:
```bash
./venv/bin/python -c "
import json
from eUczelniaMessenger import MessengerClient, SessionData
with open('data/session.json') as f:
    s = json.load(f)
client = MessengerClient(SessionData(sesskey=s['sesskey'], cookies=s['cookies'], user_id=s['user_id']))
for c in client.get_conversations(limit=10).conversations:
    print(f'ID: {c.id} | Name: {c.name}')
"
```

### Step 5: Start the Daemon
Launch the daemon in the background to begin monitoring the conversation and generating AI completions:
```bash
SESSKEY=$(./venv/bin/python -c "import json; print(json.load(open('data/session.json'))['sesskey'])")
USER_ID=$(./venv/bin/python -c "import json; print(json.load(open('data/session.json'))['user_id'])")
COOKIE_NAME=$(./venv/bin/python -c "import json; print(list(json.load(open('data/session.json'))['cookies'].keys())[0])")
COOKIE_VALUE=$(./venv/bin/python -c "import json; print(list(json.load(open('data/session.json'))['cookies'].values())[0])")

nohup ./venv/bin/python daemon/daemon.py \
  --conversation-id <CONV_ID> \
  --user-id "$USER_ID" \
  --sesskey "$SESSKEY" \
  --cookie-name "$COOKIE_NAME" \
  --cookie-value "$COOKIE_VALUE" \
  --user-prompt "You are a helpful programming tutor." \
  > data/daemon.log 2>&1 &
```

Monitor the state of the daemon using `data/daemon_status.json`:
```bash
cat data/daemon_status.json
```

---

## In-Chat Commands

You can control the daemon directly from the Moodle chat using standard commands. Default prefix is `!`:

| Command | Arguments | Description |
|---------|-----------|-------------|
| `!help` | None | Lists available commands. |
| `!status` | None | Displays uptime, mode, message counts, and active model. |
| `!mode` | `stateless` \| `context` | Switches chat memory state. |
| `!clear` | None | Clears chat memory context (only in `context` mode). |
| `!model` | `<model_name>` | Switches active completions model at runtime. |
| `!cleanup` | `on` \| `off` | Toggles automatic deletion of sent messages upon shutdown. |
| `!prompt` | `show` \| `set <text>` \| `append <text>` \| `undo` | Configures session-specific guidelines. |
| `!knowledge` | `show` | Displays loaded knowledge base files and chunk counts. |
| `!disconnect` | None | Gracefully disconnects the daemon. |

---

## Configuration Reference

Check `docs/configuration.md` for details on configuring `config/config.json`.
Check `docs/commands.md` for in-depth examples of chat commands.
Check `docs/troubleshooting.md` for CAS login issues and Playwright debugging.

---

## License

This project is licensed under the MIT License. See `LICENSE` for details.
