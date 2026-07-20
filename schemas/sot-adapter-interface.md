# Source of Truth Adapter Interface

opskit supports multiple sources of truth for device inventory, IPAM, and CMDB data.
This document defines the adapter interface that every SoT implementation must satisfy.

## Design

When `env.yml → source_of_truth.type = netbox`, NetBox is the canonical store and
local `datasets/` files are generated exports. When `type = git-yaml`, local files
are canonical.

The adapter interface abstracts this so that all downstream consumers (note generator,
inventory report, semaphore-sync, Ansible dynamic inventory) read through the same API.

## Interface

### `read_devices(env_path: str) -> list[Device]`

Return all devices in the environment. Must return a list of `Device` objects:

```python
@dataclass
class Device:
    name: str
    hostname: str | None
    ip_address: str | None
    mac_address: str | None
    role: str | None          # e.g. server, switch, router, workstation
    os: str | None
    os_version: str | None
    hardware: str | None
    serial: str | None
    status: str               # active, standby, decommissioned
    site: str | None
    location: str | None
    vlans: list[int]
    services: list[str]       # service names from services registry
    tags: list[str]
    notes: str | None
    owner: str                # environment name
    maturity: int             # 1-5 per L1-L5 maturity model
    raw: dict                 # backend-specific data (for adapter consumers)
```

### `read_device(env_path: str, name: str) -> Device | None`

Return a single device by name, or None.

### `read_subnets(env_path: str) -> list[Subnet]`

```python
@dataclass
class Subnet:
    name: str
    cidr: str
    gateway: str | None
    vlan_id: int | None
    description: str | None
```

### `read_services(env_path: str) -> list[Service]`

```python
@dataclass
class Service:
    name: str
    host: str                 # device name or IP
    port: int
    protocol: str             # tcp, udp
    description: str | None
```

### `generate_exports(env_path: str) -> None`

Generate local YAML dataset files from the canonical SoT. For `netbox` type, this
pulls from the NetBox API and writes `datasets/devices/*.yml`, `ipam.yml`, etc.
For `git-yaml` type, this is a no-op (local files are canonical).

This is called by `opskit sot-sync` and is idempotent.

## Implementations

| Adapter | File | Status |
|---------|------|--------|
| `git-yaml` | `bin/adapters/git_yaml.py` | Phase 2 (migrated from the predecessor repo) |
| `netbox` | `bin/adapters/netbox.py` | Phase 3 (new; uses NetBox REST API) |

## Configuration

The adapter is selected by `env.yml → source_of_truth.type`. Adapter-specific
configuration (URL, token ref, export path) is in the `source_of_truth` block.
