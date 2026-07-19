#!/usr/bin/env python3
"""
opskit semaphore-sync — idempotently syncs the Ansible catalogue to a Semaphore UI instance.

Reads:
  environments/<env>/env.yml   — environment config + semaphore endpoint
  ansible/playbooks/           — playbook catalogue with metadata

Creates/updates:
  Semaphore project (one per environment)
  Semaphore inventory (from environments/<env>/ansible/inventory.yml)
  Semaphore repository (this git repo)
  Semaphore task templates (one per playbook, with ticket survey for state-changing plays)

Usage:
  bin/semaphore-sync.py [--env ENV] [--dry-run]
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import requests
import yaml

ROOT = Path(__file__).resolve().parents[1]


def _active_env() -> str:
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("ACTIVE_ENV="):
                return line.split("=", 1)[1].strip().strip('"')
    return ""


def _load_env_yml(env_name: str) -> dict:
    path = ROOT / "environments" / env_name / "env.yml"
    return yaml.safe_load(path.read_text())


def _playbook_metadata(playbook_path: Path) -> dict:
    """Extract metadata from a playbook YAML file."""
    try:
        content = yaml.safe_load(playbook_path.read_text())
    except Exception:
        return {}

    if not isinstance(content, list) or not content:
        return {}

    play = content[0]
    return {
        "name": play.get("name", playbook_path.stem),
        "hosts": play.get("hosts", "all"),
        "file": str(playbook_path.relative_to(ROOT / "ansible" / "playbooks")),
    }


def _is_state_changing(playbook_path: Path) -> bool:
    """Heuristic: playbooks with 'deploy', 'configure', 'install', 'provision' are state-changing."""
    name = playbook_path.name.lower()
    for keyword in ["provision", "deploy", "configure", "install", "setup", "migrate"]:
        if keyword in name:
            return True

    content = yaml.safe_load(playbook_path.read_text())
    if isinstance(content, list):
        for play in content:
            if play.get("become", False):
                return True
    return False


class SemaphoreSync:
    def __init__(self, env_name: str, dry_run: bool = False):
        self.env_name = env_name
        self.dry_run = dry_run
        config = _load_env_yml(env_name)
        exec_cfg = config.get("execution", {})
        self.api_url = exec_cfg.get("semaphore_url", "")
        self.project_name = exec_cfg.get("semaphore_project", env_name)
        self.token = os.environ.get("SEMAPHORE_API_TOKEN", "")
        self.session = requests.Session()
        if self.token:
            self.session.headers["Authorization"] = f"Bearer {self.token}"
        self.session.headers["Content-Type"] = "application/json"

    def _api(self, method: str, path: str, data: dict | None = None) -> dict:
        url = f"{self.api_url}/api/{path}"
        if self.dry_run:
            print(f"  [DRY RUN] {method} {url}")
            return {}
        resp = self.session.request(method, url, json=data)
        resp.raise_for_status()
        return resp.json() if resp.text else {}

    def sync_project(self) -> int:
        """Create or get project ID."""
        projects = self._api("GET", "projects")
        for p in projects:
            if p.get("name") == self.project_name:
                print(f"  Project '{self.project_name}' already exists (id={p['id']})")
                return p["id"]

        result = self._api("POST", "projects", {"name": self.project_name})
        print(f"  Created project '{self.project_name}' (id={result.get('id')})")
        return result["id"]

    def sync_inventory(self, project_id: int) -> int:
        """Create or get inventory ID from the env's inventory.yml."""
        inv_path = ROOT / "environments" / self.env_name / "ansible" / "inventory.yml"
        inv_name = f"{self.env_name}-inventory"

        inventories = self._api("GET", f"project/{project_id}/inventory")
        for inv in inventories:
            if inv.get("name") == inv_name:
                print(f"  Inventory '{inv_name}' already exists (id={inv['id']})")
                return inv["id"]

        inv_content = inv_path.read_text() if inv_path.exists() else ""
        result = self._api("POST", f"project/{project_id}/inventory", {
            "name": inv_name,
            "type": "static",
            "inventory": inv_content,
        })
        print(f"  Created inventory '{inv_name}' (id={result.get('id')})")
        return result["id"]

    def sync_playbook_templates(self, project_id: int, inventory_id: int) -> list[int]:
        """Create task templates for each playbook in the catalogue."""
        playbooks_dir = ROOT / "ansible" / "playbooks"
        env_path = str(ROOT / "environments" / self.env_name / "ansible")
        template_ids = []

        for pb in sorted(playbooks_dir.glob("*.yml")):
            meta = _playbook_metadata(pb)
            template_name = pb.stem
            is_stateful = _is_state_changing(pb)

            # Check if template already exists
            existing = self._api("GET", f"project/{project_id}/templates")
            found = None
            for t in existing:
                if t.get("name") == template_name:
                    found = t
                    break

            playbook_rel = str(pb.relative_to(ROOT))
            args_data = {
                "name": template_name,
                "playbook": playbook_rel,
                "inventory_id": inventory_id,
                "project_id": project_id,
                "type": "task",
                "arguments": json.dumps(["-i", env_path]),
            }

            if is_stateful:
                args_data["survey_vars"] = json.dumps([
                    {"name": "ticket_id", "title": "Ticket ID", "required": True,
                     "description": f"Change control ticket ({self.env_name})"}
                ])

            if found:
                print(f"  Template '{template_name}' already exists (id={found['id']})")
                template_ids.append(found["id"])
                continue

            result = self._api("POST", f"project/{project_id}/templates", args_data)
            print(f"  Created template '{template_name}' (id={result.get('id')})")
            template_ids.append(result.get("id"))

        return template_ids

    def sync(self) -> dict:
        print(f"\nSyncing environment '{self.env_name}' to Semaphore...")
        if not self.api_url:
            print("  Semaphore not configured — skipping.")
            return {}

        project_id = self.sync_project()
        inventory_id = self.sync_inventory(project_id)
        template_ids = self.sync_playbook_templates(project_id, inventory_id)

        summary = {
            "project_id": project_id,
            "inventory_id": inventory_id,
            "templates": len(template_ids),
        }
        print(f"  Done — {summary}")
        return summary


def main():
    parser = argparse.ArgumentParser(description="Sync opskit catalogue to Semaphore UI")
    parser.add_argument("--env", help="Environment name (default: ACTIVE_ENV)")
    parser.add_argument("--dry-run", action="store_true", help="Preview only")
    args = parser.parse_args()

    env_name = args.env or _active_env()
    if not env_name:
        print("ERROR: No environment specified.", file=sys.stderr)
        sys.exit(1)

    syncer = SemaphoreSync(env_name, dry_run=args.dry_run)
    syncer.sync()


if __name__ == "__main__":
    main()
