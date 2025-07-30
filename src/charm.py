#!/usr/bin/env python3
# Copyright 2025 Tony Meyer
# See LICENSE file for licensing details.

"""Charm the application."""

import dataclasses
import ipaddress
import json
import logging
import pathlib
import sqlite3

import ops

import rbldnsd

logger = logging.getLogger(__name__)

DB_PATH = pathlib.Path("/var/lib/rbldnsd-operator/dynamic_entries.db")


@dataclasses.dataclass(frozen=True, kw_only=True)
class RbldnsdConfig:
    """Configuration for rbldnsd."""

    hostname: str = "example.com"
    """Base hostname for the rbldnsd service."""
    bind_addresses: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = dataclasses.field(
        default_factory=lambda: [ipaddress.ip_address("0.0.0.0")]
    )
    """Addresses to bind rbldnsd to."""
    port: int = 53
    """Port to bind rbldnsd to."""
    ipv4_only: bool = False
    """Only listen on IPv4."""
    ipv6_only: bool = False
    """Only listen on IPv6."""
    check_interval: str = "1m"
    """Interval between checking for zone file changes."""

    def __post_init__(self):
        """Post-init hook."""
        if isinstance(self.bind_addresses, str):
            bind_addresses = json.loads(self.bind_addresses)
            addresses: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
            for addr in bind_addresses:
                try:
                    addresses.append(ipaddress.ip_address(addr))
                except ValueError:
                    raise ValueError(f"Invalid bind address: {addr}")
            object.__setattr__(self, "bind_addresses", addresses)
        if self.port and not 1 <= self.port <= 65535:
            raise ValueError(f"Port must be between 1 and 65535, got {self.port}")
        if self.ipv4_only and self.ipv6_only:
            raise ValueError("Cannot specify both ipv4_only and ipv6_only")
        if not self.check_interval:
            raise ValueError("check_interval must be specified")
        if self.check_interval.isdigit():
            return
        if not self.check_interval.endswith(("s", "m", "h", "d", "w")):
            raise ValueError(
                f"check_interval must be a duration like '1s', '5m', or '2h', "
                f"got {self.check_interval}"
            )


@dataclasses.dataclass(frozen=True, kw_only=True)
class AddEntryAction:
    """Action to add an entry to the dynamic DNSBL list."""

    type: str
    """Type of entry to add."""
    value: ipaddress.IPv4Address | str
    """Value of entry to add."""
    a_record: ipaddress.IPv4Address | ipaddress.IPv6Address = ipaddress.ip_address("127.0.0.2")
    """A record to add."""
    txt_record: str = ""
    """TXT record to add."""

    def __post_init__(self):
        """Post-init hook."""
        if self.type not in ("ip4set", "dnset"):
            raise ValueError(f"Invalid entry type: {self.type}")
        if isinstance(self.a_record, str):
            object.__setattr__(self, "a_record", ipaddress.ip_address(self.a_record))
        if self.type == "ip4set":
            if isinstance(self.value, str):
                # rbldnsd allows partial addresses, like "127.0" to mean anything that starts
                # with "127.0" However, we do not want to expose that, as it's too easy to
                # widely block. So we only allow full addresses.
                object.__setattr__(self, "value", ipaddress.ip_address(self.value))
            if isinstance(self.value, ipaddress.IPv6Address):
                # rbldnsd can do these, but realistically they end up blocking almost nothing
                # so we won't bother for now.
                raise ValueError(f"IPv6 addresses are not supported: {self.value}")
        else:
            if not isinstance(self.value, str):
                raise ValueError(f"Domain must be a string, got {type(self.value)}")
            if not self.value.endswith("."):
                object.__setattr__(self, "value", self.value + ".")


@dataclasses.dataclass(frozen=True, kw_only=True)
class RemoveEntryAction:
    """Action to remove an entry from the dynamic DNSBL list."""

    type: str
    """Type of entry to remove."""
    value: str
    """Value of entry to remove."""

    def __post_init__(self):
        """Post-init hook."""
        if self.type not in ("ip4set", "dnset"):
            raise ValueError(f"Invalid entry type: {self.type}")


@dataclasses.dataclass(frozen=True, kw_only=True)
class ListEntriesAction:
    """Action to list entries from the dynamic DNSBL list."""

    type: str | None = None
    """Type of entries to list."""

    def __post_init__(self):
        """Post-init hook."""
        if self.type is not None and self.type not in ("ip4set", "dnset"):
            raise ValueError(f"Invalid entry type: {self.type}")


@dataclasses.dataclass(frozen=True, kw_only=True)
class AddStaticListAction:
    """Action to add a static list."""

    type: str
    """Type of static list."""
    subdomain: str
    """Subdomain for the static list."""
    filename: str
    """Filename for the static list."""

    def __post_init__(self):
        """Post-init hook."""
        if self.type not in ("ip4set", "dnset"):
            raise ValueError(f"Invalid static list type: {self.type}")


@dataclasses.dataclass(frozen=True, kw_only=True)
class RemoveStaticListAction:
    """Action to remove a static list."""

    type: str
    """Type of static list."""
    subdomain: str
    """Subdomain for the static list."""

    def __post_init__(self):
        """Post-init hook."""
        if self.type not in ("ip4set", "dnset"):
            raise ValueError(f"Invalid static list type: {self.type}")


class RbldnsdCharm(ops.CharmBase):
    """Charm the application."""

    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        framework.observe(self.on.install, self._on_install)
        framework.observe(self.on.start, self._on_start)
        framework.observe(self.on.remove, self._on_remove)
        framework.observe(self.on.config_changed, self._on_config_changed)
        framework.observe(self.on["reload"].action, self._on_reload_action)
        framework.observe(self.on["add_entry"].action, self._on_add_entry_action)
        framework.observe(self.on["remove_entry"].action, self._on_remove_entry_action)
        framework.observe(self.on["list_entries"].action, self._on_list_entries_action)
        framework.observe(self.on["add-static-list"].action, self._on_add_static_list_action)
        framework.observe(self.on["remove-static-list"].action, self._on_remove_static_list_action)
        # TODO: Integrate with prometheus charm
        # metrics to prometheus
        # add "-s statsfile" to the command line
        # expose the metrics from that file, which looks like:
        # timestamp zone:qtot:qok:qnxd:bin:bout zone:...
        # qtot total queries received
        # qok positive replies
        # qnxd NXDOMAIN replies
        # bin total bytes read from network
        # bout total bytes written to network
        # *: total values for all zones

    def _init_db(self):
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(DB_PATH) as conn:
            c = conn.cursor()
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS ip4set (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ip TEXT NOT NULL,
                    a_record TEXT DEFAULT '127.0.0.2',
                    txt_record TEXT
                )
            """
            )
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS dnset (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    domain TEXT NOT NULL,
                    a_record TEXT DEFAULT '127.0.0.2',
                    txt_record TEXT
                )
            """
            )
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS static_lists (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    subdomain TEXT NOT NULL,
                    type TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    UNIQUE(subdomain, type)
                )
                """
            )
            conn.commit()

    def _add_entry_db(self, entry_type: str, value: str, a_record: str, txt_record: str):
        self._init_db()
        with sqlite3.connect(DB_PATH) as conn:
            c = conn.cursor()
            if entry_type == "ip4set":
                c.execute("SELECT 1 FROM ip4set WHERE ip=?", (value,))
                if c.fetchone():
                    return False, "IP already exists"
                c.execute(
                    "INSERT INTO ip4set (ip, a_record, txt_record) VALUES (?, ?, ?)",
                    (value, a_record, txt_record),
                )
            elif entry_type == "dnset":
                c.execute("SELECT 1 FROM dnset WHERE domain=?", (value,))
                if c.fetchone():
                    return False, "Domain already exists"
                c.execute(
                    "INSERT INTO dnset (domain, a_record, txt_record) VALUES (?, ?, ?)",
                    (value, a_record, txt_record),
                )
            else:
                return False, "Unknown entry type"
            conn.commit()
        return True, None

    def _remove_entry_db(self, entry_type: str, value: str):
        self._init_db()
        with sqlite3.connect(DB_PATH) as conn:
            c = conn.cursor()
            if entry_type == "ip4set":
                c.execute("DELETE FROM ip4set WHERE ip=?", (value,))
                if c.rowcount == 0:
                    return False, "IP not found"
            elif entry_type == "dnset":
                c.execute("DELETE FROM dnset WHERE domain=?", (value,))
                if c.rowcount == 0:
                    return False, "Domain not found"
            else:
                return False, "Unknown entry type"
            conn.commit()
        return True, None

    def _list_entries_db(self, entry_type: str | None = None):
        self._init_db()
        with sqlite3.connect(DB_PATH) as conn:
            c = conn.cursor()
            result = {}
            if entry_type in (None, "ip4set"):
                c.execute("SELECT ip, a_record, txt_record FROM ip4set")
                result["ip4set"] = [
                    {"ip": row[0], "a_record": row[1], "txt_record": row[2]}
                    for row in c.fetchall()
                ]
            if entry_type in (None, "dnset"):
                c.execute("SELECT domain, a_record, txt_record FROM dnset")
                result["dnset"] = [
                    {"domain": row[0], "a_record": row[1], "txt_record": row[2]}
                    for row in c.fetchall()
                ]
            return result

    def _on_add_static_list_action(self, event: ops.ActionEvent):
        params = event.load_params(AddStaticListAction, errors="fail")
        if not pathlib.Path(params.filename).exists():
            event.log(
                f"Please copy the list into the unit. "
                f"`juju scp /local/path {self.unit.name}:/var/lib/rbldns/`"
            )
            return
        self._init_db()
        with sqlite3.connect(DB_PATH) as conn:
            c = conn.cursor()
            c.execute(
                "INSERT OR REPLACE INTO static_lists (subdomain, type, filename) VALUES (?, ?, ?)",
                (params.subdomain, params.type, params.filename),
            )
            conn.commit()
        if not self._write_config():
            event.fail("Failed to write rbldnsd config")
            return
        rbldnsd.restart()
        event.set_results({"result": f"Static list added: {params.subdomain} ({params.type})"})

    def _on_remove_static_list_action(self, event: ops.ActionEvent):
        params = event.load_params(RemoveStaticListAction, errors="fail")
        self._init_db()
        with sqlite3.connect(DB_PATH) as conn:
            c = conn.cursor()
            c.execute(
                "DELETE FROM static_lists WHERE subdomain=? AND type=?",
                (params.subdomain, params.type),
            )
            if c.rowcount == 0:
                event.fail(f"Static list not found: {params.subdomain} ({params.type})")
                return
            conn.commit()
        if not self._write_config():
            event.fail("Failed to write rbldnsd config")
            return
        rbldnsd.restart()
        event.set_results({"result": f"Static list removed: {params.subdomain} ({params.type})"})

    def _on_add_entry_action(self, event: ops.ActionEvent):
        params = event.load_params(AddEntryAction, errors="fail")
        ok, msg = self._add_entry_db(
            params.type, str(params.value), str(params.a_record), params.txt_record
        )
        if not ok:
            event.fail(msg)
            return
        event.set_results({"result": f"Entry added: {params.type} {params.value}"})
        rbldnsd.write_dynamic_entries_db(DB_PATH)

    def _on_remove_entry_action(self, event: ops.ActionEvent):
        params = event.load_params(RemoveEntryAction, errors="fail")
        ok, msg = self._remove_entry_db(params.type, str(params.value))
        if not ok:
            event.fail(msg)
            return
        event.set_results({"result": f"Entry removed: {params.type} {params.value}"})
        rbldnsd.write_dynamic_entries_db(DB_PATH)

    def _on_list_entries_action(self, event: ops.ActionEvent):
        params = event.load_params(ListEntriesAction, errors="fail")
        entries = self._list_entries_db(params.type)
        event.set_results(entries)

    def _on_reload_action(self, event: ops.ActionEvent):
        rbldnsd.reload_zones()
        event.set_results({"result": "rbldnsd zones reloaded"})

    def _on_install(self, _: ops.InstallEvent):
        """Install the workload on the machine."""
        self.unit.status = ops.MaintenanceStatus("Installing rbldnsd.")
        if not rbldnsd.install():
            self.unit.status = ops.BlockedStatus("Failed to install rbldnsd.")
            return
        self.unit.status = ops.ActiveStatus()

    def _on_start(self, _: ops.StartEvent):
        """Handle start event."""
        self.unit.status = ops.MaintenanceStatus("Starting rbldnsd")
        if not rbldnsd.start():
            self.unit.status = ops.BlockedStatus("Failed to start rbldnsd")
            return
        version = rbldnsd.get_version()
        if version is not None:
            self.unit.set_workload_version(version)
        self.unit.status = ops.ActiveStatus()

    def _on_remove(self, _: ops.RemoveEvent):
        """Handle remove event by removing the workload."""
        self.unit.status = ops.MaintenanceStatus("Removing rbldnsd")
        rbldnsd.remove()
        self.unit.status = ops.BlockedStatus("rbldnsd removed.")

    def _on_config_changed(self, _: ops.ConfigChangedEvent):
        """Handle config changed event."""
        if not self._write_config():
            return
        if not rbldnsd.restart():
            self.unit.status = ops.BlockedStatus("Failed to restart rbldnsd")
            return
        self.unit.status = ops.ActiveStatus()

    def _write_config(self):
        try:
            config = self.load_config(RbldnsdConfig)
        except ValueError as e:
            logger.error("Failed to load config: %s", e)
            self.unit.status = ops.BlockedStatus(f"Invalid config: {e}")
            return False
        rbldnsd.write_rbldnsd_config(
            config.bind_addresses,
            config.port,
            config.ipv4_only,
            config.ipv6_only,
            config.check_interval,
            config.hostname,
            DB_PATH,
        )
        return True


if __name__ == "__main__":  # pragma: nocover
    ops.main(RbldnsdCharm)
