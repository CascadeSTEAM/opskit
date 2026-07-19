"""
Create new dataset directory scaffolds.

When a user names a new network, this creates:
  inventory/datasets/<name>/
    ├── devices/
    ├── ipam.yml
    ├── network.yml
    ├── services.yml
    └── vlans.yml
"""

from pathlib import Path
from datetime import date


def create_dataset(name: str, inventory_root: Path,
                   cidr: str = "", description: str = "") -> Path:
    """
    Create a new dataset directory with scaffold files.
    Returns the dataset path.
    """
    ds_path = inventory_root / 'datasets' / name
    devices_dir = ds_path / 'devices'

    if ds_path.exists():
        print(f"  Dataset '{name}' already exists at {ds_path}")
        return ds_path

    devices_dir.mkdir(parents=True, exist_ok=True)

    _write_network(ds_path, name, cidr, description)
    _write_ipam(ds_path, name)
    _write_services(ds_path)
    _write_vlans(ds_path)

    print(f"  Created new dataset: {name}")
    print(f"    {ds_path}/network.yml")
    print(f"    {ds_path}/ipam.yml")
    print(f"    {ds_path}/services.yml")
    print(f"    {ds_path}/vlans.yml")
    print(f"    {ds_path}/devices/")
    print(f"  Next: run scan.py --dataset {name} to populate")

    return ds_path


def _write_network(ds_path: Path, name: str, cidr: str, description: str) -> None:
    """Write the network.yml scaffold."""
    content = {
        'network': {
            'name': name,
            'short_name': name,
            'cidr': cidr or "0.0.0.0/0",
            'type': 'private',
            'gateway': '',
            'dns_primary': '',
            'domain': f"{name}.local",
            'description': description or f"Auto-created dataset: {name}",
            'subnets': [
                {
                    'cidr': cidr or "0.0.0.0/0",
                    'purpose': 'Primary subnet',
                    'type': 'mixed',
                }
            ],
        }
    }
    import yaml
    with open(ds_path / 'network.yml', 'w') as fh:
        yaml.dump(content, fh, default_flow_style=False, sort_keys=False)
    print(f"    network.yml — update CIDR, gateway, DNS before scanning")


def _write_ipam(ds_path: Path, name: str) -> None:
    """Write the IPAM scaffold."""
    today = date.today().isoformat()
    content = {
        'ipam': {
            'network': name,
            'last_updated': today,
            'allocations': [],
        }
    }
    import yaml
    with open(ds_path / 'ipam.yml', 'w') as fh:
        yaml.dump(content, fh, default_flow_style=False, sort_keys=False)
    print(f"    ipam.yml — empty, will be populated by scan")


def _write_services(ds_path: Path) -> None:
    """Write the services.yml scaffold."""
    content = {'services': []}
    import yaml
    with open(ds_path / 'services.yml', 'w') as fh:
        yaml.dump(content, fh, default_flow_style=False, sort_keys=False)
    print(f"    services.yml — empty, will be populated by scan")


def _write_vlans(ds_path: Path) -> None:
    """Write the vlans.yml scaffold."""
    content = {'vlans': []}
    import yaml
    with open(ds_path / 'vlans.yml', 'w') as fh:
        yaml.dump(content, fh, default_flow_style=False, sort_keys=False)
    print(f"    vlans.yml — empty, will be populated by scan")


def list_datasets(inventory_root: Path) -> list[dict]:
    """List all existing datasets with basic info."""
    datasets_dir = inventory_root / 'datasets'
    if not datasets_dir.exists():
        return []

    results = []
    for ds in sorted(datasets_dir.iterdir()):
        if not ds.is_dir():
            continue
        network_file = ds / 'network.yml'
        info = {'name': ds.name, 'path': ds}
        if network_file.exists():
            import yaml
            try:
                with open(network_file) as fh:
                    data = yaml.safe_load(fh)
                net = data.get('network', {})
                info['cidr'] = net.get('cidr', '')
                info['description'] = net.get('description', '')
            except Exception:
                pass
        info['device_count'] = len(list((ds / 'devices').glob('*.yml'))) if (ds / 'devices').exists() else 0
        results.append(info)
    return results
