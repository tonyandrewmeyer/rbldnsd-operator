# Copyright 2025 Tony Meyer
# See LICENSE file for licensing details.
#
# To learn more about testing, see https://ops.readthedocs.io/en/latest/explanation/testing.html

import ipaddress
import json
import sqlite3

import pytest
from ops import testing

from charm import DB_PATH, RbldnsdCharm


def mock_get_version():
    """Get a mock version string without executing the workload code."""
    return "1.0.0"


def mock_rbldnsd_functions(monkeypatch):
    """Mock all rbldnsd module functions for testing."""
    monkeypatch.setattr("charm.rbldnsd.get_version", mock_get_version)
    monkeypatch.setattr("charm.rbldnsd.install", lambda: True)
    monkeypatch.setattr("charm.rbldnsd.start", lambda: True)
    monkeypatch.setattr("charm.rbldnsd.restart", lambda: True)
    monkeypatch.setattr("charm.rbldnsd.remove", lambda: True)
    monkeypatch.setattr("charm.rbldnsd.reload_zones", lambda: None)
    monkeypatch.setattr("charm.rbldnsd.write_rbldnsd_config", lambda *args, **kwargs: None)
    monkeypatch.setattr("charm.rbldnsd.write_dynamic_entries_db", lambda *args: None)


class TestCharmInitialisation:
    """Test charm initialisation and basic lifecycle events."""

    def test_install_success(self, monkeypatch):
        """Test successful installation."""
        install_called = []

        def mock_install():
            install_called.append(True)
            return True

        monkeypatch.setattr("charm.rbldnsd.install", mock_install)
        ctx = testing.Context(RbldnsdCharm)

        state_out = ctx.run(ctx.on.install(), testing.State())

        assert state_out.unit_status == testing.ActiveStatus()
        assert install_called, "rbldnsd.install should have been called"

    def test_install_failure(self, monkeypatch):
        monkeypatch.setattr("charm.rbldnsd.install", lambda: False)
        ctx = testing.Context(RbldnsdCharm)

        state_out = ctx.run(ctx.on.install(), testing.State())

        assert state_out.unit_status == testing.BlockedStatus("Failed to install rbldnsd.")

    def test_start_success(self, monkeypatch):
        monkeypatch.setattr("charm.rbldnsd.get_version", mock_get_version)

        start_called = []

        def mock_start():
            start_called.append(True)
            return True

        monkeypatch.setattr("charm.rbldnsd.start", mock_start)
        ctx = testing.Context(RbldnsdCharm)

        state_out = ctx.run(ctx.on.start(), testing.State())

        assert state_out.unit_status == testing.ActiveStatus()
        assert state_out.workload_version == "1.0.0"
        assert start_called, "rbldnsd.start should have been called"

    def test_start_failure(self, monkeypatch):
        monkeypatch.setattr("charm.rbldnsd.start", lambda: False)
        ctx = testing.Context(RbldnsdCharm)

        state_out = ctx.run(ctx.on.start(), testing.State())

        assert state_out.unit_status == testing.BlockedStatus("Failed to start rbldnsd")

    def test_remove(self, monkeypatch):
        remove_called = []

        def mock_remove():
            remove_called.append(True)
            return True

        monkeypatch.setattr("charm.rbldnsd.remove", mock_remove)
        ctx = testing.Context(RbldnsdCharm)

        state_out = ctx.run(ctx.on.remove(), testing.State())

        assert state_out.unit_status == testing.BlockedStatus("rbldnsd removed.")
        assert remove_called, "rbldnsd.remove should have been called"


class TestConfigurationChanges:
    """Test configuration change handling."""

    @pytest.fixture(autouse=True)
    def setup_monkeypatch(self, monkeypatch):
        """Set up monkeypatching for all tests in this class."""
        mock_rbldnsd_functions(monkeypatch)

    def test_config_changed_success(self, monkeypatch):
        write_config_called = []

        def mock_write_config(*args, **kwargs):
            write_config_called.append((args, kwargs))

        monkeypatch.setattr("charm.rbldnsd.write_rbldnsd_config", mock_write_config)

        ctx = testing.Context(RbldnsdCharm)

        config: dict[str, str | int | float] = {
            "hostname": "test.example.com",
            "port": 5353,
            "bind-addresses": json.dumps(["0.0.0.0"]),
            "ipv4-only": False,
            "ipv6-only": False,
            "check-interval": "2m",
        }

        state_out = ctx.run(ctx.on.config_changed(), testing.State(config=config))

        assert state_out.unit_status == testing.ActiveStatus()
        assert len(write_config_called) == 1
        assert write_config_called[0][0] == (
            [ipaddress.ip_address("0.0.0.0")],
            5353,
            False,
            False,
            "2m",
            "test.example.com",
            DB_PATH,
        )

    def test_config_changed_invalid_port(self, monkeypatch):
        ctx = testing.Context(RbldnsdCharm)

        config: dict[str, str | int | float] = {
            "hostname": "test.example.com",
            "port": 70000,  # Invalid port
            "bind-addresses": json.dumps(["127.0.0.1"]),
            "ipv4-only": False,
            "ipv6-only": False,
            "check-interval": "2m",
        }

        state_out = ctx.run(ctx.on.config_changed(), testing.State(config=config))

        assert isinstance(state_out.unit_status, testing.BlockedStatus)
        assert "Invalid config" in state_out.unit_status.message
        assert "Port must be between 1 and 65535" in state_out.unit_status.message

    def test_config_changed_conflicting_ip_versions(self, monkeypatch):
        ctx = testing.Context(RbldnsdCharm)

        config: dict[str, str | int | float] = {
            "hostname": "test.example.com",
            "port": 53,
            "bind-addresses": json.dumps(["127.0.0.1"]),
            "ipv4-only": True,
            "ipv6-only": True,  # Conflict with ipv4-only
            "check-interval": "2m",
        }

        state_out = ctx.run(ctx.on.config_changed(), testing.State(config=config))

        assert isinstance(state_out.unit_status, testing.BlockedStatus)
        assert "Invalid config" in state_out.unit_status.message

    def test_config_changed_restart_failure(self, monkeypatch):
        monkeypatch.setattr("charm.rbldnsd.restart", lambda: False)
        ctx = testing.Context(RbldnsdCharm)

        config: dict[str, str | int | float] = {
            "hostname": "test.example.com",
            "port": 5353,
            "bind-addresses": json.dumps(["127.0.0.1"]),
            "ipv4-only": False,
            "ipv6-only": False,
            "check-interval": "2m",
        }

        state_out = ctx.run(ctx.on.config_changed(), testing.State(config=config))

        assert isinstance(state_out.unit_status, testing.BlockedStatus)
        assert "Failed to restart rbldnsd" in state_out.unit_status.message


class TestActionHandling:
    """Test action handling."""

    def test_reload_action(self, monkeypatch):
        reload_called = []

        def mock_reload():
            reload_called.append(True)

        monkeypatch.setattr("charm.rbldnsd.reload_zones", mock_reload)

        ctx = testing.Context(RbldnsdCharm)

        ctx.run(ctx.on.action("reload"), testing.State())

        assert ctx.action_results == {"result": "rbldnsd zones reloaded"}
        assert reload_called, "rbldnsd.reload_zones should have been called"

    def test_add_entry_action_ip4set(self, monkeypatch, tmp_path):
        mock_rbldnsd_functions(monkeypatch)

        db_path = tmp_path / "test.db"
        monkeypatch.setattr("charm.DB_PATH", db_path)

        ctx = testing.Context(RbldnsdCharm)

        ctx.run(
            ctx.on.action(
                "add-entry",
                params={
                    "type": "ip4set",
                    "value": "192.168.1.1",
                    "a_record": "127.0.0.5",
                    "txt_record": "Test IP",
                },
            ),
            testing.State(),
        )

        assert ctx.action_results == {"result": "Entry added: ip4set 192.168.1.1"}

    def test_add_entry_action_dnset(self, monkeypatch, tmp_path):
        mock_rbldnsd_functions(monkeypatch)

        db_path = tmp_path / "test.db"
        monkeypatch.setattr("charm.DB_PATH", db_path)

        ctx = testing.Context(RbldnsdCharm)

        ctx.run(
            ctx.on.action(
                "add-entry",
                params={
                    "type": "dnset",
                    "value": "spam.example.com",
                    "a_record": "127.0.0.6",
                    "txt_record": "Test domain",
                },
            ),
            testing.State(),
        )

        assert ctx.action_results == {"result": "Entry added: dnset spam.example.com."}

    def test_add_entry_action_duplicate(self, monkeypatch, tmp_path):
        mock_rbldnsd_functions(monkeypatch)

        db_path = tmp_path / "test.db"
        monkeypatch.setattr("charm.DB_PATH", db_path)

        with sqlite3.connect(db_path) as conn:
            c = conn.cursor()
            c.execute(
                """
                CREATE TABLE ip4set (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ip TEXT NOT NULL,
                    a_record TEXT DEFAULT '127.0.0.2',
                    txt_record TEXT
                )
            """
            )
            c.execute(
                "INSERT INTO ip4set (ip, a_record, txt_record) VALUES (?, ?, ?)",
                ("192.168.1.1", "127.0.0.5", "Existing IP"),
            )
            conn.commit()

        ctx = testing.Context(RbldnsdCharm)

        with pytest.raises(testing.ActionFailed) as exc_info:
            ctx.run(
                ctx.on.action(
                    "add-entry",
                    params={
                        "type": "ip4set",
                        "value": "192.168.1.1",
                        "a_record": "127.0.0.5",
                        "txt_record": "Test IP",
                    },
                ),
                testing.State(),
            )

        assert isinstance(exc_info.value, testing.ActionFailed)
        assert exc_info.value.message == "IP already exists"

    def test_remove_entry_action(self, monkeypatch, tmp_path):
        mock_rbldnsd_functions(monkeypatch)

        db_path = tmp_path / "test.db"
        monkeypatch.setattr("charm.DB_PATH", db_path)

        with sqlite3.connect(db_path) as conn:
            c = conn.cursor()
            c.execute(
                """
                CREATE TABLE ip4set (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ip TEXT NOT NULL,
                    a_record TEXT DEFAULT '127.0.0.2',
                    txt_record TEXT
                )
            """
            )
            c.execute(
                "INSERT INTO ip4set (ip, a_record, txt_record) VALUES (?, ?, ?)",
                ("192.168.1.1", "127.0.0.5", "Test IP"),
            )
            conn.commit()

        ctx = testing.Context(RbldnsdCharm)

        ctx.run(
            ctx.on.action("remove-entry", params={"type": "ip4set", "value": "192.168.1.1"}),
            testing.State(),
        )

        assert ctx.action_results == {"result": "Entry removed: ip4set 192.168.1.1"}

    def test_list_entries_action(self, monkeypatch, tmp_path):
        mock_rbldnsd_functions(monkeypatch)

        db_path = tmp_path / "test.db"
        monkeypatch.setattr("charm.DB_PATH", db_path)

        with sqlite3.connect(db_path) as conn:
            c = conn.cursor()
            c.execute(
                """
                CREATE TABLE ip4set (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ip TEXT NOT NULL,
                    a_record TEXT DEFAULT '127.0.0.2',
                    txt_record TEXT
                )
            """
            )
            c.execute(
                """
                CREATE TABLE dnset (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    domain TEXT NOT NULL,
                    a_record TEXT DEFAULT '127.0.0.2',
                    txt_record TEXT
                )
            """
            )
            c.execute(
                "INSERT INTO ip4set (ip, a_record, txt_record) VALUES (?, ?, ?)",
                ("192.168.1.1", "127.0.0.5", "Test IP"),
            )
            c.execute(
                "INSERT INTO dnset (domain, a_record, txt_record) VALUES (?, ?, ?)",
                ("spam.example.com", "127.0.0.6", "Test domain"),
            )
            conn.commit()

        ctx = testing.Context(RbldnsdCharm)

        ctx.run(ctx.on.action("list-entries"), testing.State())

        expected_results = {
            "ip4set": [{"ip": "192.168.1.1", "a_record": "127.0.0.5", "txt_record": "Test IP"}],
            "dnset": [
                {
                    "domain": "spam.example.com",
                    "a_record": "127.0.0.6",
                    "txt_record": "Test domain",
                }
            ],
        }
        assert ctx.action_results == expected_results

    def test_add_static_list_action(self, monkeypatch, tmp_path):
        mock_rbldnsd_functions(monkeypatch)

        db_path = tmp_path / "test.db"
        monkeypatch.setattr("charm.DB_PATH", db_path)
        monkeypatch.setattr("pathlib.Path.exists", lambda self: True)

        ctx = testing.Context(RbldnsdCharm)

        ctx.run(
            ctx.on.action(
                "add-static-list",
                params={"subdomain": "test", "type": "ip4set", "filename": "test.zone"},
            ),
            testing.State(),
        )

        assert ctx.action_results == {"result": "Static list added: test (ip4set)"}
        assert ctx.action_logs == []

    def test_remove_static_list_action(self, monkeypatch, tmp_path):
        mock_rbldnsd_functions(monkeypatch)

        db_path = tmp_path / "test.db"
        monkeypatch.setattr("charm.DB_PATH", db_path)

        with sqlite3.connect(db_path) as conn:
            c = conn.cursor()
            c.execute(
                """
                CREATE TABLE static_lists (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    subdomain TEXT NOT NULL,
                    type TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    UNIQUE(subdomain, type)
                )
            """
            )
            c.execute(
                "INSERT INTO static_lists (subdomain, type, filename) VALUES (?, ?, ?)",
                ("test", "ip4set", "test.zone"),
            )
            conn.commit()

        ctx = testing.Context(RbldnsdCharm)

        ctx.run(
            ctx.on.action("remove-static-list", params={"subdomain": "test", "type": "ip4set"}),
            testing.State(),
        )

        assert ctx.action_results == {"result": "Static list removed: test (ip4set)"}


class TestErrorHandling:
    """Test error handling scenarios."""

    def test_invalid_action_parameters(self, monkeypatch, tmp_path):
        mock_rbldnsd_functions(monkeypatch)

        db_path = tmp_path / "test.db"
        monkeypatch.setattr("charm.DB_PATH", db_path)

        ctx = testing.Context(RbldnsdCharm)

        with pytest.raises(testing.ActionFailed) as exc_info:
            ctx.run(
                ctx.on.action(
                    "add-entry", params={"type": "invalid type", "value": "192.168.1.1"}
                ),
                testing.State(),
            )
        assert isinstance(exc_info.value, testing.ActionFailed)
        assert "invalid type" in exc_info.value.message

    def test_database_operations_with_missing_file(self, monkeypatch):
        ctx = testing.Context(RbldnsdCharm)

        ctx.run(
            ctx.on.action(
                "add-static-list",
                params={"subdomain": "test", "type": "ip4set", "filename": "/no/such/file.zone"},
            ),
            testing.State(),
        )

        assert ctx.action_logs == [
            "Please copy the list into the unit. `juju scp /local/path rbldnsd/0:/var/lib/rbldns/`"
        ]
