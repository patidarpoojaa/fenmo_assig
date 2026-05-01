from __future__ import annotations

import socket
import threading
import time

import requests
import uvicorn

from backend.main import create_app


HOST = "127.0.0.1"
STARTUP_TIMEOUT_SECONDS = 8

_lock = threading.Lock()
_api_url: str | None = None
_server: uvicorn.Server | None = None
_thread: threading.Thread | None = None


def _is_healthy(base_url: str) -> bool:
    try:
        response = requests.get(f"{base_url}/health", timeout=1)
        return response.status_code == 200 and response.json().get("status") == "ok"
    except requests.RequestException:
        return False


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((HOST, 0))
        return int(sock.getsockname()[1])


def ensure_embedded_api() -> str:
    global _api_url, _server, _thread

    if _api_url and _is_healthy(_api_url):
        return _api_url

    with _lock:
        if _api_url and _is_healthy(_api_url):
            return _api_url

        port = _find_free_port()
        base_url = f"http://{HOST}:{port}"
        config = uvicorn.Config(
            create_app(),
            host=HOST,
            port=port,
            log_level="warning",
            access_log=False,
        )
        _server = uvicorn.Server(config)
        _thread = threading.Thread(
            target=_server.run,
            name="embedded-expense-api",
            daemon=True,
        )
        _thread.start()

        deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            if _is_healthy(base_url):
                _api_url = base_url
                return base_url
            time.sleep(0.2)

    raise RuntimeError("The embedded FastAPI server did not start in time.")
