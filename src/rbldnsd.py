# Copyright 2025 Tony Meyer
# See LICENSE file for licensing details.

"""Functions for managing and interacting with the workload.

The intention is that this module could be used outside the context of a charm.
"""

import logging
import os
import pathlib
import signal
import sqlite3
import subprocess

from charms.operator_libs_linux.v0 import apt
from charms.operator_libs_linux.v1 import systemd

logger = logging.getLogger(__name__)


# Functions for managing the workload process on the local machine:


def install() -> bool:
    """Install the workload (by installing rbldnsd via apt)."""
    try:
        apt.update()
        apt.add_package("rbldnsd")
        return True
    except apt.PackageNotFoundError:
        logger.error("Could not find rbldnsd package.")
    except apt.PackageError as e:
        logger.error("Could not install rbldnsd package. Reason: %s", e.message)
    return False


def start() -> bool:
    """Start the workload (by starting the rbldnsd service)."""
    try:
        systemd.service_enable("rbldnsd")
        systemd.service_start("rbldnsd")
        return True
    except systemd.SystemdError as e:
        logger.error(f"Failed to start rbldnsd service: {e}")
    return False


def remove():
    """Remove the rbldnsd package using apt."""
    apt.remove_package("rbldnsd")


def restart() -> bool:
    """Restart the rbldnsd service using systemd."""
    try:
        systemd.service_restart("rbldnsd")
        return True
    except systemd.SystemdError as e:
        logger.error("Failed to restart rbldnsd service: %s", e)
    return False


def reload_zones():
    """Send SIGHUP to rbldnsd to reload zones."""
    with open("/var/run/rbldnsd.pid", "r") as f:
        pid = int(f.read())
    os.kill(pid, signal.SIGHUP)


# Functions for interacting with the workload:


def get_version() -> str | None:
    """Get the running version of the workload."""
    try:
        result = subprocess.run(
            ["/usr/sbin/rbldnsd", "-h"], capture_output=True, text=True, check=True
        )
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to get rbldnsd version: {e}")
        return None
    # Help output starts with something like:
    # "rbldnsd: rbl dns daemon version 1.0pre (snapshot 20210120)"
    first_line = result.stdout.splitlines()[0]
    if "version" in first_line:
        version = first_line.split("version", 1)[1].strip()
        return version
    logger.error("Unexpected output format from rbldnsd -h: %s", first_line)
    return None


def write_rbldnsd_config(
    bind_addresses,
    port,
    ipv4_only,
    ipv6_only,
    check_interval,
    hostname: str,
    db_path: pathlib.Path | None = None,
):
    """Write the /etc/default/rbldnsd file."""
    cmd = []
    for addr in bind_addresses:
        cmd.extend(["-b", f"{addr}/{port}"])
    if ipv4_only:
        cmd.append("-4")
    if ipv6_only:
        cmd.append("-6")
    if check_interval:
        cmd.extend(["-c", str(check_interval)])
    cmd_str = " ".join(cmd)
    static_lists = _get_static_lists(db_path) if db_path else []
    lines = [
        "# /etc/default/rbldnsd",
        "# This file should set one variable, RBLDNSD, to be a multiline",
        "# list of all instances of rbldnsd to start.  Every line in that",
        "# list consist of a key (basename for a pid file), and rbldnsd",
        "# command line, e.g.:",
        "#",
        '# RBLDNSD="dsbl -r/var/lib/rbldns/dsbl -b127.2 list.dsbl.org:ip4set:list"',
        "",
        f'RBLDNSD="- -f -r/var/lib/rbldns/ -p /var/run/rbldnsd.pid {cmd_str} '
        f"ip.{hostname}:ip4set:dynamic-ip4set "
        f"domain.{hostname}:dnset:dynamic-dnset"
        f' {" ".join(f"{s}.{hostname}:{t}:{f}" for s, t, f in static_lists)}"',
    ]
    with open("/etc/default/rbldnsd", "w") as f:
        f.write("\n".join(lines))


def _get_static_lists(db_path: pathlib.Path) -> list[tuple[str, str, str]]:
    """Retrieve static lists from the database."""
    if not db_path.exists():
        return []
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT subdomain, type, filename FROM static_lists")
        return list(cursor.fetchall())


def write_dynamic_entries_db(db_path: pathlib.Path):
    """Write the dynamic entries to the database."""
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT ip, a_record, txt_record FROM ip4set")
        with open("/var/lib/rbldns/dynamic-ip4set", "w") as f:
            for ip, a_record, txt_record in cursor.fetchall():
                f.write(f"{ip} :{a_record}{':' if txt_record else ''}{txt_record}\n")
        with open("/var/lib/rbldns/dynamic-dnset", "w") as f:
            for domain, a_record, txt_record in cursor.fetchall():
                f.write(f"{domain} :{a_record}{':' if txt_record else ''}{txt_record}\n")
