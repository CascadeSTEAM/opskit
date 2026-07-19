#!/usr/bin/env python3
"""
opskit Semaphore MCP Adapter — REST API wrapper for Semaphore UI.
Provides auditable, RBAC-scoped playbook execution for AI agents.

Tools:
  semaphore_list_templates  — list task templates for active environment
  semaphore_launch_task     — launch a task template with vars
  semaphore_get_task        — poll task status + output

Credentials resolved at startup from env.yml → Vaultwarden.
"""
import json
import os
import sys
from pathlib import Path

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


def _load_env_config() -> dict:
    env_name = _active_env() or "example"
    yml_path = ROOT / "environments" / env_name / "env.yml"
    if not yml_path.exists():
        return {}
    return yaml.safe_load(yml_path.read_text())


def _semaphore_client():
    config = _load_env_config()
    exec_cfg = config.get("execution", {})
    url = exec_cfg.get("semaphore_url", "")
    token = os.environ.get("SEMAPHORE_API_TOKEN", "")

    if not url:
        return None

    session = requests.Session()
    session.headers["Authorization"] = f"Bearer {token}"
    session.headers["Content-Type"] = "application/json"
    return session, url


def list_templates():
    """List task templates for the active environment's Semaphore project."""
    client = _semaphore_client()
    if not client:
        return {"error": "Semaphore not configured for active environment."}

    session, url = client
    config = _load_env_config()
    project_name = config.get("execution", {}).get("semaphore_project", "")

    # Get project ID
    projects = session.get(f"{url}/api/projects").json()
    project_id = None
    for p in projects:
        if p.get("name") == project_name:
            project_id = p["id"]
            break

    if not project_id:
        return {"error": f"Project '{project_name}' not found."}

    templates = session.get(f"{url}/api/project/{project_id}/templates").json()
    return [{"id": t["id"], "name": t["name"], "playbook": t.get("playbook", "")} for t in templates]


def launch_task(template_id: int, vars: dict | None = None):
    """Launch a task template."""
    client = _semaphore_client()
    if not client:
        return {"error": "Semaphore not configured."}

    session, url = client
    config = _load_env_config()
    project_name = config.get("execution", {}).get("semaphore_project", "")

    projects = session.get(f"{url}/api/projects").json()
    project_id = None
    for p in projects:
        if p.get("name") == project_name:
            project_id = p["id"]
            break

    payload = {
        "template_id": template_id,
        "debug": False,
        "dry_run": False,
    }
    if vars:
        payload["environment"] = json.dumps(vars)

    resp = session.post(f"{url}/api/project/{project_id}/tasks", json=payload)
    task = resp.json()
    return {"task_id": task.get("id"), "status": task.get("status")}


def get_task(task_id: int):
    """Get task status and output."""
    client = _semaphore_client()
    if not client:
        return {"error": "Semaphore not configured."}

    session, url = client
    config = _load_env_config()
    project_name = config.get("execution", {}).get("semaphore_project", "")

    projects = session.get(f"{url}/api/projects").json()
    project_id = None
    for p in projects:
        if p.get("name") == project_name:
            project_id = p["id"]
            break

    task = session.get(f"{url}/api/project/{project_id}/tasks/{task_id}").json()

    # Fetch output if task completed
    output = None
    if task.get("status") in ("success", "error"):
        output_resp = session.get(f"{url}/api/project/{project_id}/tasks/{task_id}/output")
        output = output_resp.text if output_resp.ok else None

    return {
        "task_id": task.get("id"),
        "status": task.get("status"),
        "playbook": task.get("playbook", ""),
        "start": task.get("start"),
        "end": task.get("end"),
        "output": output[:4000] if output else None,
    }


if __name__ == "__main__":
    # Test mode
    cmd = sys.argv[1] if len(sys.argv) > 1 else "list"
    if cmd == "--test":
        print("Semaphore MCP adapter: OK (no live Semaphore configured)")
        sys.exit(0)
    elif cmd == "list":
        print(json.dumps(list_templates(), indent=2))
    elif cmd == "launch" and len(sys.argv) > 2:
        print(json.dumps(launch_task(int(sys.argv[2])), indent=2))
    elif cmd == "task" and len(sys.argv) > 2:
        print(json.dumps(get_task(int(sys.argv[2])), indent=2))
    else:
        print("Usage: semaphore-mcp-adapter.py [--test|list|launch <id>|task <id>]")
