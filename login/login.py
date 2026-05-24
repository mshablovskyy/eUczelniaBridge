#!/usr/bin/env python3
import asyncio
import argparse
import json
import os
import sys
import traceback
from pathlib import Path
from playwright.async_api import async_playwright
from dotenv import load_dotenv

# Load environment variables from .env file in the config/ directory if present
package_root = Path(__file__).resolve().parent.parent
dotenv_paths = [
    package_root / "config" / ".env",
    Path.cwd() / "config" / ".env",
    Path.cwd() / ".env"
]
for dp in dotenv_paths:
    if dp.exists():
        load_dotenv(dotenv_path=dp)
        break
else:
    load_dotenv()


class EuczelniaAuthenticator:
    LOGIN_URL = "https://logowanie.uek.krakow.pl/cas/login?service=https%3A%2F%2Fe-uczelnia.uek.krakow.pl%2Flogin%2Findex.php%3FauthCAS%3DCAS"
    DASHBOARD_URL = "https://e-uczelnia.uek.krakow.pl/"

    def __init__(self, username=None, password=None, headless=True, timeout=30, data_dir=None):
        """
        Initialize the authenticator.
        :param username: CAS username (falls back to EUCZELNIA_USERNAME env variable)
        :param password: CAS password (falls back to EUCZELNIA_PASSWORD env variable)
        :param headless: Run browser headlessly
        :param timeout: Action timeout in seconds
        :param data_dir: Directory where runtime/diagnostic files should be written
        """
        self.username = username or os.getenv("EUCZELNIA_USERNAME")
        self.password = password or os.getenv("EUCZELNIA_PASSWORD")
        self.headless = headless
        self.timeout_ms = timeout * 1000
        self.data_dir = Path(data_dir) if data_dir else None
        self.console_logs = []

    async def authenticate(self) -> dict:
        """
        Runs browser automation to authenticate, then extracts cookies and M.cfg parameters.
        Returns a session dictionary compatible with SessionData.
        """
        if not self.username or not self.password:
            raise ValueError(
                "Credentials missing. Provide username and password via CLI, constructor, "
                "or define EUCZELNIA_USERNAME and EUCZELNIA_PASSWORD in your .env file."
            )

        async with async_playwright() as p:
            print(f"Launching Chromium (headless={self.headless})...")
            browser = await p.chromium.launch(headless=self.headless)
            context = await browser.new_context(viewport={"width": 1280, "height": 800})
            page = await context.new_page()

            # Record console messages for error diagnostics
            self.console_logs = []
            page.on("console", lambda msg: self.console_logs.append(f"[{msg.type}] {msg.text}"))

            try:
                print(f"Navigating to CAS login portal...")
                await page.goto(self.LOGIN_URL, timeout=self.timeout_ms)

                print("Filling credentials...")
                # Fill username
                await page.wait_for_selector("#username", timeout=self.timeout_ms)
                await page.fill("#username", self.username)

                # Fill password
                await page.wait_for_selector("#password", timeout=self.timeout_ms)
                await page.fill("#password", self.password)

                print("Submitting login form...")
                # Click the submit button and wait for navigation back to e-uczelnia
                async with page.expect_navigation(timeout=self.timeout_ms):
                    await page.click("[name='submitBtn']")

                print("Verifying authentication state on e-uczelnia...")
                # Wait until Moodle config object (M.cfg) is fully initialized on the page
                await page.wait_for_function(
                    "() => typeof M !== 'undefined' && typeof M.cfg !== 'undefined' && typeof M.cfg.sesskey !== 'undefined'",
                    timeout=self.timeout_ms
                )

                print("Extracting Moodle global session configuration...")
                # Extract sesskey and userid (supporting both userId and userid keys in M.cfg)
                m_cfg = await page.evaluate("() => ({sesskey: M.cfg.sesskey, userid: M.cfg.userId || M.cfg.userid})")
                
                if not m_cfg.get("sesskey"):
                    raise RuntimeError("Failed to extract sesskey from M.cfg")

                print("Capturing session cookies...")
                # Extract session cookies
                cookies_list = await context.cookies("https://e-uczelnia.uek.krakow.pl")
                moodle_cookies = {}
                for c in cookies_list:
                    if c["name"].startswith("MoodleSession"):
                        moodle_cookies[c["name"]] = c["value"]

                if not moodle_cookies:
                    # Fallback to checking all cookies in context in case domain matching differed
                    all_cookies = await context.cookies()
                    for c in all_cookies:
                        if c["name"].startswith("MoodleSession"):
                            moodle_cookies[c["name"]] = c["value"]

                if not moodle_cookies:
                    raise RuntimeError("Failed to capture any MoodleSession cookies.")

                # Structure final session data output
                session_data = {
                    "sesskey": m_cfg["sesskey"],
                    "cookies": moodle_cookies,
                    "user_id": int(m_cfg["userid"]) if m_cfg.get("userid") else None
                }

                print("Authentication successful!")
                return session_data

            except Exception as e:
                print(f"Error during authentication: {e}", file=sys.stderr)
                await self._dump_diagnostics(page, e)
                raise
            finally:
                await context.close()
                await browser.close()

    async def _dump_diagnostics(self, page, error):
        """
        Dumps diagnostic logs, page source HTML, and visual screenshots to assist debugging.
        """
        if self.data_dir:
            debug_dir = self.data_dir / "debug_login"
        else:
            debug_dir = package_root / "data" / "debug_login"
            if not debug_dir.parent.exists():
                debug_dir = Path("debug_login")

        debug_dir.mkdir(parents=True, exist_ok=True)
        print(f"Writing diagnostic logs to '{debug_dir.resolve()}'...")

        # 1. Save Stacktrace
        with open(debug_dir / "error.log", "w", encoding="utf-8") as f:
            f.write(f"Exception: {type(error).__name__}: {error}\n\n")
            traceback.print_exc(file=f)

        # 2. Save Console Logs
        with open(debug_dir / "console.log", "w", encoding="utf-8") as f:
            f.write("\n".join(self.console_logs))

        # 3. Save Page HTML Source
        try:
            html = await page.content()
            with open(debug_dir / "page_source.html", "w", encoding="utf-8") as f:
                f.write(html)
        except Exception as html_err:
            print(f"Could not save page HTML source: {html_err}", file=sys.stderr)

        # 4. Save Screenshot
        try:
            await page.screenshot(path=debug_dir / "screenshot.png")
            print(f"Diagnostic screenshot saved to {debug_dir / 'screenshot.png'}")
        except Exception as ss_err:
            print(f"Could not capture diagnostic screenshot: {ss_err}", file=sys.stderr)


async def main():
    parser = argparse.ArgumentParser(
        description="Securely log in to UEK eUczelnia CAS and extract active Moodle session credentials."
    )
    parser.add_argument(
        "--username", "-u",
        help="CAS Username (overrides EUCZELNIA_USERNAME env variable)"
    )
    parser.add_argument(
        "--password", "-p",
        help="CAS Password (overrides EUCZELNIA_PASSWORD env variable)"
    )
    parser.add_argument(
        "--output", "-o",
        help="Output path to save the session JSON (outputs to stdout if not specified)"
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Run browser in headed mode (runs headless by default)"
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="Timeout in seconds for operations (default: 30)"
    )
    parser.add_argument(
        "--data-dir",
        help="Custom data directory to store diagnostics"
    )

    args = parser.parse_args()

    # Load credentials interactively if not provided via args/env
    username = args.username or os.getenv("EUCZELNIA_USERNAME")
    password = args.password or os.getenv("EUCZELNIA_PASSWORD")

    if not username:
        username = input("Enter your CAS Username: ").strip()
    if not password:
        import getpass
        password = getpass.getpass("Enter your CAS Password: ").strip()

    authenticator = EuczelniaAuthenticator(
        username=username,
        password=password,
        headless=not args.headed,
        timeout=args.timeout,
        data_dir=args.data_dir
    )

    try:
        session_data = await authenticator.authenticate()
        json_output = json.dumps(session_data, indent=2)

        if args.output:
            out_path = Path(args.output)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json_output, encoding="utf-8")
            print(f"Session data successfully written to: {out_path.resolve()}")
        else:
            print("\n--- Session Data JSON ---")
            print(json_output)
            print("-------------------------")

    except Exception:
        sys.exit(1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nAborted.")
        sys.exit(1)
