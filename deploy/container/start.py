"""Run the private API and public web server together; stop if either fails."""
import os
import signal
import subprocess
import sys
import threading
import time
import urllib.request


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
        web_env = {key: value for key, value in os.environ.items()
                   if key not in ("ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GROQ_API_KEY", "OPENAI_API_KEY",
                                  "ADMIN_PASSWORD", "WORKSPACE_PASSWORD")}
        # Render/Cloud Run inject PORT; Hugging Face uses the fixed app_port 7860.
        web_env.update(PORT=os.environ.get("PORT", "7860"), HOSTNAME="0.0.0.0")
        children.append(subprocess.Popen(["node", "server.js"], cwd="/app/frontend", env=web_env))
        while not stopped.wait(1):
            if any(child.poll() is not None for child in children):
                return 1
        return 0
    finally:
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
