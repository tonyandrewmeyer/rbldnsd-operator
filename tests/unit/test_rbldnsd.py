import pathlib
import signal
import unittest.mock

import rbldnsd


def test_get_version_success(monkeypatch):
    class DummyResult:
        def __init__(self):
            self.stdout = (
                "rbldnsd: rbl dns daemon version 1.0pre (snapshot 20210120)\n"
                "Usage is: rbldnsd options zonespec..."
            )

    monkeypatch.setattr(rbldnsd.subprocess, "run", lambda *a, **k: DummyResult())
    assert rbldnsd.get_version() == "1.0pre (snapshot 20210120)"


def test_get_version_error(monkeypatch):
    def raise_error(*a, **k):
        raise rbldnsd.subprocess.CalledProcessError(1, "rbldnsd")

    monkeypatch.setattr(rbldnsd.subprocess, "run", raise_error)
    assert rbldnsd.get_version() is None


def test_install_calls_apt(monkeypatch):
    update_mock = unittest.mock.Mock()
    add_package_mock = unittest.mock.Mock()
    monkeypatch.setattr(rbldnsd.apt, "update", update_mock)
    monkeypatch.setattr(rbldnsd.apt, "add_package", add_package_mock)
    rbldnsd.install()
    update_mock.assert_called_once()
    add_package_mock.assert_called_once_with("rbldnsd")


def test_remove_calls_apt(monkeypatch):
    remove_mock = unittest.mock.Mock()
    monkeypatch.setattr(rbldnsd.apt, "remove_package", remove_mock)
    rbldnsd.remove()
    remove_mock.assert_called_once_with("rbldnsd")


def test_start_calls_systemd(monkeypatch):
    class DummySystemd:
        class SystemdError(Exception):
            pass

        @staticmethod
        def service_enable(name):
            assert name == "rbldnsd"

        @staticmethod
        def service_start(name):
            assert name == "rbldnsd"

    monkeypatch.setattr(rbldnsd, "systemd", DummySystemd)
    rbldnsd.start()


def test_restart_calls_systemd(monkeypatch):
    class DummySystemd:
        class SystemdError(Exception):
            pass

        @staticmethod
        def service_restart(name):
            assert name == "rbldnsd"

    monkeypatch.setattr(rbldnsd, "systemd", DummySystemd)
    rbldnsd.restart()


def test_reload_zones(monkeypatch, tmp_path):
    pidfile = tmp_path / "rbldnsd.pid"
    pidfile.write_text("12345")
    monkeypatch.setattr(
        "builtins.open",
        lambda f, mode="r": pidfile.open(mode),
    )
    called = {}

    def fake_kill(pid, sig):
        called["pid"] = pid
        called["sig"] = sig

    monkeypatch.setattr(rbldnsd.os, "kill", fake_kill)
    rbldnsd.reload_zones()
    assert called["pid"] == 12345
    assert called["sig"] == signal.SIGHUP


def test_write_rbldnsd_config_basic(monkeypatch, tmp_path):
    path = tmp_path / "rbldnsd.default"

    monkeypatch.setattr(
        "builtins.open",
        lambda f, mode="r": path.open(mode),
    )
    rbldnsd.write_rbldnsd_config(["127.0.0.1"], 53, False, False, "1m", "example.test")
    content = path.read_text()
    assert "RBLDNSD=" in content
    assert "-b 127.0.0.1/53" in content
    assert "-c 1m" in content
    assert "ip.example.test:ip4set:dynamic-ip4set" in content
    assert "domain.example.test:dnset:dynamic-dnset" in content


def test_write_dynamic_entries_db(monkeypatch, tmp_path):
    ip_path = tmp_path / "ip-entries.db"
    domain_path = tmp_path / "domain-entries.db"

    class DummyCursor:
        def execute(self, sql):
            if "ip4set" in sql:
                self._rows = [("127.0.0.2", "127.0.0.1", "Test IP")]
            else:
                self._rows = [("test.example.com", "127.0.0.3", "Test domain")]

        def fetchall(self):
            return self._rows

    class DummyConn:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def cursor(self):
            return DummyCursor()

    monkeypatch.setattr(rbldnsd.sqlite3, "connect", lambda path: DummyConn())
    monkeypatch.setattr(
        "builtins.open",
        lambda f, mode="r": ip_path.open(mode)
        if f == "/var/lib/rbldns/dynamic-ip4set"
        else domain_path.open(mode),
    )
    rbldnsd.write_dynamic_entries_db(pathlib.Path("."))
    ip_content = ip_path.read_text()
    assert "127.0.0.2 :127.0.0.1:Test IP" in ip_content
    domain_content = domain_path.read_text()
    assert "test.example.com :127.0.0.3:Test domain" in domain_content
