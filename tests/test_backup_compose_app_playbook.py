"""Static validation of ansible/playbooks/backup-compose-app.yml (#429).

Installs a nightly cron job that runs a compose project's own backup script, then prunes old
backups. Never executed in CI, so the properties that matter are pinned here.

Failure modes that are silent and expensive, one test each:

1. Pruning after a FAILED backup (the only good copy gets deleted while no new one exists).
2. A prune that can reach outside the backup directory, or delete things that are not backups.
3. Running as a shell string with interpolated user values instead of fixed, quoted paths.
4. A job that is not idempotent, so every run rewrites it and reports a change.
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
PLAYBOOK = ROOT / "ansible" / "playbooks" / "backup-compose-app.yml"

RFC1918 = re.compile(
    r"\b(10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
    r"|192\.168\.\d{1,3}\.\d{1,3}"
    r"|172\.(1[6-9]|2[0-9]|3[01])\.\d{1,3}\.\d{1,3})\b"
)


def _play():
    return yaml.safe_load(PLAYBOOK.read_text())[0]


def _tasks():
    return _play()["tasks"]


def _text():
    return PLAYBOOK.read_text()


def _task_named(fragment):
    hits = [t for t in _tasks() if fragment.lower() in str(t.get("name", "")).lower()]
    assert hits, f"no task whose name contains {fragment!r}"
    return hits[0]


def _wrapper_body():
    task = _task_named("backup wrapper")
    return task["ansible.builtin.copy"]["content"]


def test_playbook_exists_and_parses():
    assert PLAYBOOK.is_file()
    assert isinstance(_play(), dict)


def test_it_hardcodes_no_infrastructure_addresses():
    assert not RFC1918.findall(_text()), "committed playbooks stay environment-agnostic (#134)"


def test_the_target_is_supplied_not_hardcoded():
    assert "target_host" in str(_play()["hosts"])


def test_app_name_has_no_default_and_is_asserted_first():
    assert "app_name" not in (_play().get("vars") or {})
    first = _tasks()[0]
    assert "ansible.builtin.assert" in first
    assert "app_name is defined" in " ".join(str(c) for c in first["ansible.builtin.assert"]["that"])


def test_names_and_numbers_are_validated_before_they_reach_a_file():
    text = " ".join(str(t.get("ansible.builtin.assert", "")) for t in _tasks())
    assert "app_name is match" in text, "app_name ends up in file names and a cron line"
    assert "backup_keep" in text and "backup_hour" in text and "backup_minute" in text


def test_the_wrapper_stops_on_any_error():
    assert re.search(r"^set -eu", _wrapper_body(), re.M), "a failed backup must stop the script before pruning"


def test_pruning_happens_only_after_the_backup_command():
    body = _wrapper_body()
    backup = body.index("docker-backup") if "docker-backup" in body else body.index("backup_script")
    prune = body.index("rm -rf")
    assert backup < prune, "never prune before a new backup exists"


def test_pruning_is_limited_to_timestamp_named_directories_in_the_backup_dir():
    body = _wrapper_body()
    assert re.search(r"\[0-9\]", body), "only directories named like a UTC timestamp may be pruned"
    assert "rm -rf --" in body, "end options before the path list"
    assert "head -n -" in body or "tail -n +" in body, "keep the newest N"
    for bad in ("rm -rf /", "rm -rf *", "rm -rf ."):
        assert bad not in body


def test_the_job_never_touches_volumes_or_the_running_stack():
    for bad in ("compose down", "down -v", "docker volume", "docker system prune", "compose rm"):
        assert bad not in _text(), f"{bad!r} has no place in a backup play"


def test_the_job_runs_as_a_cron_entry_with_a_logfile():
    task = _task_named("Schedule the nightly backup")
    assert "ansible.builtin.cron" in task or "ansible.builtin.copy" in task
    assert "/etc/cron.d/" in str(task)
    assert "backup.log" in _text() or "backup_log" in _text()


def test_the_cron_job_uses_the_wrapper_not_inline_shell():
    assert "/usr/local/sbin/" in _text()


def test_it_is_idempotent_and_check_mode_friendly():
    wrapper = _task_named("backup wrapper")["ansible.builtin.copy"]
    assert "content" in wrapper and wrapper.get("mode") in ("0750", "0700", "0755")
    assert not any("ansible.builtin.shell" in t for t in _tasks()), "use declarative modules"


def test_the_report_says_how_to_restore_and_what_is_not_covered():
    text = str(_task_named("Report")["ansible.builtin.debug"])
    assert "restore" in text.lower()
    assert "off-box" in text.lower() or "offsite" in text.lower()


@pytest.mark.skipif(shutil.which("ansible-playbook") is None, reason="ansible-playbook not installed")
def test_playbook_passes_ansible_syntax_check():
    result = subprocess.run(
        ["ansible-playbook", "--syntax-check", "-i", "localhost,", "-e", "target_host=localhost", str(PLAYBOOK)],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert result.returncode == 0, result.stderr
