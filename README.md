# rbldnsd DNS Blacklist Server

This charm deploys and manages the [rbldnsd DNS blacklist server](https://linux.die.net/man/8/rbldnsd) on Ubuntu 24.04 machines. It handles installation, service management, and provides a foundation for further configuration.

## Installation and Usage

### Deploy from Charmhub

```bash
juju deploy rbldnsd
```

### Build and deploy locally

```bash
charmcraft pack
juju deploy ./rbldnsd-*.charm
```

## Configuration

The charm supports the following configuration options:

- `hostname`: Base hostname for the rbldnsd service (default: "example.com")
- `bind-addresses`: JSON list of addresses to bind rbldnsd to (default: ["0.0.0.0"])
- `port`: Port to bind rbldnsd to (default: 53)
- `ipv4-only`: Only listen on IPv4 (default: false)
- `ipv6-only`: Only listen on IPv6 (default: false)
- `check-interval`: Interval between checking for zone file changes (default: "1m")

## Actions

Available actions:

### Static Lists
- `add-static-list`: Add a static list to rbldnsd from a file
- `remove-static-list`: Remove a static list from rbldnsd

### Dynamic Entries
- `add-entry`: Add an entry to the dynamic DNSBL list (supports ip4set and dnset types)
- `remove-entry`: Remove an entry from the dynamic DNSBL list
- `list-entries`: List all dynamic DNSBL entries

### General
- `reload`: Reload rbldnsd zones

## Static Lists

The charm supports adding static blacklists from files. These are useful for large lists that don't change frequently.

### Adding a static list

```bash
juju run rbldnsd/0 add-static-list subdomain=mybl type=ip4set filename=mybl.zone
```

Parameters:
- `subdomain`: The subdomain for this list (for example, "mybl" creates mybl.example.com)
- `type`: Either "ip4set" for IP addresses or "dnset" for domains
- `filename`: Path to the file containing the list entries (in the `/var/lib/rbldns/` folder)

You also need to copy the list to the unit:

```bash
juju scp mybl.zone rbldnsd/0:/var/lib/rbldns/
```

### Removing a static list

```bash
juju run rbldnsd/0 remove-static-list subdomain=mybl
```

## Testing

Run the tests with:

```bash
tox
```
