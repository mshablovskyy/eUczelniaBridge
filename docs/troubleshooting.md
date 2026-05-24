# Troubleshooting Guide

This guide describes common failure modes, diagnostic procedures, and self-correction actions for the `euczelnia-bridge` package. It covers both CAS login automation (Playwright) and daemon runtime issues.

---

## 1. Diagnostic Directories & Files

All runtime, log, and diagnostic files are stored in the configured `data_dir` (default: `./data`). When a failure occurs, immediately inspect the following files:

- **`data/daemon.log`**: The main revolving daemon log. Contains polling cycles, in-chat command responses, AI completion prompts, and subprocess logs.
- **`data/daemon_status.json`**: The daemon heartbeat file. Contains current runtime status, active mode, last event, and timestamp.
- **`data/debug_login/`**: Output folder containing diagnostics for automated login failures:
  - `error.log`: Python CAS login traceback.
  - `console.log`: Chrome JS console outputs.
  - `page_source.html`: HTML content of the login page at the moment of failure.
  - `screenshot.png`: Visual snapshot of the browser at the moment of failure.

---

## 2. CAS Login & Authentication Failures

If `login/login.py` fails, check the files in `data/debug_login/` and classify the issue into one of these categories:

### Type A: Incorrect Credentials
- **Symptom**: `page_source.html` contains CAS validation warnings (e.g., `"Dostarczone dane uwierzytelniania nie mogą zostać uznane za poprawne"`).
- **Action**: Stop retry loops immediately to avoid locking the account. Update the credentials in `config/.env` and re-run.

### Type B: MFA or CAPTCHA Challenge
- **Symptom**: Redirection stops on an OTP/validation challenge screen. `page_source.html` contains form fields named `token`, `otp`, or `captcha`.
- **Action**: Run the login script once in headed mode to complete the verification challenge manually:
  ```bash
  ./venv/bin/python login/login.py --headed --output data/session.json
  ```

### Type C: Portal Downtime or Network Outages
- **Symptom**: `error.log` contains network timeout errors (`net::ERR_CONNECTION_TIMED_OUT` or `net::ERR_NAME_NOT_RESOLVED`).
- **Action**: Verify portal access manually via a standard web browser. If down, wait and retry authentication using backoff schedules.

### Type D: Page Selector Shift (CAS layout updates)
- **Symptom**: Timeout errors waiting for DOM selectors like `#username`, `#password`, or `[name="submitBtn"]`.
- **Action**: Inspect `page_source.html` textually to identify the new field selectors, edit `login/login.py` to match the updated selectors, and run again.

---

## 3. Daemon Runtime Failures

### Moodle Session Key Expiry (Auth Errors)
- **Symptom**: The Moodle API requests return code 403 or invalid session payload. The daemon logs say:
  `Session key or cookie expired. Launching login.py subprocess...`
- **Behavior**: The daemon automatically spawns `login/login.py` to acquire a fresh session, updates its cookies in memory, and resumes operations.
- **Failure state**: If the login subprocess fails, the daemon writes `status: auth_failed` to `daemon_status.json` and shuts down.
- **Resolution**: Check `data/debug_login/` logs. Ensure `config/.env` credentials have not expired or changed.

### AI Gateway Connection Failures
- **Symptom**: Polled user messages receive responses starting with:
  `❌ AI Error: [error details]`
- **Causes**:
  - The Ollama dev server or remote LLM endpoint is not running.
  - Incorrect `base_url` or `api_key` configured in `config/config.json`.
- **Resolution**: Test the API endpoint using curl:
  ```bash
  curl http://localhost:11434/v1/chat/completions \
    -H "Content-Type: application/json" \
    -d '{"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "test"}]}'
  ```
  Ensure the values returned match your config specifications.

### SQLite Database Corruption
- **Symptom**: Operational failures or SQL errors logged when fetching message history.
- **Resolution**: Since database history is used as transient memory cache only:
  1. Terminate the daemon process.
  2. Backup and remove `data/messenger.db`.
  3. Start the daemon; it will automatically recreate the database schema and initialize a clean database file.

### Playwright Chromium Binary Missing
- **Symptom**: Running `login.py` results in a Playwright error indicating that the browser executable was not found.
- **Resolution**: Reinstall Playwright browsers:
  ```bash
  ./venv/bin/playwright install chromium
  ```
