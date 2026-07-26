# Copyright 2025 Tony Meyer
# See LICENSE file for licensing details.

import logging
import pathlib
import subprocess

import jubilant
import pytest

logger = logging.getLogger(__name__)

APP_NAME = "rbldnsd"
DNS_PORT = 8053


@pytest.mark.setup
def test_build_deploy_charm(charm: pathlib.Path, juju: jubilant.Juju):
    juju.deploy(charm, APP_NAME, config={"hostname": "rbldnsd.test", "port": DNS_PORT})
    juju.wait(jubilant.all_active)


def _unit_ip_address(juju: jubilant.Juju, app_name: str, unit_no: int) -> str:
    """Return a Juju unit's IP address."""
    return juju.status().apps[app_name].units[f"{app_name}/{unit_no}"].address


def _dns_lookup(
    juju: jubilant.Juju,
    entry_type: str,
    value: str,
    a_record: str,
    txt_record: str | None,
    domain: str,
) -> None:
    """Perform a DNS lookup to verify the rbldnsd service is working."""
    unit_ip = _unit_ip_address(juju, APP_NAME, 0)
    cmd = ["/usr/bin/dig", f"@{unit_ip}", "-p", str(DNS_PORT), "+short"]
    if entry_type == "ip4set":
        reversed_ip = ".".join(reversed(value.split(".")))
        cmd.append(f"{reversed_ip}.{domain}")
    else:
        cmd.append(f"{value}.{domain}")
    dig = subprocess.run(cmd, capture_output=True, check=True)
    assert dig.stdout.strip().decode() == str(a_record)
    if not txt_record:
        return
    cmd.append("TXT")
    dig = subprocess.run(cmd, capture_output=True, check=True)
    assert dig.stdout.strip().decode() == f'"{txt_record}"'


@pytest.mark.parametrize("entry_type,value", [("ip4set", "127.0.0.1"), ("dnset", "example.test")])
def test_add_list_remove_entry(juju: jubilant.Juju, entry_type: str, value: str):
    result = juju.run(
        f"{APP_NAME}/0",
        "add-entry",
        params={
            "type": entry_type,
            "value": value,
            "a_record": "127.0.0.3",
            "txt_record": "Test entry",
        },
    )
    result.raise_on_failure()
    _dns_lookup(juju, entry_type, value, "127.0.0.3", "Test entry", "rbldnsd.test")

    result = juju.run(f"{APP_NAME}/0", "list-entries", params={"type": entry_type})
    result.raise_on_failure()
    entry = result.results[entry_type][0]
    if entry_type == "ip4set":
        assert entry["ip"] == value
    else:
        assert entry["domain"] == value
    assert entry["a_record"] == "127.0.0.3"
    assert entry["txt_record"] == "Test entry"

    result = juju.run(f"{APP_NAME}/0", "remove-entry", params={"type": entry_type, "value": value})
    result.raise_on_failure()

    result = juju.run(f"{APP_NAME}/0", "list-entries", params={"type": entry_type})
    result.raise_on_failure()
    assert not result.results[entry_type]


def test_hostname_config(juju: jubilant.Juju):
    juju.config(APP_NAME, {"hostname": "blacklist.test"})
    try:
        juju.wait(jubilant.all_active)
        result = juju.run(
            f"{APP_NAME}/0",
            "add-entry",
            params={"type": "ip4set", "value": "127.1.0.0"},
        )
        result.raise_on_failure()
        _dns_lookup(juju, "ip4set", "127.1.0.0", "127.0.0.2", None, "blacklist.test")
    finally:
        juju.config(APP_NAME, {"hostname": "rbldnsd.test"})
        juju.wait(jubilant.all_active)
