import asyncio
import json
import struct

import httpx
import pytest
import respx

from hypr_vocal_command import daemon as daemon_module
from hypr_vocal_command.daemon import Daemon, _peer_uid, check_ollama_reachable, socket_path


@pytest.fixture(autouse=True)
def _isolate_notifications(monkeypatch):
    # Never send real desktop notifications during tests -- handle_connection's
    # busy/unsupported-language paths now call notify() directly.
    monkeypatch.setattr(daemon_module, "notify", lambda *a, **k: None)


def _peercred_bytes(uid: int, pid: int = 1234, gid: int = 1000) -> bytes:
    return struct.pack("3i", pid, uid, gid)


class _FakeSocket:
    def __init__(self, uid: int) -> None:
        self._uid = uid

    def getsockopt(self, level, optname, buflen):
        return _peercred_bytes(self._uid)


class _FakeWriter:
    def __init__(self, peer_uid: int, disconnected: bool = False) -> None:
        self._socket = _FakeSocket(peer_uid)
        self.written: list[bytes] = []
        self.closed = False
        self._disconnected = disconnected

    def get_extra_info(self, name):
        assert name == "socket"
        return self._socket

    def write(self, data: bytes) -> None:
        self.written.append(data)

    async def drain(self) -> None:
        if self._disconnected:
            raise ConnectionResetError("client already disconnected")

    def close(self) -> None:
        self.closed = True

    def last_response(self) -> dict:
        assert self.written, "nothing was written back"
        return json.loads(self.written[-1])


class _FakeReader:
    def __init__(self, line: bytes) -> None:
        self._line = line

    async def readline(self) -> bytes:
        return self._line


def _bare_daemon(**attrs) -> Daemon:
    # Bypasses __init__ deliberately -- constructing a real Daemon loads whisper/VAD/
    # Ollama, which is exactly the heavy, service-dependent work these tests don't need
    # to touch to exercise the connection-handling/security logic.
    instance = object.__new__(Daemon)
    instance._own_uid = attrs.get("own_uid", 1000)
    instance._busy = attrs.get("busy", asyncio.Lock())
    instance._run_pipeline = attrs.get("run_pipeline", lambda language: {"ok": True})
    return instance


def test_socket_path_requires_xdg_runtime_dir(monkeypatch):
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    with pytest.raises(RuntimeError):
        socket_path()


def test_socket_path_uses_xdg_runtime_dir(monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/user/1000")
    assert socket_path() == daemon_module.Path("/run/user/1000/hypr-vocal-command.sock")


@respx.mock
def test_check_ollama_reachable_succeeds_when_ollama_responds():
    respx.get("http://localhost:11434/api/tags").mock(return_value=httpx.Response(200))
    check_ollama_reachable("http://localhost:11434")  # must not raise


@respx.mock
def test_check_ollama_reachable_raises_when_ollama_is_down():
    respx.get("http://localhost:11434/api/tags").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(RuntimeError, match="not reachable"):
        check_ollama_reachable("http://localhost:11434")


def test_peer_uid_reads_so_peercred():
    writer = _FakeWriter(peer_uid=4242)
    assert _peer_uid(writer) == 4242


def test_rejects_connection_from_mismatched_uid(monkeypatch):
    logged = []
    monkeypatch.setattr(daemon_module, "log_event", lambda event: logged.append(event))

    daemon = _bare_daemon(own_uid=1000)
    writer = _FakeWriter(peer_uid=1001)
    reader = _FakeReader(b'{"language": "en"}\n')

    asyncio.run(daemon.handle_connection(reader, writer))

    assert writer.written == []  # rejected before any payload is trusted or answered
    assert writer.closed is True
    assert logged[0]["reason"] == "uid_mismatch"
    assert logged[0]["peer_uid"] == 1001


def test_rejects_invalid_json():
    daemon = _bare_daemon()
    writer = _FakeWriter(peer_uid=1000)
    reader = _FakeReader(b"not json at all\n")

    asyncio.run(daemon.handle_connection(reader, writer))

    assert "invalid JSON" in writer.last_response()["message"]


def test_rejects_unsupported_language():
    daemon = _bare_daemon()
    writer = _FakeWriter(peer_uid=1000)
    reader = _FakeReader(b'{"language": "fr"}\n')

    asyncio.run(daemon.handle_connection(reader, writer))

    response = writer.last_response()
    assert response["ok"] is False
    assert "fr" in response["message"]


def test_arabic_is_an_accepted_language():
    # Phase 9: "ar" used to be rejected outright; it now routes through the pipeline.
    languages_seen = []
    daemon = _bare_daemon(
        run_pipeline=lambda language: languages_seen.append(language) or {"ok": True}
    )
    writer = _FakeWriter(peer_uid=1000)
    reader = _FakeReader(b'{"language": "ar"}\n')

    asyncio.run(daemon.handle_connection(reader, writer))

    assert languages_seen == ["ar"]
    assert writer.last_response()["ok"] is True


def test_responds_busy_when_already_processing_a_request():
    async def scenario():
        busy = asyncio.Lock()
        await busy.acquire()  # simulate another connection's pipeline already in flight
        daemon = _bare_daemon(busy=busy)
        writer = _FakeWriter(peer_uid=1000)
        reader = _FakeReader(b'{"language": "en"}\n')

        await daemon.handle_connection(reader, writer)

        response = writer.last_response()
        assert response["ok"] is False
        assert "busy" in response["message"]

    asyncio.run(scenario())


def test_successful_request_runs_pipeline_and_responds_with_its_result():
    expected = {"ok": True, "message": "Opened terminal (kitty).", "transcript": "open a terminal"}
    daemon = _bare_daemon(run_pipeline=lambda language: expected)
    writer = _FakeWriter(peer_uid=1000)
    reader = _FakeReader(b'{"language": "en"}\n')

    asyncio.run(daemon.handle_connection(reader, writer))

    assert writer.last_response() == expected


def test_client_disconnect_before_response_is_not_logged_as_an_error(monkeypatch):
    # The production trigger (client.py) is fire-and-forget: it closes its connection
    # immediately after sending, long before the pipeline finishes. This must be treated
    # as the expected, benign outcome it is -- never as an "unexpected_error", which
    # would make every single real hotkey press look like a bug in the logs.
    logged = []
    monkeypatch.setattr(daemon_module, "log_event", lambda event: logged.append(event))

    expected = {"ok": True, "message": "Opened terminal (kitty)."}
    daemon = _bare_daemon(run_pipeline=lambda language: expected)
    writer = _FakeWriter(peer_uid=1000, disconnected=True)
    reader = _FakeReader(b'{"language": "en"}\n')

    asyncio.run(daemon.handle_connection(reader, writer))  # must not raise

    assert [e["reason"] for e in logged] == ["client_disconnected_before_response"]


def test_unexpected_exception_does_not_propagate_and_reports_internal_error(monkeypatch):
    monkeypatch.setattr(daemon_module, "log_event", lambda event: None)

    def _boom(language):
        raise RuntimeError("something broke")

    daemon = _bare_daemon(run_pipeline=_boom)
    writer = _FakeWriter(peer_uid=1000)
    reader = _FakeReader(b'{"language": "en"}\n')

    asyncio.run(daemon.handle_connection(reader, writer))  # must not raise

    assert writer.last_response()["message"] == "internal error"
