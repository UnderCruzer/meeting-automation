"""Run the private API, the public web server and (optionally) the Slack bot together.

API and web are required: if either exits, the container stops. The Slack bot
(calendar → DM → recording approval) runs only when SLACK_BOT_TOKEN and SLACK_APP_TOKEN
are set, and is restarted on its own if it crashes.
"""
import os
import signal
import subprocess
import sys
import threading
import time
import urllib.request


_PROVIDER_SECRETS = ("ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GROQ_API_KEY", "OPENAI_API_KEY",
                     "ADMIN_PASSWORD", "WORKSPACE_PASSWORD")


def _env_without(names):
    return {key: value for key, value in os.environ.items() if key not in names}


def _bot_env():
    env = _env_without(_PROVIDER_SECRETS + ("BACKEND_API_KEY",))
    public_url = os.environ.get("PUBLIC_URL") or os.environ.get("RENDER_EXTERNAL_URL", "")
    env.update(
        PORT="3005",  # internal only (Microsoft sign-in routes); the platform routes just $PORT
        BACKEND_URL="http://127.0.0.1:8000",
        RECORDING_PAGE_URL=public_url or "http://localhost:" + os.environ.get("PORT", "7860"),
        ALERT_STORE_PATH="/app/data/sent_alerts.json",
    )
    return env


def main():
    provider = os.environ.get("LLM_PROVIDER", "").lower() or (
        "gemini" if os.environ.get("GEMINI_API_KEY") else "anthropic")
    llm_key = "GEMINI_API_KEY" if provider == "gemini" else "ANTHROPIC_API_KEY"
    for name in ("BACKEND_API_KEY", llm_key):
        if not os.environ.get(name):
            raise RuntimeError(f"Missing required secret: {name}")
    if not (os.environ.get("ADMIN_PASSWORD") or os.environ.get("WORKSPACE_PASSWORD")):
        print("warning: ADMIN_PASSWORD not set — startup fails unless users already exist", file=sys.stderr)
    stopped = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stopped.set())
    signal.signal(signal.SIGINT, lambda *_: stopped.set())
    children = []
    bot = None
    try:
        api = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000"],
            cwd="/app/backend",
        )
        children.append(api)
        deadline = time.monotonic() + 60
        while True:
            if stopped.is_set():
                return 0
            if api.poll() is not None:
                raise RuntimeError("Backend exited before becoming ready")
            try:
                with urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=2) as res:
                    if res.status == 200:
                        break
            except OSError:
                pass
            if time.monotonic() > deadline:
                raise RuntimeError("Backend startup timed out")
            stopped.wait(1)
        web_env = _env_without(_PROVIDER_SECRETS + ("SLACK_BOT_TOKEN", "SLACK_APP_TOKEN", "CALENDAR_ICS_URLS",
                                                     "AZURE_CLIENT_SECRET"))
        # Render/Cloud Run inject PORT; Hugging Face uses the fixed app_port 7860.
        web_env.update(PORT=os.environ.get("PORT", "7860"), HOSTNAME="0.0.0.0")
        children.append(subprocess.Popen(["node", "server.js"], cwd="/app/frontend", env=web_env))

        bot = None
        bot_backoff = 5.0
        bot_enabled = bool(os.environ.get("SLACK_BOT_TOKEN") and os.environ.get("SLACK_APP_TOKEN"))
        if not bot_enabled:
            print("info: Slack bot disabled (set SLACK_BOT_TOKEN and SLACK_APP_TOKEN to enable)", file=sys.stderr)
        next_bot_start = 0.0
        while not stopped.wait(1):
            if any(child.poll() is not None for child in children):
                return 1
            if bot_enabled and (bot is None or bot.poll() is not None) and time.monotonic() >= next_bot_start:
                if bot is not None:
                    print(f"warning: Slack bot exited ({bot.returncode}); restarting", file=sys.stderr)
                    bot_backoff = min(bot_backoff * 2, 300.0)
                bot = subprocess.Popen(["node", "src/app.js"], cwd="/app/slack-bot", env=_bot_env())
                next_bot_start = time.monotonic() + bot_backoff
        return 0
    finally:
        if bot is not None:
            children.append(bot)
        for child in children:
            if child.poll() is None:
                child.terminate()
        for child in children:
            try:
                child.wait(timeout=15)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()


if __name__ == "__main__":
    sys.exit(main())
