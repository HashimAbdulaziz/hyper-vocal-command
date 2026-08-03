from pathlib import Path

from hypr_vocal_command.appscan import _parse_desktop_file, discover_apps

FIXTURES = Path(__file__).parent / "fixtures" / "desktop"


def test_native_app_is_parsed(monkeypatch):
    monkeypatch.setattr(
        "hypr_vocal_command.appscan.shutil.which",
        lambda name: "/usr/bin/testnativeapp" if name == "/usr/bin/testnativeapp" else None,
    )
    monkeypatch.setattr(
        "hypr_vocal_command.appscan._reverse_rpm_lookup", lambda path: "testnativeapp-pkg"
    )

    entry = _parse_desktop_file(FIXTURES / "native-app.desktop")

    assert entry is not None
    assert entry.manager == "native"
    assert entry.identifier == "/usr/bin/testnativeapp"
    assert entry.package_name == "testnativeapp-pkg"
    assert "test native app" in entry.surface_forms
    assert "testnativeapp" in entry.surface_forms  # from the binary basename
    assert "%f" not in " ".join(entry.surface_forms)  # field code was stripped


def test_env_wrapper_is_unwrapped_for_naming_but_full_argv_preserved(monkeypatch):
    def fake_which(name):
        if name in ("env", "/usr/bin/envwrappedtarget"):
            return f"/usr/bin/{Path(name).name}"
        return None

    monkeypatch.setattr("hypr_vocal_command.appscan.shutil.which", fake_which)
    monkeypatch.setattr(
        "hypr_vocal_command.appscan._reverse_rpm_lookup", lambda path: "envwrappedtarget-pkg"
    )

    entry = _parse_desktop_file(FIXTURES / "env-wrapper-app.desktop")

    assert entry is not None
    assert entry.manager == "native"
    # full argv preserved for execution, not just the "env" wrapper binary
    assert entry.identifier == "env FOO=bar /usr/bin/envwrappedtarget --flag"
    # package name attributed to the real target, not the wrapper
    assert entry.package_name == "envwrappedtarget-pkg"
    assert "envwrappedtarget" in entry.surface_forms
    assert "env" not in entry.surface_forms


def test_native_app_with_missing_binary_is_skipped(monkeypatch):
    monkeypatch.setattr("hypr_vocal_command.appscan.shutil.which", lambda name: None)

    entry = _parse_desktop_file(FIXTURES / "native-app.desktop")

    assert entry is None


def test_flatpak_app_id_extracted():
    entry = _parse_desktop_file(FIXTURES / "flatpak-app.desktop")

    assert entry is not None
    assert entry.manager == "flatpak"
    assert entry.identifier == "org.example.TestFlatpakApp"
    assert entry.package_name is None


def test_hidden_app_is_skipped():
    assert _parse_desktop_file(FIXTURES / "hidden-app.desktop") is None


def test_non_application_type_is_skipped():
    assert _parse_desktop_file(FIXTURES / "not-an-application.desktop") is None


def test_discover_apps_scans_directory_and_dedupes_by_key(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "hypr_vocal_command.appscan.shutil.which",
        lambda name: name if name.startswith("/") else f"/usr/bin/{name}",
    )
    monkeypatch.setattr("hypr_vocal_command.appscan._reverse_rpm_lookup", lambda path: None)

    (tmp_path / "app1.desktop").write_text(
        "[Desktop Entry]\nType=Application\nName=App One\nExec=app1\n"
    )
    (tmp_path / "app2.desktop").write_text(
        "[Desktop Entry]\nType=Application\nName=App Two\n"
        "Exec=flatpak run org.example.AppTwo\n"
    )
    (tmp_path / "not-a-desktop-file.txt").write_text("ignored")

    entries = discover_apps([tmp_path])

    assert {e.key for e in entries} == {"app1", "app2"}
    by_key = {e.key: e for e in entries}
    assert by_key["app2"].manager == "flatpak"
    assert by_key["app2"].identifier == "org.example.AppTwo"


def test_discover_apps_ignores_missing_directories():
    assert discover_apps([Path("/no/such/directory")]) == []
