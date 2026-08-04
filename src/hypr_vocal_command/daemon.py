"""Warm, long-running Unix-domain-socket daemon.

Replaces the Phase 6 CLI's per-invocation cold start (reload whisper, reload the LLM
client, rebuild prompts every single time) with resources built once at startup and
reused for the life of the process -- this is what finally makes the Phase 4 cache
observable, and removes the ~177ms whisper model-load cost measured during the
pre-Phase-7 review from every request.

Security model, built in from the start rather than deferred:
- The socket is created under a restrictive umask *and* explicitly chmod'd 0600
  immediately after binding, so only this user's own processes can ever connect --
  there is no window where it's briefly more permissive than that.
- Every accepted connection's peer UID is checked via SO_PEERCRED before its payload
  is trusted at all; a mismatch is rejected and logged, never processed.
- `registry.validate_startup()` runs at boot; the daemon refuses to start at all if a
  handler module wasn't imported (the exact footgun `handlers/__init__.py` warns about).

Concurrency model: a single microphone is an inherently exclusive resource -- there is
no meaningful way to service two overlapping voice commands at once. Rather than queue
a second request behind the first (which would silently start recording it late, or
confusingly interleave two speakers), a connection that arrives while one is already
in flight gets an immediate "busy" response.
"""

import asyncio
import json
import os
import signal
import socket
import struct
from pathlib import Path
from typing import Any

import httpx

from . import handlers  # populates the registry; also used directly below
from .audio.transcribe import load_model
from .audio.vad import SileroVAD
from .audio.vocabulary import build_command_vocabulary_prompt
from .config import Config, load_config
from .llm.cache import CachedClassifier
from .llm.client import OllamaClient
from .llm.prompts import build_system_prompt
from .pipeline import run_pipeline
from .registry import validate_startup
from .utils.notifier import notify
from .utils.telemetry import log_event

_PEERCRED_STRUCT = "3i"  # pid_t, uid_t, gid_t -- see unix(7) SO_PEERCRED

SUPPORTED_LANGUAGES = ("en", "ar")


def socket_path() -> Path:
    xdg_runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
    if not xdg_runtime_dir:
        raise RuntimeError(
            "XDG_RUNTIME_DIR is not set -- refusing to place the daemon socket "
            "somewhere with unclear permissions (e.g. /tmp)."
        )
    return Path(xdg_runtime_dir) / "hypr-vocal-command.sock"


def check_ollama_reachable(base_url: str, timeout: float = 3.0) -> None:
    """Raises if Ollama isn't reachable. Checked first, before the slow whisper/VAD
    model loading -- fails fast with a clear log line instead of starting up looking
    healthy and only failing on the first real voice command. Under systemd's
    `Restart=on-failure`, this also naturally handles boot-time startup-ordering
    (Ollama's own unit not being up yet) by retrying rather than wedging forever."""
    try:
        response = httpx.get(f"{base_url.rstrip('/')}/api/tags", timeout=timeout)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise RuntimeError(f"Ollama not reachable at {base_url}: {exc}") from exc


def _peer_uid(writer: asyncio.StreamWriter) -> int:
    sock = writer.get_extra_info("socket")
    creds = sock.getsockopt(
        socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize(_PEERCRED_STRUCT)
    )
    _pid, uid, _gid = struct.unpack(_PEERCRED_STRUCT, creds)
    return uid


class Daemon:
    def __init__(self, config: Config | None = None) -> None:
        validate_startup(handlers.EXPECTED_INTENTS)

        self.config = config or load_config()
        self._own_uid = os.getuid()
        self._busy = asyncio.Lock()

        # Warm resources: built once here, reused for every future connection.
        self._vad = SileroVAD()
        self._whisper_model = load_model()
        self._system_prompt = build_system_prompt()

        # Keyed by model name, not by language: English and Egyptian Arabic currently
        # share one model (see Config.model_ar), so this is normally a single warm
        # client rather than one per language. If the two are ever pointed at different
        # models, each still gets its own client without changing this code.
        self._classifiers: dict[str, CachedClassifier] = {}
        for language in SUPPORTED_LANGUAGES:
            model = self.config.model_for(language)
            if model not in self._classifiers:
                self._classifiers[model] = CachedClassifier(
                    OllamaClient(
                        model=model,
                        base_url=self.config.ollama_base_url,
                        timeout=self.config.llm_timeout_s,
                    )
                )
        self._vocabulary_prompts = {
            language: build_command_vocabulary_prompt(self.config, language)
            for language in SUPPORTED_LANGUAGES
        }

    def close(self) -> None:
        for classifier in self._classifiers.values():
            classifier.close()

    async def handle_connection(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            peer_uid = _peer_uid(writer)
            if peer_uid != self._own_uid:
                log_event(
                    {
                        "stage": "connection",
                        "ok": False,
                        "reason": "uid_mismatch",
                        "peer_uid": peer_uid,
                        "own_uid": self._own_uid,
                    }
                )
                return

            raw = await reader.readline()
            if not raw:
                return

            try:
                request = json.loads(raw)
            except json.JSONDecodeError:
                await self._respond(writer, {"ok": False, "message": "invalid JSON request"})
                return

            language = request.get("language", "en")
            if language not in SUPPORTED_LANGUAGES:
                message = f"unsupported language {language!r}"
                notify("hypr-vocal-command", message, urgency="critical")
                await self._respond(writer, {"ok": False, "message": message})
                return

            if self._busy.locked():
                # The production trigger (client.py) is fire-and-forget -- it doesn't
                # read this response at all, so without this notify() a hotkey press
                # made while another command is in flight would be dropped completely
                # silently, with no feedback that it didn't register.
                message = "Still busy with the previous command -- try again in a moment."
                notify("hypr-vocal-command", message)
                await self._respond(writer, {"ok": False, "message": message})
                return

            async with self._busy:
                result = await asyncio.get_running_loop().run_in_executor(
                    None, self._run_pipeline, language
                )
            await self._respond(writer, result)
        except Exception as exc:  # noqa: BLE001 -- never let one bad connection take the daemon down
            log_event(
                {"stage": "connection", "ok": False, "reason": "unexpected_error", "error": str(exc)}
            )
            try:
                await self._respond(writer, {"ok": False, "message": "internal error"})
            except Exception as respond_exc:  # noqa: BLE001 -- e.g. client already disconnected
                log_event(
                    {
                        "stage": "connection",
                        "ok": False,
                        "reason": "failed_to_send_error_response",
                        "error": str(respond_exc),
                    }
                )
        finally:
            writer.close()

    async def _respond(self, writer: asyncio.StreamWriter, payload: dict[str, Any]) -> None:
        # The production trigger (client.py) is deliberately fire-and-forget: it sends
        # its request and closes immediately, without waiting for this response at all
        # (see client.py's docstring). By the time a real pipeline run finishes, seconds
        # later, that connection is long gone -- this is the *expected*, benign outcome
        # of that design, not a bug, so it must never be logged as an "unexpected_error"
        # the way it would if left to propagate to handle_connection's generic handler.
        try:
            writer.write((json.dumps(payload) + "\n").encode())
            await writer.drain()
        except (ConnectionError, BrokenPipeError):
            log_event({"stage": "connection", "reason": "client_disconnected_before_response"})

    def _run_pipeline(self, language: str) -> dict[str, Any]:
        result = run_pipeline(
            vad=self._vad,
            whisper_model=self._whisper_model,
            classifier=self._classifiers[self.config.model_for(language)],
            system_prompt=self._system_prompt,
            vocabulary_prompt=self._vocabulary_prompts[language],
            config=self.config,
            language=language,
        )
        return {
            "ok": result.ok,
            "message": result.message,
            "transcript": result.transcript,
            "intent": result.intent,
            "confidence": result.confidence,
            "transcribe_ms": result.transcribe_ms,
            "llm_latency_ms": result.llm_latency_ms,
            "total_ms": result.total_ms,
        }


async def run_daemon(config: Config | None = None) -> None:
    config = config or load_config()
    check_ollama_reachable(config.ollama_base_url)  # fail fast, before the slow model loads

    daemon = Daemon(config)
    path = socket_path()
    if path.exists():
        path.unlink()  # stale socket from an unclean shutdown -- safe to remove and rebind

    old_umask = os.umask(0o077)  # belt-and-suspenders: restrictive even before the chmod
    try:
        server = await asyncio.start_unix_server(daemon.handle_connection, path=str(path))
    finally:
        os.umask(old_umask)
    os.chmod(path, 0o600)

    print(f"Listening on {path}", flush=True)

    # `systemctl stop` sends SIGTERM (not SIGINT/KeyboardInterrupt) -- without an explicit
    # handler here, Python's default SIGTERM action kills the process immediately and skips
    # the `finally` cleanup below, leaving a stale socket file for the *next* start to find.
    # Registering both makes shutdown behave identically either way.
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    try:
        async with server:
            await stop_event.wait()
    finally:
        daemon.close()
        if path.exists():
            path.unlink()
