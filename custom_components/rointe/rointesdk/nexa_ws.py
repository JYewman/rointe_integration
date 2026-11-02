"""Persistent Firebase WebSocket connection for Nexa devices."""

from __future__ import annotations

import json
import logging
import ssl
import threading
import time
from typing import Any, Callable, Dict, Optional

LOGGER = logging.getLogger(__name__)

# Firebase drops idle sockets; the Nexa web app pings every 25 seconds.
KEEPALIVE_INTERVAL_SECONDS = 25
# No traffic at all (including keep-alive replies) for this long means the
# socket is dead even if it was never closed, so it gets renewed.
STALE_AFTER_SECONDS = 300
CONNECT_TIMEOUT_SECONDS = 5
AUTH_TIMEOUT_SECONDS = 5
REQUEST_TIMEOUT_SECONDS = 8


class NexaWebSocket:
    """Single long-lived, authenticated Firebase WebSocket.

    Reads and writes share this connection instead of opening a new socket per
    request. A background thread sends keep-alives and renews the connection
    when it goes stale; any request that finds it dead renews it first.
    """

    def __init__(self, url: str, token_provider: Callable[[], Optional[str]]) -> None:
        self._url = url
        self._token_provider = token_provider

        self._ws: Any = None
        self._ws_thread: Optional[threading.Thread] = None
        self._connected = threading.Event()
        self._authed_token: Optional[str] = None
        self._last_message_time = 0.0

        self._lock = threading.RLock()  # serialises connect/renew/close
        self._pending: Dict[int, Dict[str, Any]] = {}
        self._pending_lock = threading.Lock()
        self._next_rid = 0

        self._stop = threading.Event()
        self._keepalive_thread: Optional[threading.Thread] = None

    # -------------------- public --------------------

    def request(self, action: str, body: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Send one Firebase request and return its response body ("b").

        Returns None if the connection could not be established or no response
        arrived in time. The caller decides whether to retry.
        """
        for attempt in range(2):
            if not self._ensure_connected():
                return None
            response = self._send_and_wait(action, body)
            if response is not None:
                return response
            if attempt == 0:
                LOGGER.debug("Nexa WebSocket request %s timed out, renewing connection", action)
                with self._lock:
                    self._renew()
        return None

    def invalidate_auth(self) -> None:
        """Force re-authentication on the next request (e.g. after token refresh)."""
        with self._lock:
            self._authed_token = None

    def close(self) -> None:
        """Stop the keep-alive thread and close the socket."""
        self._stop.set()
        with self._lock:
            self._close_socket()
        if self._keepalive_thread and self._keepalive_thread.is_alive():
            self._keepalive_thread.join(timeout=2)
        self._keepalive_thread = None

    # -------------------- connection --------------------

    def _is_alive(self) -> bool:
        return (
            self._ws is not None
            and self._connected.is_set()
            and time.monotonic() - self._last_message_time < STALE_AFTER_SECONDS
        )

    def _ensure_connected(self) -> bool:
        """Connect, renew a stale socket, or re-auth if the token changed."""
        token = self._token_provider()
        if not token:
            return False

        with self._lock:
            if self._is_alive() and self._authed_token == token:
                return True
            return self._renew(token)

    def _renew(self, token: Optional[str] = None) -> bool:
        """Tear down any existing socket and open a fresh authenticated one.

        Caller must hold self._lock.
        """
        try:
            import websocket  # type: ignore
        except ImportError:
            LOGGER.error("websocket-client is required for Nexa devices.")
            return False

        token = token or self._token_provider()
        if not token:
            return False

        self._close_socket()
        self._stop.clear()

        opened = threading.Event()
        self._connected.clear()

        def on_open(ws):
            self._last_message_time = time.monotonic()
            self._connected.set()
            opened.set()

        def on_message(ws, message):
            self._last_message_time = time.monotonic()
            if message.strip() == "0":
                return  # keep-alive reply
            try:
                msg = json.loads(message)
            except ValueError:
                return
            if msg.get("t") != "d" or "d" not in msg:
                return
            data_block = msg["d"]
            req_id = data_block.get("r")
            if req_id is None or "b" not in data_block:
                return
            with self._pending_lock:
                waiter = self._pending.get(req_id)
            if waiter is not None:
                waiter["response"] = data_block["b"]
                waiter["event"].set()

        def on_error(ws, error):
            if error and "NoneType" not in str(error):
                LOGGER.debug("Nexa WebSocket error: %s", error)

        def on_close(ws, code, msg):
            # Only react if this is still the active socket; a renew may
            # already have replaced it.
            if ws is self._ws:
                self._connected.clear()
                self._fail_pending()
            opened.set()

        ws = websocket.WebSocketApp(
            self._url,
            on_open=on_open,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close,
        )
        self._ws = ws
        self._ws_thread = threading.Thread(
            target=lambda: ws.run_forever(sslopt={"cert_reqs": ssl.CERT_NONE}),
            daemon=True,
            name="rointe-nexa-ws",
        )
        self._ws_thread.start()

        if not opened.wait(timeout=CONNECT_TIMEOUT_SECONDS) or not self._connected.is_set():
            LOGGER.warning("Nexa WebSocket connection timeout")
            self._close_socket()
            return False

        auth = self._send_and_wait("auth", {"cred": token}, timeout=AUTH_TIMEOUT_SECONDS)
        if not auth or auth.get("s") != "ok":
            LOGGER.warning(
                "Nexa WebSocket auth failed (status=%s)", auth.get("s") if auth else None
            )
            self._close_socket()
            return False

        self._authed_token = token
        self._start_keepalive()
        LOGGER.debug("Nexa WebSocket connected and authenticated")
        return True

    def _close_socket(self) -> None:
        """Close the current socket. Caller must hold self._lock."""
        ws = self._ws
        self._ws = None
        self._authed_token = None
        self._connected.clear()
        self._fail_pending()
        if ws is not None:
            try:
                ws.close()
            except Exception:  # noqa: BLE001
                pass
        if self._ws_thread and self._ws_thread.is_alive():
            self._ws_thread.join(timeout=2)
        self._ws_thread = None

    # -------------------- requests --------------------

    def _send_and_wait(
        self, action: str, body: Dict[str, Any], timeout: float = REQUEST_TIMEOUT_SECONDS
    ) -> Optional[Dict[str, Any]]:
        ws = self._ws
        if ws is None:
            return None

        with self._pending_lock:
            self._next_rid += 1
            rid = self._next_rid
            waiter: Dict[str, Any] = {"event": threading.Event(), "response": None}
            self._pending[rid] = waiter

        try:
            ws.send(json.dumps({"t": "d", "d": {"r": rid, "a": action, "b": body}}))
        except Exception as err:  # noqa: BLE001
            LOGGER.debug("Nexa WebSocket send failed: %s", err)
            self._connected.clear()
            with self._pending_lock:
                self._pending.pop(rid, None)
            return None

        waiter["event"].wait(timeout=timeout)
        with self._pending_lock:
            self._pending.pop(rid, None)
        return waiter["response"]

    def _fail_pending(self) -> None:
        """Wake every waiter so callers don't sit out the full timeout."""
        with self._pending_lock:
            waiters = list(self._pending.values())
            self._pending.clear()
        for waiter in waiters:
            waiter["event"].set()

    # -------------------- keep-alive --------------------

    def _start_keepalive(self) -> None:
        if self._keepalive_thread and self._keepalive_thread.is_alive():
            return
        self._keepalive_thread = threading.Thread(
            target=self._keepalive_loop, daemon=True, name="rointe-nexa-ws-keepalive"
        )
        self._keepalive_thread.start()

    def _keepalive_loop(self) -> None:
        """Ping every 25 s; renew the socket if it has gone stale or dropped."""
        while not self._stop.wait(KEEPALIVE_INTERVAL_SECONDS):
            with self._lock:
                if self._ws is None:
                    continue  # nothing open; next request will connect
                if not self._is_alive():
                    LOGGER.info("Nexa WebSocket stale or closed, renewing connection")
                    self._renew()
                    continue
                try:
                    self._ws.send("0")
                except Exception as err:  # noqa: BLE001
                    LOGGER.debug("Nexa WebSocket keep-alive failed: %s", err)
                    self._connected.clear()
