import json
import socket
import threading

import pytest

from hypr_vocal_command import client as client_module


@pytest.fixture(autouse=True)
def _isolate_notifications(monkeypatch):
    monkeypatch.setattr(client_module, "_notify", lambda *a, **k: None)


def _run_fake_server(sock_path, ready: threading.Event, received: list):
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(sock_path)
    server.listen(1)
    server.settimeout(5)
    ready.set()
    try:
        conn, _ = server.accept()
        with conn:
            received.append(conn.recv(65536))
    finally:
        server.close()


def _start_fake_server(sock_path) -> tuple[threading.Thread, list]:
    received: list[bytes] = []
    ready = threading.Event()
    thread = threading.Thread(
        target=_run_fake_server, args=(sock_path, ready, received), daemon=True
    )
    thread.start()
    ready.wait(timeout=5)  # don't let the client connect before listen() is actually up
    return thread, received


def test_main_sends_expected_request_to_the_socket(tmp_path, monkeypatch):
    sock_path = str(tmp_path / "test.sock")
    monkeypatch.setattr(client_module, "_socket_path", lambda: sock_path)
    server_thread, received = _start_fake_server(sock_path)

    monkeypatch.setattr("sys.argv", ["hypr-vocal-command-trigger", "--lang", "en"])
    exit_code = client_module.main()
    server_thread.join(timeout=5)

    assert exit_code == 0
    assert json.loads(received[0]) == {"language": "en"}


def test_main_passes_through_lang_argument(tmp_path, monkeypatch):
    sock_path = str(tmp_path / "test.sock")
    monkeypatch.setattr(client_module, "_socket_path", lambda: sock_path)
    server_thread, received = _start_fake_server(sock_path)

    monkeypatch.setattr("sys.argv", ["hypr-vocal-command-trigger", "--lang", "ar"])
    client_module.main()
    server_thread.join(timeout=5)

    assert json.loads(received[0]) == {"language": "ar"}


def test_main_handles_missing_xdg_runtime_dir(monkeypatch):
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    monkeypatch.setattr("sys.argv", ["hypr-vocal-command-trigger"])

    assert client_module.main() == 1


def test_main_handles_daemon_not_running(tmp_path, monkeypatch):
    # A socket path that exists on disk but nothing is listening on it.
    sock_path = str(tmp_path / "nothing-here.sock")
    monkeypatch.setattr(client_module, "_socket_path", lambda: sock_path)
    monkeypatch.setattr("sys.argv", ["hypr-vocal-command-trigger"])

    assert client_module.main() == 1
