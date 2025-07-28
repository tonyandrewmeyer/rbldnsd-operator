#!/usr/bin/env python3
# Copyright 2025 Tony Meyer
# See LICENSE file for licensing details.

import logging
import subprocess

import jubilant
import pytest
import pytest_jubilant

logger = logging.getLogger(__name__)


@pytest.mark.setup
def test_build_deploy_charm(juju):
    juju.deploy(
        pytest_jubilant.pack("."),
        "rbldnsd",
        config={"hostname": "rbldnsd.test", "port": 8053},
    )
    juju.wait(jubilant.all_active)


def get_unit_ip_address(juju: jubilant.Juju, app_name: str, unit_no: int):
    """Return a juju unit's IP address."""
    return juju.status().apps[app_name].units[f"{app_name}/{unit_no}"].address


def dns_lookup(
    juju: jubilant.Juju, type: str, value: str, a_record: str, txt_record: str | None, domain: str
):
    """Perform a DNS lookup to verify the rbldnsd service is working."""
    unit_ip = get_unit_ip_address(juju, "rbldnsd", 0)
    cmd = ["/usr/bin/dig", f"@{unit_ip}", "-p", 8053, "+short"]
    if type == "ip4set":
        reversed_ip = ".".join(reversed(value.split(".")))
        cmd.append(f"{reversed_ip}.{domain}")
    else:
        cmd.append(f"{value}.{domain}")
    dig = subprocess.run(cmd, capture_output=True, check=True)
    assert dig.returncode == 0
    assert dig.stdout.strip() == str(a_record)
    if not txt_record:
        return
    cmd.append("TXT")
    dig = subprocess.run(cmd, capture_output=True, check=True)
    assert dig.returncode == 0
    assert dig.stdout.strip() == f'"{txt_record}"'


@pytest.mark.parametrize("type,value", [("ip4set", "127.0.0.1"), ("dnset", "example.test")])
def test_add_list_remove_ip4set_entry(juju: jubilant.Juju, type: str, value: str):
    # Add an entry.
    result = juju.run(
        "rbldnsd/0",
        "add-entry",
        params={
            "type": type,
            "value": value,
            "a_record": "127.0.0.3",
            "txt_record": "Test entry",
        },
    )
    result.raise_on_failure()
    dns_lookup(juju, type, value, "127.0.0.3", "Test entry", "rbldnsd.test")
    # List entries.
    result = juju.run("rbldnsd/0", "list-entries", params={"type": type})
    result.raise_on_failure()
    entry = result.results[type][0]
    if type == "ip4set":
        assert entry["ip"] == value
    else:
        assert entry["domain"] == value
    assert entry["a_record"] == "127.0.0.3"
    assert entry["txt_record"] == "Test entry"
    # Remove the entry.
    result = juju.run("rbldnsd/0", "remove-entry", params={"type": type, "value": value})
    result.raise_on_failure()
    # List again to confirm removal.
    result = juju.run("rbldnsd/0", "list-entries", params={"type": type})
    result.raise_on_failure()
    assert not result.results[type]


def test_hostname_config(juju: jubilant.Juju):
    juju.config("rbldnsd", {"hostname": "blacklist.test"})
    try:
        juju.wait(jubilant.all_active)
        result = juju.run(
            "rbldnsd/0",
            "add-entry",
            params={
                "type": "ip4set",
                "value": "127.1.0.0",
            },
        )
        result.raise_on_failure()
        dns_lookup(juju, "ip4set", "127.1.0.0", "127.0.0.2", None, "blacklist.test")
    finally:
        juju.config("rbldnsd", {"hostname": "rbldnsd.test"})
        juju.wait(jubilant.all_active)
