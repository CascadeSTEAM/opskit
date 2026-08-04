#!/usr/bin/env python3
"""
WireGuard MCP Server — VPN peer lifecycle against WGDashboard (opskit issue #90).

Tools:
  wireguard_list_peers      List peers on an environment's configuration
  wireguard_create_peer     Create a peer: allocate address, mirror scope, store nothing secret
  wireguard_deliver_config  Hand the client config over as a one-time Bitwarden Send
  wireguard_revoke_peer     Delete a peer and verify it is gone from the running interface
  wireguard_audit           Report peers that look unowned, unused, or over-scoped

WHY THIS EXISTS
  Peer management was undocumented manual clicking in a web UI. The cost was not
  effort, it was correctness: addresses picked by eye, DNS forgotten, configs
  handed over in chat, no record of who holds access, and no revocation path. A
  year of that produces exactly what issue #90 documents — live full-tunnel
  credentials with no known owner.

THE ONE RULE THIS MODULE ENFORCES
  A client config contains a private key. Whoever holds it *is* that VPN
  account. So the config is NEVER returned through a tool result: not by
  create_peer, not by any getter. There is deliberately no wireguard_get_config.
  It leaves exactly one way — wireguard_deliver_config — which puts it in a
  Bitwarden Send with a finite access count and a deletion date, and returns
  only the access URL.

  This matters more for an agent than for a human. A tool result is transcript,
  and transcripts are logged, summarised, and pasted elsewhere. A returned
  config would be a credential leak by construction, not by accident.

AUTHENTICATION — the trap that motivated this module
  The dashboard account has TOTP enabled. A password-only login fails with
  "your username, password or OTP is incorrect", which reads as a *wrong
  password* and sends the operator hunting for a rotated credential (opskit #90).
  So this module treats the TOTP seed as a required credential, not an optional
  extra, and says so when it is missing.

  Codes are generated in-process from the seed (stdlib hmac — no new
  dependency). The seed is supplied per environment via env var, resolved from
  the vault by bin/mcp-run.sh with `"field": "totp"`.

CONFIGURATION
  mcp/tenants-wireguard.local.json (gitignored — see tenants-wireguard.example.json):

    {
      "<env>": {
        "url": "http://<host>:<port>",
        "configuration": "wg0",
        "username": "admin",
        "env_pass": "WG_<ENV>_PASS",
        "env_totp": "WG_<ENV>_TOTP_SEED",
        "reference_peer": "<existing peer to mirror scope from>",
        "dns": "<resolver handed to clients>",
        "description": "..."
      }
    }

  WIREGUARD_TENANTS_FILE overrides the path (the test suite uses this so it
  never reads a developer's real file — opskit #76).

Usage:
  python3 mcp/wireguard-mcp-server.py           # stdio MCP server
  bin/mcp-run.sh wireguard                      # with secrets from the vault
"""

import base64
import hashlib
import hmac
import json
import os
import re
import struct
import subprocess
import sys
import time
from pathlib import Path

import requests

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:  # pragma: no cover - dependency surfaced by mcp-run.sh --check
    print("ERROR: mcp package not importable — run: make deps", file=sys.stderr)
    raise

_TENANTS_FILE = (
    Path(os.environ["WIREGUARD_TENANTS_FILE"])
    if os.environ.get("WIREGUARD_TENANTS_FILE")
    else Path(__file__).parent / "tenants-wireguard.local.json"
)


def _load_tenants() -> dict:
    if _TENANTS_FILE.exists():
        return json.loads(_TENANTS_FILE.read_text())
    return {}


TENANTS = _load_tenants()

mcp = FastMCP("wireguard-peers")

# WGDashboard reports "no handshake yet" with this literal string. It is reset
# when the interface restarts, so it means "not since the last restart" and is
# NEVER evidence that a peer has never been used. wireguard_audit leans on
# cumulative transfer instead, and says so.
_NO_HANDSHAKE = "No Handshake"


# ── helpers ───────────────────────────────────────────────────────────────────
def _err(msg: str, **extra) -> str:
    return json.dumps({"ok": False, "error": msg, **extra}, indent=2)


def _ok(**payload) -> str:
    return json.dumps({"ok": True, **payload}, indent=2)


def _totp_now(seed: str) -> str:
    """Current 6-digit TOTP code. Accepts a bare base32 secret or an
    otpauth:// URI, which is how a vault item may store it."""
    secret = seed.strip()
    if secret.lower().startswith("otpauth://"):
        m = re.search(r"[?&]secret=([^&]+)", secret, re.IGNORECASE)
        if not m:
            raise ValueError("otpauth URI contains no secret parameter")
        secret = m.group(1)
    secret = re.sub(r"\s+", "", secret).upper()
    secret += "=" * (-len(secret) % 8)  # base32 needs padding
    key = base64.b32decode(secret, casefold=True)
    counter = int(time.time()) // 30
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return f"{code % 1_000_000:06d}"


def _cfg(env: str):
    if env not in TENANTS:
        available = ", ".join(sorted(TENANTS)) or "(none configured)"
        return None, _err(
            f"unknown environment '{env}'",
            available=available,
            hint=f"add it to {_TENANTS_FILE.name}",
        )
    return TENANTS[env], None


# Authenticated sessions are cached per environment. Two reasons, both real:
# the dashboard is reached over plain HTTP inside the VPN tunnel, so every
# login puts the password on the wire again; and a multi-step flow
# (create -> deliver) would otherwise perform four separate logins. A cached
# cookie can still go stale, so _fetch_peers_retrying re-authenticates once
# before giving up.
_SESSIONS: dict = {}


def _session(env: str, fresh: bool = False):
    """Authenticated requests.Session, or (None, error-json). Cached per env."""
    if not fresh and env in _SESSIONS:
        return _SESSIONS[env], None

    cfg, error = _cfg(env)
    if error:
        return None, error

    password = os.environ.get(cfg.get("env_pass", ""), "")
    seed = os.environ.get(cfg.get("env_totp", ""), "")
    if not password:
        return None, _err(
            f"env var {cfg.get('env_pass')} is not set",
            hint="secrets come from the vault via bin/mcp-run.sh wireguard",
        )
    if not seed:
        return None, _err(
            f"env var {cfg.get('env_totp')} is not set — this dashboard requires TOTP",
            hint=(
                "map the vault item's TOTP seed with {\"field\": \"totp\"} in "
                "mcp/vault-map.local.json. Without it the login fails with a "
                "message that blames the password (opskit #90)."
            ),
        )

    try:
        code = _totp_now(seed)
    except Exception as exc:
        return None, _err(f"could not derive a TOTP code from the seed: {exc}")

    s = requests.Session()
    try:
        resp = s.post(
            f"{cfg['url'].rstrip('/')}/api/authenticate",
            json={"username": cfg.get("username", "admin"), "password": password, "totp": code},
            timeout=15,
        )
        resp.raise_for_status()
        body = resp.json()
    except Exception as exc:
        return None, _err(f"dashboard unreachable or returned junk: {exc}")

    if not body.get("status"):
        return None, _err(
            "authentication rejected",
            detail=body.get("message") or "(no message)",
            hint=(
                "the dashboard reports username, password and OTP failures with "
                "one message — a fresh code is generated per call, so suspect "
                "the password or a clock skew over 30s before assuming the code."
            ),
        )
    _SESSIONS[env] = (s, cfg)
    return (s, cfg), None


def _peers_retrying(env: str):
    """(peers, info, cfg, session, None) or (None, None, None, None, error-json).

    Re-authenticates once if the first read fails, so a cached cookie that has
    expired self-heals instead of surfacing as a confusing read error.
    """
    got, error = _session(env)
    if error:
        return None, None, None, None, error
    for attempt in (1, 2):
        s, cfg = got
        try:
            peers, info = _fetch_peers(s, cfg)
            return peers, info, cfg, s, None
        except Exception as exc:
            if attempt == 2:
                return None, None, None, None, _err(
                    f"could not read peers after re-authenticating: {exc}")
            _SESSIONS.pop(env, None)
            got, error = _session(env, fresh=True)
            if error:
                return None, None, None, None, error


def _fetch_peers(s, cfg) -> tuple:
    url = f"{cfg['url'].rstrip('/')}/api/getWireguardConfigurationInfo"
    resp = s.get(url, params={"configurationName": cfg["configuration"]}, timeout=20)
    resp.raise_for_status()
    data = resp.json().get("data") or {}
    return data.get("configurationPeers") or [], data.get("configurationInfo") or {}


def _public(peer: dict) -> dict:
    """Non-secret view of a peer. Never includes private_key or preshared_key."""
    return {
        "name": peer.get("name"),
        "address": peer.get("allowed_ip"),
        "scope": peer.get("endpoint_allowed_ip"),
        "dns": peer.get("DNS") or None,
        "mtu": peer.get("mtu"),
        "keepalive": peer.get("keepalive"),
        "latest_handshake": peer.get("latest_handshake"),
        "status": peer.get("status"),
        "public_key": peer.get("id") or peer.get("public_key"),
        "total_transfer_gb": (peer.get("total_data") or peer.get("cumu_data") or 0),
    }


def _next_address(peers: list, subnet_base: str) -> str:
    """Lowest unused host in the server's /24, skipping .1 (the server)."""
    used = set()
    for p in peers:
        ip = (p.get("allowed_ip") or "").split("/")[0].strip()
        if ip.startswith(subnet_base + "."):
            try:
                used.add(int(ip.rsplit(".", 1)[1]))
            except ValueError:
                continue
    for host in range(2, 255):
        if host not in used:
            return f"{subnet_base}.{host}/32"
    raise RuntimeError(f"no free address left in {subnet_base}.0/24")


def _genkeys() -> tuple:
    """(private, public) via the wg binary — the same tool the server uses."""
    try:
        priv = subprocess.run(["wg", "genkey"], capture_output=True, text=True,
                              check=True).stdout.strip()
        pub = subprocess.run(["wg", "pubkey"], input=priv, capture_output=True,
                             text=True, check=True).stdout.strip()
    except FileNotFoundError:
        raise RuntimeError("the `wg` binary is not installed — apt install wireguard-tools")
    return priv, pub


# ── tools ─────────────────────────────────────────────────────────────────────
@mcp.tool()
def wireguard_list_peers(env: str) -> str:
    """List peers on an environment's WireGuard configuration.

    Returns non-secret fields only — never a private key. Note that
    latest_handshake resets when the interface restarts, so "No Handshake"
    means "not since the last restart", not "never used".
    """
    peers, _info, cfg, _s, error = _peers_retrying(env)
    if error:
        return error
    return _ok(
        environment=env,
        configuration=cfg["configuration"],
        peer_count=len(peers),
        peers=[_public(p) for p in peers],
    )


@mcp.tool()
def wireguard_create_peer(
    env: str,
    name: str,
    mirror_peer: str = "",
    allowed_ips: str = "",
    dns: str = "",
) -> str:
    """Create a VPN peer.

    Allocates the next free client address, and by default mirrors the access
    scope of the environment's reference peer so a new user gets the same
    access the team already has rather than a hand-typed guess.

    Deliberately does NOT return the client config — it contains a private key.
    Use wireguard_deliver_config to hand it over as a one-time Bitwarden Send.

    Args:
        env: environment key from the tenants file
        name: peer name. Convention is owner_device, e.g. dana_laptop — a future
            auditor needs to know both who and which machine.
        mirror_peer: peer whose scope to copy. Defaults to the configured
            reference_peer.
        allowed_ips: explicit scope, overriding the mirror. 0.0.0.0/0 is a full
            tunnel and routes all of the user's traffic through this network.
        dns: explicit resolver, overriding the environment default.
    """
    if not name or not re.fullmatch(r"[A-Za-z0-9._-]{2,64}", name):
        return _err(
            "invalid peer name",
            hint="2-64 chars, letters/digits/dot/underscore/hyphen; convention is owner_device",
        )

    peers, info, cfg, s, error = _peers_retrying(env)
    if error:
        return error

    if any(p.get("name") == name for p in peers):
        return _err(f"a peer named '{name}' already exists", hint="pick another name, or revoke the old one first")

    # Scope: explicit > mirrored > refuse. Never silently default to a full
    # tunnel — that is a privilege decision, not a fallback.
    scope, source = allowed_ips.strip(), "explicit"
    if not scope:
        ref_name = mirror_peer.strip() or cfg.get("reference_peer", "")
        ref = next((p for p in peers if p.get("name") == ref_name), None)
        if not ref:
            return _err(
                f"no scope given and reference peer '{ref_name}' not found",
                hint="pass allowed_ips explicitly, or set reference_peer in the tenants file",
                available_peers=[p.get("name") for p in peers],
            )
        scope, source = ref.get("endpoint_allowed_ip") or "", f"mirrored from {ref_name}"
        if not scope:
            return _err(f"reference peer '{ref_name}' has no scope recorded")

    server_addr = (info.get("Address") or cfg.get("address") or "").split("/")[0]
    if not server_addr or server_addr.count(".") != 3:
        return _err("could not determine the server address to allocate from",
                    detail=f"got {server_addr!r}")
    subnet_base = server_addr.rsplit(".", 1)[0]

    try:
        address = _next_address(peers, subnet_base)
        private_key, public_key = _genkeys()
    except Exception as exc:
        return _err(str(exc))

    payload = {
        "bulkAdd": False, "bulkAddAmount": 0,
        "name": name,
        "public_key": public_key,
        "private_key": private_key,
        "allowed_ips": [address],
        "DNS": dns.strip() or cfg.get("dns", ""),
        "endpoint_allowed_ip": scope,
        "mtu": int(cfg.get("mtu", 1420)),
        "keepalive": int(cfg.get("keepalive", 21)),
        "preshared_key": "", "preshared_key_bulkAdd": False,
    }
    try:
        resp = s.post(
            f"{cfg['url'].rstrip('/')}/api/addPeers/{cfg['configuration']}",
            json=payload, timeout=30,
        )
        resp.raise_for_status()
        body = resp.json()
    except Exception as exc:
        return _err(f"peer creation failed: {exc}")
    if not body.get("status", True):
        return _err("dashboard refused the peer", detail=body.get("message"))

    # Verify against the server rather than trusting the response.
    try:
        peers_after, _ = _fetch_peers(s, cfg)
    except Exception as exc:
        return _err(f"peer may have been created but verification failed: {exc}")
    created = next((p for p in peers_after if p.get("name") == name), None)
    if not created:
        return _err("dashboard reported success but the peer is not present")

    return _ok(
        created=_public(created),
        scope_source=source,
        full_tunnel=(scope.strip() == "0.0.0.0/0"),
        config_withheld=(
            "The client config contains a private key and is deliberately not "
            "returned here. Deliver it with wireguard_deliver_config."
        ),
        next_steps=[
            f"wireguard_deliver_config(env='{env}', name='{name}') — one-time Send link",
            "record the peer owner in the environment's peer inventory",
        ],
    )


@mcp.tool()
def wireguard_deliver_config(
    env: str,
    name: str,
    delete_in_days: int = 2,
    max_access_count: int = 1,
    send_password: str = "",
) -> str:
    """Hand a peer's client config to its owner as a Bitwarden Send.

    This is the only sanctioned way the config leaves the system. It returns an
    access URL, never the config itself, so the private key never enters a
    transcript, a chat message, or an email body.

    Defaults to one-time access expiring in 2 days. Add send_password for a
    second factor you pass to the recipient out of band.
    """
    if max_access_count < 1:
        return _err("max_access_count must be at least 1")
    if not os.environ.get("BW_SESSION"):
        return _err(
            "BW_SESSION is not set — cannot create a Bitwarden Send",
            hint="export BW_SESSION=$(bw unlock --raw) before starting the runtime",
        )

    peers, _info, cfg, s, error = _peers_retrying(env)
    if error:
        return error
    peer = next((p for p in peers if p.get("name") == name), None)
    if not peer:
        return _err(f"no peer named '{name}'",
                    available_peers=[p.get("name") for p in peers])

    pubkey = peer.get("id") or peer.get("public_key")
    try:
        resp = s.get(f"{cfg['url'].rstrip('/')}/api/downloadPeer/{cfg['configuration']}",
                     params={"id": pubkey}, timeout=20)
        resp.raise_for_status()
        body = (resp.json().get("data") or {}).get("file")
    except Exception as exc:
        return _err(f"could not fetch the client config: {exc}")
    if not body:
        return _err("dashboard returned an empty config")

    # The config touches disk only inside a 0600 temp file, and is removed
    # immediately — bw send needs a file path for file Sends.
    import tempfile
    tmp = None
    try:
        fd, tmp = tempfile.mkstemp(prefix=f"{name}-", suffix=".conf")
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as fh:
            fh.write(body)
        cmd = ["bw", "send", "--file", tmp, "--name", f"{name}.conf",
               "--deleteInDays", str(delete_in_days),
               "--maxAccessCount", str(max_access_count)]
        if send_password:
            cmd += ["--password", send_password]
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
    except FileNotFoundError:
        return _err("the `bw` CLI is not installed — npm install -g @bitwarden/cli")
    except Exception as exc:
        return _err(f"could not create the Send: {exc}")
    finally:
        if tmp and os.path.exists(tmp):
            os.remove(tmp)

    if out.returncode != 0:
        return _err("bw send failed", detail=(out.stderr or out.stdout).strip()[:400])

    # `bw send` prints a bare access URL for text Sends but a full JSON object
    # for --file Sends. Verified against the live CLI: assuming the bare-URL
    # form rejected a Send that had in fact been created, orphaning an
    # unreferenced copy of the config in the vault. Handle both, and always
    # surface the Send id so an orphan can be deleted if anything downstream
    # fails.
    stdout = (out.stdout or "").strip()
    url, send_id = "", ""
    if stdout.startswith("{"):
        try:
            obj = json.loads(stdout)
            url = obj.get("accessUrl") or ""
            send_id = obj.get("id") or ""
        except json.JSONDecodeError:
            pass
    if not url:
        for line in reversed(stdout.splitlines()):
            if line.strip().startswith("http"):
                url = line.strip()
                break
    if not url:
        return _err(
            "bw send produced no access URL — a Send may still have been created",
            detail=stdout[:300],
            cleanup_hint="check `bw send list` and delete any orphan with `bw send delete <id>`",
        )

    return _ok(
        send_id=send_id or None,
        peer=name,
        access_url=url,
        expires_in_days=delete_in_days,
        max_accesses=max_access_count,
        password_protected=bool(send_password),
        reminder=(
            "Send the URL over any channel; send the Send password, if set, over "
            "a different one. The config was never written to a durable file and "
            "is not included in this result."
        ),
    )


@mcp.tool()
def wireguard_revoke_peer(env: str, name: str, confirm: bool = False) -> str:
    """Delete a peer, revoking its access immediately.

    WireGuard has no sessions to expire: removing the peer makes its private key
    inert at once. Anyone holding that config loses access with no warning, and
    because the key is stored server-side you cannot restore it — a replacement
    peer must be created and redelivered.

    Requires confirm=True. Verifies the peer is gone from the running interface
    rather than trusting the delete response.
    """
    peers, _info, cfg, s, error = _peers_retrying(env)
    if error:
        return error
    peer = next((p for p in peers if p.get("name") == name), None)
    if not peer:
        return _err(f"no peer named '{name}'",
                    available_peers=[p.get("name") for p in peers])

    if not confirm:
        return _err(
            "refusing to revoke without confirm=True",
            peer=_public(peer),
            consequence=(
                "immediate loss of access for whoever holds this config; "
                "not restorable — you would create and redeliver a new peer"
            ),
        )

    pubkey = peer.get("id") or peer.get("public_key")
    try:
        resp = s.post(f"{cfg['url'].rstrip('/')}/api/deletePeers/{cfg['configuration']}",
                      json={"peers": [pubkey]}, timeout=30)
        resp.raise_for_status()
        body = resp.json()
    except Exception as exc:
        return _err(f"revoke request failed: {exc}")
    if not body.get("status", True):
        return _err("dashboard refused the delete", detail=body.get("message"))

    try:
        peers_after, _ = _fetch_peers(s, cfg)
    except Exception as exc:
        return _err(f"delete reported success but verification failed: {exc}")
    if any(p.get("name") == name for p in peers_after):
        return _err(
            "dashboard reported success but the peer is STILL PRESENT — access not revoked",
            hint="check the dashboard directly; do not assume this peer is gone",
        )

    return _ok(
        revoked=name,
        address_freed=peer.get("allowed_ip"),
        peers_remaining=len(peers_after),
        follow_up="delete the corresponding vault item, and mark the peer inventory entry revoked",
    )


@mcp.tool()
def wireguard_audit(env: str) -> str:
    """Report peers that look unowned, unused, or over-scoped.

    This is the check that catches what manual peer creation leaves behind:
    credentials nobody can account for. Findings are advisory — a peer with no
    recent handshake may simply belong to someone on holiday.
    """
    peers, _info, _cfg, _s, error = _peers_retrying(env)
    if error:
        return error

    findings = []
    for p in peers:
        pub, flags = _public(p), []
        if (pub["scope"] or "").strip() == "0.0.0.0/0":
            flags.append("full_tunnel: routes all of this user's traffic through the network")
        try:
            transferred = float(pub["total_transfer_gb"] or 0)
        except (TypeError, ValueError):
            transferred = 0.0
        if not transferred:
            # A peer issued minutes ago has zero transfer too. Saying "never
            # used" here would invite revoking somebody's brand-new access, so
            # state what is actually known and where to resolve it.
            flags.append(
                "no_transfer_recorded: cumulative transfer is zero — either never "
                "used, or issued recently and not yet connected. Check the issue "
                "date in the vault item before concluding it is stale."
            )
        if pub["latest_handshake"] == _NO_HANDSHAKE:
            flags.append("no_handshake_since_restart: weak signal on its own, see note")
        if not re.search(r"[._-]", pub["name"] or ""):
            flags.append("name_carries_no_owner: cannot tell who or which device from the name")
        if flags:
            findings.append({"peer": pub["name"], "address": pub["address"], "flags": flags})

    return _ok(
        environment=env,
        peer_count=len(peers),
        findings=findings,
        note=(
            "Findings are advisory and none of them alone justifies revocation. "
            "latest_handshake resets when the interface restarts, so it is never "
            "proof a peer went unused. Zero cumulative transfer is the stronger "
            "signal but cannot distinguish an abandoned peer from a freshly "
            "issued one. The peer that should worry you is the one that is "
            "over-scoped AND has no identifiable owner — confirm ownership "
            "before revoking anything."
        ),
    )


if __name__ == "__main__":
    mcp.run(transport="stdio")
