"""The work rescued from an abandoned branch (opskit #184).

Three commits sat on `erp-stack-single-site-multihost-and-dns` for 18 days with
no PR, 119 commits behind main, found only because the #182 cleanup cycle
refused to delete a branch carrying unmerged commits. Each item is pinned here
so it cannot be lost a second time — and because two of them encode field
findings that would be expensive to rediscover.
"""

import re
from pathlib import Path

import jinja2
import yaml

ROOT = Path(__file__).resolve().parents[1]
CLOUDFLARE = ROOT / "ansible" / "playbooks" / "configure-cloudflare-dns.yml"
DNS_ZONES = ROOT / "ansible" / "playbooks" / "configure-dns-zones.yml"
VERIFY = ROOT / "ansible" / "roles" / "erp_stack" / "tasks" / "verify.yml"
ERP_DEFAULTS = ROOT / "ansible" / "roles" / "erp_stack" / "defaults" / "main.yml"
COMPOSE = ROOT / "ansible" / "roles" / "erp_stack" / "templates" / "compose.yml.j2"

RFC1918 = re.compile(
    r"\b(10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
    r"|192\.168\.\d{1,3}\.\d{1,3}"
    r"|172\.(1[6-9]|2[0-9]|3[01])\.\d{1,3}\.\d{1,3})\b"
)


def _tasks(path):
    return yaml.safe_load(path.read_text())[0]["tasks"]


# ── the Cloudflare playbook, absent from main entirely ───────────────────────

def test_the_cloudflare_playbook_exists_and_parses():
    assert CLOUDFLARE.is_file()
    assert _tasks(CLOUDFLARE)


def test_it_carries_no_real_zones_addresses_or_tokens():
    """It is data-driven from the environment layer; a committed zone name or
    token would be exactly what docs/client-data-policy.md forbids."""
    text = CLOUDFLARE.read_text()
    assert not RFC1918.search(text)
    for shape in ("dash.cloudflare.com/", "Bearer ", "api_key"):
        assert shape not in text.replace(
            "dash.cloudflare.com -> My Profile", ""), f"{shape} looks like real data"


def test_every_zone_must_have_a_token_before_anything_is_changed():
    """A missing token would otherwise surface as a per-record failure partway
    through, leaving a zone half-applied."""
    names = [str(t.get("name", "")) for t in _tasks(CLOUDFLARE)]
    assert any("token" in n.lower() for n in names)

    assert_idx = next(i for i, n in enumerate(names) if "token" in n.lower())
    apply_idx = next(i for i, n in enumerate(names) if "Ensure DNS records" in n)
    assert assert_idx < apply_idx


def test_records_are_unproxied_by_default():
    """proxied: true breaks ACME HTTP-01 validation, which is how certificates
    are issued here."""
    text = CLOUDFLARE.read_text()
    assert "item.1.proxied | default(false)" in text


# ── the DNS apex fix ─────────────────────────────────────────────────────────

def _render_domain(record_name, zone):
    """Render the real expression from the playbook, not a copy of it."""
    task = next(t for t in _tasks(DNS_ZONES)
                if "Add records to zones" in str(t.get("name", "")))
    expr = str(task["ansible.builtin.uri"]["body"]["domain"])
    return jinja2.Environment().from_string(expr).render(
        item={0: {"name": zone}, 1: {"name": record_name}})


def test_an_apex_record_names_the_zone_itself():
    """`@` means the zone apex. Concatenating it produced '@.example.org' — a
    real record, at the wrong name, that nothing would flag."""
    assert _render_domain("@", "example.org") == "example.org"
    assert _render_domain("", "example.org") == "example.org"


def test_an_ordinary_record_is_still_a_child_of_the_zone():
    assert _render_domain("www", "example.org") == "www.example.org"


# ── the curl-over-uri field finding ──────────────────────────────────────────

def test_the_frontend_probe_does_not_use_the_uri_module():
    """`uri` imports python-cryptography on the TARGET, which fails on hosts
    whose system python lacks a matching _cffi_backend — seen on python3.14.
    The reason is recorded in the file so it is not 'simplified' back."""
    probe = next(t for t in yaml.safe_load(VERIFY.read_text())
                 if "Probe" in str(t.get("name", "")))

    # The parsed task, not the file text — the comment explaining the change
    # names the module it replaced, and must not itself trip this.
    assert "ansible.builtin.uri" not in probe
    assert "curl" in str(probe["ansible.builtin.command"]["cmd"])
    assert "_cffi_backend" in VERIFY.read_text(), (
        "the reason must survive with the change, or it gets 'simplified' back"
    )


def test_the_probe_is_not_reported_as_a_change():
    probe = next(t for t in yaml.safe_load(VERIFY.read_text())
                 if "Probe" in str(t.get("name", "")))
    assert probe.get("changed_when") is False
    assert probe.get("until"), "a probe without retries fails on a slow start"


# ── the single-site multi-host option ────────────────────────────────────────

def test_the_site_name_header_is_configurable():
    defaults = yaml.safe_load(ERP_DEFAULTS.read_text())
    assert "erp_stack_site_name_header" in defaults


def test_its_default_preserves_the_existing_behaviour():
    """Rescued work must not change what already-deployed stacks do. `$$host`
    is what the template hardcoded before."""
    defaults = yaml.safe_load(ERP_DEFAULTS.read_text())
    assert defaults["erp_stack_site_name_header"] == "$$host"
    assert "FRAPPE_SITE_NAME_HEADER: {{ erp_stack_site_name_header }}" in \
        COMPOSE.read_text()
