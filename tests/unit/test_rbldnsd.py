# Copyright 2025 Tony Meyer
# See LICENSE file for licensing details.

import ipaddress
import pathlib
import signal
import subprocess

import pytest

import rbldnsd


class _CompletedProcess:
    def __init__(self, stdout: str) -> None:
        self.stdout = stdout


def test_get_version_success(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        rbldnsd.subprocess,
        "run",
        lambda *a, **k: _CompletedProcess(
            "rbldnsd: rbl dns daemon version 1.0pre (snapshot 20210120)\n"
            "Usage is: rbldnsd options zonespec..."
        ),
    )
    assert rbldnsd.get_version() == "1.0pre (snapshot 20210120)"


def test_get_version_error(monkeypatch: pytest.MonkeyPatch):
    def raise_error(*a, **k):
        raise subprocess.CalledProcessError(1, "rbldnsd")

    monkeypatch.setattr(rbldnsd.subprocess, "run", raise_error)
    assert rbldnsd.get_version() is None


def test_install_calls_apt(monkeypatch: pytest.MonkeyPatch):
    calls: list[str] = []
    monkeypatch.setattr(rbldnsd.apt, "update", lambda: calls.append("update"))
    monkeypatch.setattr(rbldnsd.apt, "add_package", lambda name: calls.append(f"add:{name}"))
    assert rbldnsd.install()
    assert calls == ["update", "add:rbldnsd"]


def test_remove_calls_apt(monkeypatch: pytest.MonkeyPatch):
    calls: list[str] = []
    monkeypatch.setattr(rbldnsd.apt, "remove_package", lambda name: calls.append(name))
    rbldnsd.remove()
    assert calls == ["rbldnsd"]


def test_start_calls_systemd(monkeypatch: pytest.MonkeyPatch):
    enabled: list[str] = []
    started: list[str] = []
    monkeypatch.setattr(rbldnsd.systemd, "service_enable", lambda name: enabled.append(name))
    monkeypatch.setattr(rbldnsd.systemd, "service_start", lambda name: started.append(name))
    assert rbldnsd.start()
    assert enabled == ["rbldnsd"]
    assert started == ["rbldnsd"]


def test_restart_calls_systemd(monkeypatch: pytest.MonkeyPatch):
    restarted: list[str] = []
    monkeypatch.setattr(rbldnsd.systemd, "service_restart", lambda name: restarted.append(name))
    assert rbldnsd.restart()
    assert restarted == ["rbldnsd"]


def test_reload_zones(monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path):
    pidfile = tmp_path / "rbldnsd.pid"
    pidfile.write_text("12345")
    monkeypatch.setattr(rbldnsd, "PID_FILE", pidfile)
    called: dict[str, int] = {}

    def fake_kill(pid: int, sig: int) -> None:
        called["pid"] = pid
        called["sig"] = sig

    monkeypatch.setattr(rbldnsd.os, "kill", fake_kill)
    rbldnsd.reload_zones()
    assert called["pid"] == 12345
    assert called["sig"] == signal.SIGHUP


def test_write_rbldnsd_config_basic(monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path):
    defaults = tmp_path / "rbldnsd.default"
    monkeypatch.setattr(rbldnsd, "DEFAULTS_FILE", defaults)
    rbldnsd.write_rbldnsd_config(
        [ipaddress.ip_address("127.0.0.1")], 53, False, False, "1m", "example.test"
    )
    content = defaults.read_text()
    assert "RBLDNSD=" in content
    assert "-b 127.0.0.1/53" in content
    assert "-c 1m" in content
    assert "ip.example.test:ip4set:dynamic-ip4set" in content
    assert "domain.example.test:dnset:dynamic-dnset" in content


def test_write_dynamic_entries_db(monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path):
    workload_dir = tmp_path / "rbldns"
    workload_dir.mkdir()
    monkeypatch.setattr(rbldnsd, "WORKLOAD_DATA_DIR", workload_dir)

    class _Cursor:
        def __init__(self) -> None:
            self._rows: list[tuple[str, str, str]] = []

        def execute(self, sql: str) -> None:
            if "ip4set" in sql:
                self._rows = [("127.0.0.2", "127.0.0.1", "Test IP")]
            else:
                self._rows = [("test.example.com", "127.0.0.3", "Test domain")]

        def fetchall(self) -> list[tuple[str, str, str]]:
            return self._rows

    class _Conn:
        def __enter__(self) -> "_Conn":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def cursor(self) -> _Cursor:
            return _Cursor()

    monkeypatch.setattr(rbldnsd.sqlite3, "connect", lambda path: _Conn())
    rbldnsd.write_dynamic_entries_db(tmp_path / "dummy.db")
    ip_content = (workload_dir / "dynamic-ip4set").read_text()
    assert "127.0.0.2 :127.0.0.1:Test IP" in ip_content
    domain_content = (workload_dir / "dynamic-dnset").read_text()
    assert "test.example.com :127.0.0.3:Test domain" in domain_content
