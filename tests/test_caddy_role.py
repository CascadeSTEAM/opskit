"""Caddy role: per-route TLS strategy (opskit #242).

`internal: true` only restricts source IP (imports the `internal_only`
snippet) — it says nothing about how Caddy obtains a certificate. Automatic
HTTPS always tries public ACME unless a route opts into `tls_internal`, which
must render Caddy's local-CA directive instead.
"""

from pathlib import Path

import jinja2

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "ansible" / "roles" / "caddy" / "templates" / "Caddyfile.j2"


def _render(caddy_routes):
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(str(TEMPLATE.parent)))
    template = env.get_template(TEMPLATE.name)
    return template.render(
        caddy_global_email="support@example.org",
        caddy_admin_listen="127.0.0.1:2019",
        caddy_internal_subnets=["192.0.2.0/24"],
        caddy_routes=caddy_routes,
        ansible_facts={"default_ipv4": {"address": "192.0.2.1"}},
    )


def test_tls_internal_route_gets_the_local_ca_directive():
    rendered = _render([
        {"domain": "dev-clone.example.org", "target": "192.0.2.30:8080",
         "internal": True, "tls_internal": True},
    ])
    block = rendered.split("dev-clone.example.org {", 1)[1].split("\n}", 1)[0]
    assert "tls internal" in block


def test_a_route_without_the_flag_does_not_get_it():
    rendered = _render([
        {"domain": "public.example.org", "target": "192.0.2.10:80",
         "internal": False},
    ])
    block = rendered.split("public.example.org {", 1)[1].split("\n}", 1)[0]
    assert "tls internal" not in block


def test_internal_true_alone_does_not_imply_tls_internal():
    """The bug this issue fixes: `internal` is IP-filtering only."""
    rendered = _render([
        {"domain": "ip-filtered.example.org", "target": "192.0.2.20:80",
         "internal": True},
    ])
    block = rendered.split("ip-filtered.example.org {", 1)[1].split("\n}", 1)[0]
    assert "import internal_only" in block
    assert "tls internal" not in block


def test_tls_internal_combines_with_backend_tls_skip_verify():
    """The realistic shape: an internal-only, never-public route whose
    backend also speaks self-signed HTTPS (own reverse_proxy sub-block)."""
    rendered = _render([
        {"domain": "dev-clone.example.org", "target": "192.0.2.30:8080",
         "internal": True, "tls_internal": True, "backend_tls_skip_verify": True},
    ])
    assert "tls internal" in rendered
    assert "reverse_proxy https://192.0.2.30:8080 {" in rendered
    assert "tls_insecure_skip_verify" in rendered
