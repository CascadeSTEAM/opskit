#!/usr/bin/env python3
"""baseline.py — Capture, compare, and manage system baselines for opskit environments.

Usage:
    baseline.py capture <env> <host> [--ssh-user <user>] [--ssh-port <port>]
    baseline.py diff <env> <host>
    baseline.py status [<env>]
    baseline.py rebuild <env> <host>

Baselines capture known-good system state for troubleshooting and rebuild.
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# OPSKIT_ROOT override exists for tests (point at a temp repo root).
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = Path(os.environ.get("OPSKIT_ROOT") or SCRIPT_DIR.parent)
ENVS_DIR = REPO_ROOT / "environments"


def ssh_cmd(host: str, user: str, port: int, command: str, local: bool = False) -> str:
    """Execute a command locally or via SSH."""
    if local:
        result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=120)
    else:
        ssh = [
            "ssh",
            "-o", "ConnectTimeout=10",
            "-o", "StrictHostKeyChecking=no",
            "-p", str(port),
            f"{user}@{host}",
            command,
        ]
        result = subprocess.run(ssh, capture_output=True, text=True, timeout=60)
    # Some commands return non-zero but still have useful output
    if result.returncode != 0 and not result.stdout.strip():
        print(f"SSH warning: {result.stderr.strip()}", file=sys.stderr)
        return ""
    return result.stdout.strip()


def is_local(host: str) -> bool:
    """Check if host is localhost."""
    import socket
    try:
        hostname = socket.gethostname()
        local_ips = [socket.gethostbyname(hostname), '127.0.0.1', '::1', 'localhost']
        target_ip = socket.gethostbyname(host)
        return target_ip in local_ips or host in ['localhost', '127.0.0.1', '::1', hostname]
    except:
        return host in ['localhost', '127.0.0.1', '::1']


def capture_all(host: str, user: str, port: int) -> dict:
    """Capture complete system baseline."""
    local = is_local(host)
    mode = "locally" if local else f"{user}@{host}:{port}"
    print(f"Capturing baseline from {mode}...")
    
    baseline = {
        "captured_at": datetime.now().isoformat(),
        "host": host,
        "user": user,
        "local": local,
        "os": {},
        "gpu": {},
        "display": {},
        "packages": [],
        "services": [],
        "network": {},
    }
    
    # Helper to run commands
    def run(cmd):
        return ssh_cmd(host, user, port, cmd, local=local)
    
    # OS
    data = {}
    raw = run("cat /etc/os-release | head -6")
    for line in raw.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            data[k.strip().lower()] = v.strip().strip('"')
    data["kernel"] = run("uname -r")
    data["hostname"] = run("hostname -f") or run("hostname")
    baseline["os"] = data
    
    # GPU
    gpu_data = {}
    vga = run("lspci | grep -i 'vga\\|display\\|3d'")
    gpu_data["devices"] = [l.strip() for l in vga.splitlines() if l.strip()]
    drivers = run("dpkg -l | grep -E 'mesa|intel.*driver|nvidia|amd.*driver' | awk '{print $2, $3}'")
    gpu_data["packages"] = [l.strip() for l in drivers.splitlines() if l.strip()]
    baseline["gpu"] = gpu_data
    
    # Display
    display_data = {}
    dm_raw = run("systemctl list-unit-files --type=service | grep -E 'sddm|gdm|lightdm|lxdm' | head -1")
    if dm_raw:
        display_data["display_manager"] = dm_raw.split()[0].replace(".service", "")
    else:
        display_data["display_manager"] = "unknown"
    
    session_info = run("loginctl show-session $(loginctl list-sessions --no-legend | head -1 | awk '{print $1}') -p Type -p Desktop 2>/dev/null")
    if session_info:
        for line in session_info.splitlines():
            if "Type=" in line:
                display_data["session_type"] = line.split("=")[1].strip()
            if "Desktop=" in line:
                display_data["desktop"] = line.split("=")[1].strip()
    
    if "session_type" not in display_data:
        display_data["session_type"] = "unknown"
    if "desktop" not in display_data:
        display_data["desktop"] = "KDE" if display_data.get("display_manager") == "sddm" else "unknown"
    
    # KScreen configs - search specific user directories, not entire /home
    home_dir = run("echo $HOME") or "/root"
    kscreen_path = f"{home_dir}/.local/share/kscreen/outputs"
    kscreen_exists = run(f"test -d {kscreen_path} && echo yes")
    display_data["kscreen_outputs"] = {}
    
    if kscreen_exists == "yes":
        files = run(f"ls {kscreen_path}/ 2>/dev/null")
        for f in files.splitlines():
            f = f.strip()
            if not f:
                continue
            content = run(f"cat {kscreen_path}/{f}")
            if content:
                try:
                    parsed = json.loads(content)
                    key = f"{home_dir.split('/home/')[1]}/{f}" if "/home/" in home_dir else f
                    display_data["kscreen_outputs"][key] = parsed
                except json.JSONDecodeError:
                    pass
    
    # Xorg config
    xorg = run("cat /etc/X11/xorg.conf 2>/dev/null")
    if xorg:
        display_data["xorg_conf"] = xorg
    
    xorg_d = run("ls /etc/X11/xorg.conf.d/ 2>/dev/null")
    if xorg_d:
        display_data["xorg_conf_d"] = {}
        for f in xorg_d.splitlines():
            f = f.strip()
            if f and not f.endswith('.swp'):
                content = run(f"cat /etc/X11/xorg.conf.d/{f}")
                if content:
                    display_data["xorg_conf_d"][f] = content
    
    baseline["display"] = display_data
    
    # Packages
    packages = run("dpkg -l | grep -E 'kde|plasma|gnome|xfce|wayland|xorg|sddm|gdm|lightdm|mesa|intel|nvidia|wireguard|tailscale|fail2ban|ssh' | awk '{print $2}'")
    baseline["packages"] = [l.strip() for l in packages.splitlines() if l.strip()]
    
    # Services
    services = run("systemctl list-unit-files --state=enabled --type=service --no-pager | grep enabled | awk '{print $1}'")
    baseline["services"] = [l.strip().replace(".service", "") for l in services.splitlines() if l.strip()]
    
    # Network
    net_data = {}
    net_data["routes"] = run("ip route | head -5").splitlines()
    net_data["interfaces"] = run("ip -br addr show | grep -v lo").splitlines()
    net_data["dns"] = run("cat /etc/resolv.conf 2>/dev/null | grep nameserver").splitlines()
    baseline["network"] = net_data
    
    return baseline


def save_baseline(env: str, host: str, baseline: dict) -> Path:
    """Save baseline to environment's device dataset."""
    env_dir = ENVS_DIR / env
    devices_dir = env_dir / "datasets" / "devices"
    devices_dir.mkdir(parents=True, exist_ok=True)
    
    # Generate device YAML
    device_file = devices_dir / f"{host}.md"
    
    # Build display config section
    display = baseline.get("display", {})
    kscreen = display.get("kscreen_outputs", {})
    
    # Clean up display manager string
    dm = display.get("display_manager", "unknown")
    if "●" in dm:
        dm = dm.split("●")[-1].split(".service")[0].strip()
    
    # Clean up desktop string  
    desktop = display.get("desktop", "unknown")
    if not desktop or desktop == "unknown":
        if dm == "sddm":
            desktop = "KDE"
    
    session_type = display.get("session_type", "unknown")
    
    lines = [
        "---",
        f"name: {host}",
        f"hostname: {baseline['os'].get('hostname', host)}",
        f"env: {env}",
        f"status: baselined",
        f"os: {baseline['os'].get('pretty_name', 'unknown')}",
        f"kernel: {baseline['os'].get('kernel', 'unknown')}",
        f"desktop: {desktop} ({session_type})" if session_type != "unknown" else f"desktop: {desktop}",
        f"display_manager: {dm}",
        f"baseline_captured: {baseline['captured_at']}",
        "",
    ]
    
    # GPU section
    gpu = baseline.get("gpu", {})
    if gpu.get("devices"):
        lines.append("gpu:")
        for dev in gpu["devices"]:
            lines.append(f"  - {dev}")
        if gpu.get("packages"):
            lines.append("  packages:")
            for pkg in gpu["packages"]:
                lines.append(f"    - {pkg}")
        lines.append("")
    
    # Display outputs
    if kscreen:
        lines.append("display_baseline:")
        lines.append("  description: >")
        lines.append("    KScreen config files. rotation values may be counterintuitive")
        lines.append("    (e.g., rotation:1 can be correct for natively portrait panels).")
        lines.append("    Do NOT change without verifying against this baseline.")
        lines.append("  outputs:")
        for key, config in kscreen.items():
            # Config can be a dict (single output) or list of outputs
            outputs = config if isinstance(config, list) else [config]
            for out in outputs:
                if not isinstance(out, dict):
                    continue
                meta = out.get("metadata", {})
                mode = out.get("mode", {})
                size = mode.get("size", {})
                lines.append(f"    - name: {meta.get('name', 'unknown')}")
                lines.append(f"      model: {meta.get('fullname', 'unknown')}")
                lines.append(f"      edid_hash: {out.get('id', 'unknown')}")
                lines.append(f"      resolution: {size.get('width', '?')}x{size.get('height', '?')}")
                lines.append(f"      rotation: {out.get('rotation', 0)}")
                lines.append(f"      scale: {out.get('scale', 1)}")
                lines.append(f"      kscreen_file: {key}")
        lines.append("")
    
    # Packages
    if baseline.get("packages"):
        lines.append("packages_baseline:")
        for pkg in baseline["packages"][:30]:  # Limit to top 30
            lines.append(f"  - {pkg}")
        lines.append("")
    
    # Services
    if baseline.get("services"):
        lines.append("systemd_services:")
        for svc in baseline["services"][:20]:  # Limit to top 20
            lines.append(f"  - {svc}")
        lines.append("")
    
    # Network
    net = baseline.get("network", {})
    if net.get("interfaces"):
        lines.append("network_baseline:")
        lines.append("  interfaces:")
        for iface in net["interfaces"]:
            lines.append(f"    - {iface.strip()}")
        lines.append("")
    
    # Rebuild notes
    lines.extend([
        "rebuild_notes:",
        "  - Install base OS from official media",
        f"  - Install {desktop} desktop environment",
        f"  - Install {dm} display manager",
        "  - Install GPU drivers (see gpu.packages)",
        "  - Deploy SSH keys to ~/.ssh/",
        "  - Configure network and VPN",
        "  - Copy KScreen configs if applicable",
        "",
    ])
    
    device_file.write_text("\n".join(lines))
    print(f"Baseline saved to {device_file}")
    return device_file


def update_status(env: str, host: str, status: str = "baselined"):
    """Update baseline tracking status."""
    env_dir = ENVS_DIR / env
    env_dir.mkdir(parents=True, exist_ok=True)
    status_file = env_dir / "baseline-status.yml"
    
    # Read existing or create new
    entries = {}
    if status_file.exists():
        for line in status_file.read_text().splitlines():
            if ":" in line and not line.startswith("#"):
                k, v = line.split(":", 1)
                entries[k.strip()] = v.strip()
    
    entries[host] = f"{status} ({datetime.now().strftime('%Y-%m-%d')})"
    
    # Write back
    lines = [f"# Baseline status for {env}", f"# Updated: {datetime.now().isoformat()}", ""]
    for k, v in sorted(entries.items()):
        lines.append(f"{k}: {v}")
    
    status_file.write_text("\n".join(lines) + "\n")
    print(f"Status updated in {status_file}")


def diff_baseline(env: str, host: str, user: str, port: int):
    """Compare current system state against saved baseline."""
    device_file = ENVS_DIR / env / "datasets" / "devices" / f"{host}.md"
    if not device_file.exists():
        print(f"No baseline found for {host} in {env}", file=sys.stderr)
        return
    
    print(f"Capturing current state from {user}@{host}:{port}...")
    current = capture_all(host, user, port)
    
    # Parse saved baseline (simplified - just compare key fields)
    content = device_file.read_text()
    
    print(f"\n=== Baseline Comparison: {host} ===")
    print(f"Baseline file: {device_file}")
    print(f"Current capture: {current['captured_at']}")
    
    # Compare OS
    saved_os = content.split("os: ")[1].split("\n")[0] if "os: " in content else "unknown"
    current_os = current["os"].get("pretty_name", "unknown")
    status = "MATCH" if saved_os == current_os else "CHANGED"
    print(f"\nOS: [{status}] saved={saved_os} current={current_os}")
    
    # Compare kernel
    saved_kernel = content.split("kernel: ")[1].split("\n")[0] if "kernel: " in content else "unknown"
    current_kernel = current["os"].get("kernel", "unknown")
    status = "MATCH" if saved_kernel == current_kernel else "CHANGED"
    print(f"Kernel: [{status}] saved={saved_kernel} current={current_kernel}")


def show_status(env_filter: str = None):
    """Show baseline status across environments."""
    print("=== Baseline Status ===\n")
    
    envs = [env_filter] if env_filter else [
        d.name for d in ENVS_DIR.iterdir() 
        if d.is_dir() and not d.name.startswith(".")
    ]
    
    for env in sorted(envs):
        env_dir = ENVS_DIR / env
        status_file = env_dir / "baseline-status.yml"
        devices_dir = env_dir / "datasets" / "devices"
        
        print(f"[{env}]")
        
        if devices_dir.exists():
            for device_file in sorted(devices_dir.glob("*.md")):
                content = device_file.read_text()
                has_baseline = "baseline_captured:" in content
                if has_baseline:
                    captured_line = [l for l in content.splitlines() if "baseline_captured:" in l]
                    if captured_line:
                        date = captured_line[0].split("baseline_captured:")[1].strip()
                        print(f"  {device_file.stem}: baselined ({date})")
                    else:
                        print(f"  {device_file.stem}: baselined")
                else:
                    print(f"  {device_file.stem}: pending")
        elif status_file.exists():
            for line in status_file.read_text().splitlines():
                if ":" in line and not line.startswith("#"):
                    print(f"  {line}")
        else:
            print("  No device data")
        print()


def _extract_scalar(content: str, key: str) -> str:
    """Return the value of a top-level `key:` scalar line, or None."""
    for line in content.splitlines():
        if line.startswith(f"{key}:"):
            return line.split(":", 1)[1].strip()
    return None


def _list_under(content: str, header_line: str) -> list:
    """Collect `- item` entries nested under an exact `header_line`.

    Stops when indentation dedents to the header's level or shallower.
    Line-based on purpose: the device baseline is human-readable markdown,
    not strict YAML (mirrors diff_baseline / show_status parsing).
    """
    out = []
    header_indent = len(header_line) - len(header_line.lstrip())
    collecting = False
    for line in content.splitlines():
        if not collecting:
            if line.rstrip() == header_line.rstrip():
                collecting = True
            continue
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        if indent <= header_indent:
            break
        stripped = line.strip()
        if stripped.startswith("- "):
            out.append(stripped[2:].strip())
    return out


def rebuild_baseline(env: str, host: str):
    """Generate a restage script from the saved baseline device YAML."""
    device_file = ENVS_DIR / env / "datasets" / "devices" / f"{host}.md"
    if not device_file.exists():
        print(f"No baseline found for {host} in {env} — run 'capture' first.", file=sys.stderr)
        return None

    content = device_file.read_text()
    os_name = _extract_scalar(content, "os") or "unknown"
    kernel = _extract_scalar(content, "kernel") or "unknown"
    desktop = _extract_scalar(content, "desktop") or "unknown"
    dm = _extract_scalar(content, "display_manager") or "unknown"
    captured = _extract_scalar(content, "baseline_captured") or "unknown"
    packages = _list_under(content, "packages_baseline:")
    gpu_packages = [p.split()[0] for p in _list_under(content, "  packages:")]
    notes = _list_under(content, "rebuild_notes:")

    # De-duplicate packages, GPU drivers first, preserving order.
    pkgs, seen = [], set()
    for p in gpu_packages + packages:
        p = p.strip()
        if p and p not in seen:
            seen.add(p)
            pkgs.append(p)

    lines = [
        "#!/usr/bin/env bash",
        "#",
        f"# Restage script for {host} ({env})",
        f"# Generated by baseline.py from {device_file.name}",
        f"# Baseline captured: {captured}",
        f"# Target OS: {os_name} (kernel {kernel})",
        "#",
        "# REVIEW BEFORE RUNNING. This is a starting point, not a turnkey installer:",
        "# base OS install and disk/partition setup are assumed already done.",
        "set -euo pipefail",
        "",
        'if [[ $EUID -ne 0 ]]; then echo "Run as root (or via sudo)." >&2; exit 1; fi',
        "",
        'echo ">>> Refreshing package lists"',
        "apt-get update",
        "",
    ]
    if pkgs:
        lines.append('echo ">>> Installing baseline packages"')
        lines.append("apt-get install -y \\")
        for i, p in enumerate(pkgs):
            sep = " \\" if i < len(pkgs) - 1 else ""
            lines.append(f"  {p}{sep}")
        lines.append("")
    lines.append(f'echo ">>> Desktop environment expected: {desktop}"')
    lines.append(f'echo ">>> Display manager expected: {dm}"')
    lines.append("")
    if notes:
        lines.append('echo ">>> Manual rebuild steps (from baseline rebuild_notes):"')
        for n in notes:
            lines.append(f'echo "  - {n}"')
        lines.append("")
        lines.append("# The steps above need operator action; automate them as they stabilise.")
    lines.append('echo ">>> Rebuild scaffold complete."')
    lines.append("")

    rebuild_dir = ENVS_DIR / env / "rebuild"
    rebuild_dir.mkdir(parents=True, exist_ok=True)
    script_file = rebuild_dir / f"{host}-rebuild.sh"
    script_file.write_text("\n".join(lines))
    script_file.chmod(0o755)
    print(f"Rebuild script generated: {script_file}")
    print("Review it before running — it assumes the base OS is already installed.")
    return script_file


def main():
    parser = argparse.ArgumentParser(description="System baseline capture and comparison")
    subparsers = parser.add_subparsers(dest="command", required=True)
    
    # Capture
    cap = subparsers.add_parser("capture", help="Capture system baseline")
    cap.add_argument("env", help="Environment name")
    cap.add_argument("host", help="Host to capture")
    cap.add_argument("--ssh-user", default="root", help="SSH user")
    cap.add_argument("--ssh-port", type=int, default=22, help="SSH port")
    
    # Diff
    d = subparsers.add_parser("diff", help="Compare against baseline")
    d.add_argument("env", help="Environment name")
    d.add_argument("host", help="Host to compare")
    d.add_argument("--ssh-user", default="root", help="SSH user")
    d.add_argument("--ssh-port", type=int, default=22, help="SSH port")
    
    # Status
    s = subparsers.add_parser("status", help="Show baseline status")
    s.add_argument("env", nargs="?", help="Filter by environment")
    
    # Rebuild
    r = subparsers.add_parser("rebuild", help="Generate rebuild script")
    r.add_argument("env", help="Environment name")
    r.add_argument("host", help="Host to rebuild")
    
    args = parser.parse_args()
    
    if args.command == "capture":
        baseline = capture_all(args.host, args.ssh_user, args.ssh_port)
        save_baseline(args.env, args.host, baseline)
        update_status(args.env, args.host)
        
    elif args.command == "diff":
        diff_baseline(args.env, args.host, args.ssh_user, args.ssh_port)
        
    elif args.command == "status":
        show_status(args.env)
        
    elif args.command == "rebuild":
        rebuild_baseline(args.env, args.host)


if __name__ == "__main__":
    main()
