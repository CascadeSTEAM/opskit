"""Tests for mcp/wireguard-mcp-server.py — VPN peer lifecycle (opskit issue #90).

Everything here is offline. `requests.Session` is replaced with a fake whose
routes are declared per test, so no dashboard is ever contacted, and the module
is loaded fresh per test via importlib because the file lives at
mcp/wireguard-mcp-server.py rather than an importable package name (mirrors
tests/test_erpnext_mcp_server.py).

WIREGUARD_TENANTS_FILE is always pointed at a throwaway fixture so the suite
never reads a developer's real gitignored tenants file (opskit #76).

Coverage focus — the invariants that make this tool safe rather than merely
functional:
  - a client config NEVER appears in a tool result; delivery is the only egress
  - scope is explicit or mirrored, never silently defaulted to a full tunnel
  - address allocation skips the server and every address already in use
  - revoke refuses without confirmation, and verifies the peer is actually gone
    rather than trusting the delete response
  - a missing TOTP seed is reported as such, not as a password problem — the
    exact misdiagnosis that motivated #90
"""

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "mcp" / "wireguard-mcp-server.py"

ENV = "client1"


def load_module():
    spec = importlib.util.spec_from_file_location("wireguard_mcp_under_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# A base32 secret with correct padding behaviour ("JBSWY3DPEHPK3PXP" is the
# canonical RFC 4648 test vector for "Hello!\xde\xad\xbe\xef").
SEED = "JBSWY3DPEHPK3PXP"


def _peer(name, addr, scope="198.51.100.0/24", dns="203.0.113.2", transfer=1.5, hs="0:01:00"):
    return {
        "name": name, "allowed_ip": addr, "endpoint_allowed_ip": scope, "DNS": dns,
        "mtu": 1420, "keepalive": 21, "latest_handshake": hs, "status": "running",
        "id": f"pubkey-{name}", "total_data": transfer,
        "private_key": f"PRIVATE-KEY-OF-{name}",  # must never surface in output
    }


class FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


class FakeSession:
    """Records calls and replies from a declared route table."""

    def __init__(self, peers, *, auth_ok=True, add_ok=True, delete_ok=True,
                 peers_after_delete=None, config_file="[Interface]\nPrivateKey = SECRET\n"):
        self.peers = list(peers)
        self.auth_ok = auth_ok
        self.add_ok = add_ok
        self.delete_ok = delete_ok
        self.peers_after_delete = peers_after_delete
        self.config_file = config_file
        self.posts = []
        self.gets = []

    def post(self, url, json=None, timeout=None):
        self.posts.append((url, json))
        if "/api/authenticate" in url:
            return FakeResponse({"status": self.auth_ok,
                                 "message": False if self.auth_ok else "incorrect"})
        if "/api/addPeers/" in url:
            if not self.add_ok:
                return FakeResponse({"status": False, "message": "refused"})
            self.peers.append(_peer(json["name"], json["allowed_ips"][0],
                                    scope=json["endpoint_allowed_ip"], dns=json["DNS"]))
            return FakeResponse({"status": True, "data": []})
        if "/api/deletePeers/" in url:
            if not self.delete_ok:
                return FakeResponse({"status": False, "message": "refused"})
            if self.peers_after_delete is None:
                keys = set(json["peers"])
                self.peers = [p for p in self.peers if p["id"] not in keys]
            else:
                self.peers = list(self.peers_after_delete)
            return FakeResponse({"status": True})
        raise AssertionError(f"unexpected POST {url}")

    def get(self, url, params=None, timeout=None):
        self.gets.append((url, params))
        if "/api/getWireguardConfigurationInfo" in url:
            return FakeResponse({"status": True, "data": {
                "configurationPeers": self.peers,
                "configurationInfo": {"Address": "192.0.2.1/24"},
            }})
        if "/api/downloadPeer/" in url:
            return FakeResponse({"status": True,
                                 "data": {"fileName": "peer", "file": self.config_file}})
        raise AssertionError(f"unexpected GET {url}")


@pytest.fixture
def mod(tmp_path, monkeypatch):
    fixture = tmp_path / "tenants-wireguard.local.json"
    fixture.write_text(json.dumps({ENV: {
        "url": "http://192.0.2.9:10086",
        "configuration": "wg0",
        "username": "admin",
        "env_pass": "WG_TEST_PASS",
        "env_totp": "WG_TEST_TOTP",
        "reference_peer": "someone_laptop",
        "dns": "203.0.113.2",
    }}))
    monkeypatch.setenv("WIREGUARD_TENANTS_FILE", str(fixture))
    monkeypatch.setenv("WG_TEST_PASS", "pw")
    monkeypatch.setenv("WG_TEST_TOTP", SEED)
    return load_module()


@pytest.fixture
def wired(mod, monkeypatch):
    """Returns a helper that installs a FakeSession and stub key generation."""
    def _install(session):
        monkeypatch.setattr(mod.requests, "Session", lambda: session)
        monkeypatch.setattr(mod, "_genkeys", lambda: ("PRIV-NEW", "PUB-NEW"))
        return session
    return _install


# ── TOTP ──────────────────────────────────────────────────────────────────────
def test_totp_generates_six_digits(mod):
    code = mod._totp_now(SEED)
    assert len(code) == 6 and code.isdigit()


def test_totp_accepts_otpauth_uri(mod):
    uri = f"otpauth://totp/Example:admin?secret={SEED}&issuer=Example"
    assert mod._totp_now(uri) == mod._totp_now(SEED)


def test_totp_accepts_unpadded_lowercase_secret(mod):
    """Vault items store seeds inconsistently; padding and case must not matter."""
    assert mod._totp_now("jbswy3dpehpk3pxp") == mod._totp_now(SEED)


def test_missing_totp_seed_is_reported_as_such(mod, monkeypatch):
    """The #90 misdiagnosis: a 2FA failure must not read as a password problem."""
    monkeypatch.delenv("WG_TEST_TOTP")
    out = json.loads(mod.wireguard_list_peers(env=ENV))
    assert out["ok"] is False
    assert "TOTP" in out["error"]
    assert "totp" in json.dumps(out["hint"]).lower()


def test_missing_password_is_reported_distinctly(mod, monkeypatch):
    monkeypatch.delenv("WG_TEST_PASS")
    out = json.loads(mod.wireguard_list_peers(env=ENV))
    assert out["ok"] is False and "WG_TEST_PASS" in out["error"]


def test_unknown_environment_lists_available(mod):
    out = json.loads(mod.wireguard_list_peers(env="nope"))
    assert out["ok"] is False and ENV in out["available"]


def test_auth_rejection_mentions_clock_skew(mod, wired):
    """A fresh code is generated per call, so the hint must not send the operator
    hunting for a rotated password first."""
    wired(FakeSession([], auth_ok=False))
    out = json.loads(mod.wireguard_list_peers(env=ENV))
    assert out["ok"] is False and "skew" in out["hint"]


# ── no secret egress ──────────────────────────────────────────────────────────
def test_list_peers_never_leaks_private_keys(mod, wired):
    wired(FakeSession([_peer("someone_laptop", "192.0.2.4/32")]))
    raw = mod.wireguard_list_peers(env=ENV)
    assert "PRIVATE-KEY-OF" not in raw and "private_key" not in raw


def test_create_peer_withholds_the_config(mod, wired):
    wired(FakeSession([_peer("someone_laptop", "192.0.2.4/32")]))
    raw = mod.wireguard_create_peer(env=ENV, name="dana_laptop")
    out = json.loads(raw)
    assert out["ok"] is True
    assert "PRIV-NEW" not in raw, "the generated private key must not be returned"
    assert "[Interface]" not in raw
    assert "config_withheld" in out


def test_there_is_no_get_config_tool(mod):
    """Egress is deliberately limited to wireguard_deliver_config."""
    exported = [n for n in dir(mod) if n.startswith("wireguard_")]
    assert "wireguard_get_config" not in exported
    assert set(exported) == {
        "wireguard_list_peers", "wireguard_create_peer",
        "wireguard_deliver_config", "wireguard_revoke_peer", "wireguard_audit",
    }


# ── address allocation ────────────────────────────────────────────────────────
def test_allocates_lowest_free_address_skipping_server(mod):
    peers = [_peer("a", "192.0.2.2/32"), _peer("b", "192.0.2.3/32")]
    assert mod._next_address(peers, "192.0.2") == "192.0.2.4/32"


def test_allocation_reuses_a_gap(mod):
    peers = [_peer("a", "192.0.2.2/32"), _peer("c", "192.0.2.4/32")]
    assert mod._next_address(peers, "192.0.2") == "192.0.2.3/32"


def test_allocation_ignores_addresses_from_other_subnets(mod):
    peers = [_peer("a", "198.51.100.9/32")]
    assert mod._next_address(peers, "192.0.2") == "192.0.2.2/32"


def test_allocation_raises_when_exhausted(mod):
    peers = [_peer(f"p{i}", f"192.0.2.{i}/32") for i in range(2, 255)]
    with pytest.raises(RuntimeError, match="no free address"):
        mod._next_address(peers, "192.0.2")


def test_create_uses_the_next_free_address(mod, wired):
    s = wired(FakeSession([_peer("someone_laptop", "192.0.2.4/32")]))
    json.loads(mod.wireguard_create_peer(env=ENV, name="dana_laptop"))
    add = next(body for url, body in s.posts if "/api/addPeers/" in url)
    assert add["allowed_ips"] == ["192.0.2.2/32"]


# ── scope: mirrored, explicit, never silently full-tunnel ─────────────────────
def test_scope_mirrors_the_reference_peer(mod, wired):
    s = wired(FakeSession([_peer("someone_laptop", "192.0.2.4/32", scope="198.51.100.0/24")]))
    out = json.loads(mod.wireguard_create_peer(env=ENV, name="dana_laptop"))
    add = next(body for url, body in s.posts if "/api/addPeers/" in url)
    assert add["endpoint_allowed_ip"] == "198.51.100.0/24"
    assert out["scope_source"] == "mirrored from someone_laptop"
    assert out["full_tunnel"] is False


def test_explicit_scope_overrides_the_mirror(mod, wired):
    s = wired(FakeSession([_peer("someone_laptop", "192.0.2.4/32")]))
    out = json.loads(mod.wireguard_create_peer(
        env=ENV, name="dana_laptop", allowed_ips="0.0.0.0/0"))
    add = next(body for url, body in s.posts if "/api/addPeers/" in url)
    assert add["endpoint_allowed_ip"] == "0.0.0.0/0"
    assert out["full_tunnel"] is True, "a full tunnel must be reported as such"


def test_missing_reference_peer_refuses_rather_than_guessing(mod, wired):
    """No scope and no reference peer must never fall back to a full tunnel."""
    wired(FakeSession([_peer("unrelated", "192.0.2.9/32")]))
    out = json.loads(mod.wireguard_create_peer(env=ENV, name="dana_laptop"))
    assert out["ok"] is False
    assert "reference peer" in out["error"]
    assert "unrelated" in out["available_peers"]


def test_duplicate_name_refused(mod, wired):
    wired(FakeSession([_peer("dana_laptop", "192.0.2.2/32")]))
    out = json.loads(mod.wireguard_create_peer(env=ENV, name="dana_laptop"))
    assert out["ok"] is False and "already exists" in out["error"]


@pytest.mark.parametrize("bad", ["", "a", "has space", "semi;colon", "x" * 65])
def test_invalid_names_refused(mod, wired, bad):
    wired(FakeSession([_peer("someone_laptop", "192.0.2.4/32")]))
    out = json.loads(mod.wireguard_create_peer(env=ENV, name=bad))
    assert out["ok"] is False and "invalid peer name" in out["error"]


def test_create_verifies_against_the_server(mod, wired, monkeypatch):
    """A success response is not proof; the peer must show up on re-read."""
    s = FakeSession([_peer("someone_laptop", "192.0.2.4/32")])
    monkeypatch.setattr(mod.requests, "Session", lambda: s)
    monkeypatch.setattr(mod, "_genkeys", lambda: ("PRIV-NEW", "PUB-NEW"))
    # dashboard claims success but does not actually add the peer
    s.post_original = s.post

    def lying_post(url, json=None, timeout=None):
        if "/api/addPeers/" in url:
            s.posts.append((url, json))
            return FakeResponse({"status": True, "data": []})
        return s.post_original(url, json=json, timeout=timeout)

    s.post = lying_post
    out = json.loads(mod.wireguard_create_peer(env=ENV, name="dana_laptop"))
    assert out["ok"] is False and "not present" in out["error"]


# ── revoke ────────────────────────────────────────────────────────────────────
def test_revoke_refuses_without_confirmation(mod, wired):
    s = wired(FakeSession([_peer("dana_laptop", "192.0.2.2/32")]))
    out = json.loads(mod.wireguard_revoke_peer(env=ENV, name="dana_laptop"))
    assert out["ok"] is False
    assert "confirm=True" in out["error"]
    assert "not restorable" in out["consequence"]
    assert not any("/api/deletePeers/" in url for url, _ in s.posts)


def test_revoke_deletes_and_confirms(mod, wired):
    s = wired(FakeSession([_peer("dana_laptop", "192.0.2.2/32"),
                           _peer("someone_laptop", "192.0.2.4/32")]))
    out = json.loads(mod.wireguard_revoke_peer(env=ENV, name="dana_laptop", confirm=True))
    assert out["ok"] is True
    assert out["revoked"] == "dana_laptop"
    assert out["address_freed"] == "192.0.2.2/32"
    assert out["peers_remaining"] == 1
    assert any("/api/deletePeers/" in url for url, _ in s.posts)


def test_revoke_reports_failure_when_peer_survives(mod, wired):
    """The dangerous case: a success response while access remains live."""
    survivor = _peer("dana_laptop", "192.0.2.2/32")
    wired(FakeSession([survivor], peers_after_delete=[survivor]))
    out = json.loads(mod.wireguard_revoke_peer(env=ENV, name="dana_laptop", confirm=True))
    assert out["ok"] is False
    assert "STILL PRESENT" in out["error"]


def test_revoke_unknown_peer(mod, wired):
    wired(FakeSession([_peer("someone_laptop", "192.0.2.4/32")]))
    out = json.loads(mod.wireguard_revoke_peer(env=ENV, name="ghost", confirm=True))
    assert out["ok"] is False and "no peer named" in out["error"]


# ── delivery ──────────────────────────────────────────────────────────────────
def test_delivery_requires_bw_session(mod, wired, monkeypatch):
    monkeypatch.delenv("BW_SESSION", raising=False)
    wired(FakeSession([_peer("dana_laptop", "192.0.2.2/32")]))
    out = json.loads(mod.wireguard_deliver_config(env=ENV, name="dana_laptop"))
    assert out["ok"] is False and "BW_SESSION" in out["error"]


def test_delivery_returns_url_not_config(mod, wired, monkeypatch):
    monkeypatch.setenv("BW_SESSION", "x")
    wired(FakeSession([_peer("dana_laptop", "192.0.2.2/32")]))

    captured = {}

    class Done:
        returncode = 0
        stdout = "https://send.example.test/#/abc\n"
        stderr = ""

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        return Done()

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    raw = mod.wireguard_deliver_config(env=ENV, name="dana_laptop")
    out = json.loads(raw)
    assert out["ok"] is True
    assert out["access_url"] == "https://send.example.test/#/abc"
    assert "[Interface]" not in raw and "SECRET" not in raw
    assert "--maxAccessCount" in captured["cmd"] and "1" in captured["cmd"]
    assert "--deleteInDays" in captured["cmd"]


def test_delivery_passes_password_when_given(mod, wired, monkeypatch):
    monkeypatch.setenv("BW_SESSION", "x")
    wired(FakeSession([_peer("dana_laptop", "192.0.2.2/32")]))
    captured = {}

    class Done:
        returncode = 0
        stdout = "https://send.example.test/#/abc"
        stderr = ""

    monkeypatch.setattr(mod.subprocess, "run",
                        lambda cmd, **kw: (captured.update(cmd=cmd), Done())[1])
    out = json.loads(mod.wireguard_deliver_config(
        env=ENV, name="dana_laptop", send_password="s3cret"))
    assert out["password_protected"] is True
    assert "--password" in captured["cmd"]


def test_delivery_removes_the_temp_file(mod, wired, monkeypatch):
    """The config must not be left on disk after delivery."""
    monkeypatch.setenv("BW_SESSION", "x")
    wired(FakeSession([_peer("dana_laptop", "192.0.2.2/32")]))
    seen = {}

    class Done:
        returncode = 0
        stdout = "https://send.example.test/#/abc"
        stderr = ""

    def fake_run(cmd, **kw):
        path = cmd[cmd.index("--file") + 1]
        seen["path"] = path
        seen["existed_during"] = Path(path).exists()
        return Done()

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    json.loads(mod.wireguard_deliver_config(env=ENV, name="dana_laptop"))
    assert seen["existed_during"] is True
    assert not Path(seen["path"]).exists(), "temp config file was left behind"


def test_delivery_parses_the_json_object_form(mod, wired, monkeypatch):
    """`bw send --file` prints a JSON object, not a bare URL. Assuming the bare
    form rejected a Send that had actually been created, leaving an orphaned
    copy of the config in the vault — found by running it live."""
    monkeypatch.setenv("BW_SESSION", "x")
    wired(FakeSession([_peer("dana_laptop", "192.0.2.2/32")]))

    class Done:
        returncode = 0
        stdout = json.dumps({
            "object": "send", "id": "send-id-123",
            "accessId": "abc", "accessUrl": "https://vault.example.test/#/send/abc/key",
        })
        stderr = ""

    monkeypatch.setattr(mod.subprocess, "run", lambda cmd, **kw: Done())
    out = json.loads(mod.wireguard_deliver_config(env=ENV, name="dana_laptop"))
    assert out["ok"] is True
    assert out["access_url"] == "https://vault.example.test/#/send/abc/key"
    assert out["send_id"] == "send-id-123", "the id is needed to delete an orphan"


def test_delivery_still_accepts_the_bare_url_form(mod, wired, monkeypatch):
    """Text Sends print a bare URL; both forms must work."""
    monkeypatch.setenv("BW_SESSION", "x")
    wired(FakeSession([_peer("dana_laptop", "192.0.2.2/32")]))

    class Done:
        returncode = 0
        stdout = "https://vault.example.test/#/send/xyz/key\n"
        stderr = ""

    monkeypatch.setattr(mod.subprocess, "run", lambda cmd, **kw: Done())
    out = json.loads(mod.wireguard_deliver_config(env=ENV, name="dana_laptop"))
    assert out["ok"] is True and out["access_url"].endswith("/xyz/key")


def test_delivery_unparseable_output_warns_about_an_orphan(mod, wired, monkeypatch):
    """If the URL cannot be found, a Send may exist anyway — say so, because the
    orphan holds a copy of the private key."""
    monkeypatch.setenv("BW_SESSION", "x")
    wired(FakeSession([_peer("dana_laptop", "192.0.2.2/32")]))

    class Done:
        returncode = 0
        stdout = "something unexpected"
        stderr = ""

    monkeypatch.setattr(mod.subprocess, "run", lambda cmd, **kw: Done())
    out = json.loads(mod.wireguard_deliver_config(env=ENV, name="dana_laptop"))
    assert out["ok"] is False
    assert "may still have been created" in out["error"]
    assert "bw send delete" in out["cleanup_hint"]


def test_delivery_rejects_zero_access_count(mod, wired, monkeypatch):
    monkeypatch.setenv("BW_SESSION", "x")
    wired(FakeSession([_peer("dana_laptop", "192.0.2.2/32")]))
    out = json.loads(mod.wireguard_deliver_config(
        env=ENV, name="dana_laptop", max_access_count=0))
    assert out["ok"] is False


# ── session caching ───────────────────────────────────────────────────────────
def test_session_is_cached_across_calls(mod, wired):
    """The dashboard is reached over plain HTTP inside the tunnel, so each login
    puts the password on the wire again. One login per environment, not one per
    call."""
    s = wired(FakeSession([_peer("someone_laptop", "192.0.2.4/32")]))
    mod.wireguard_list_peers(env=ENV)
    mod.wireguard_list_peers(env=ENV)
    mod.wireguard_audit(env=ENV)
    logins = [url for url, _ in s.posts if "/api/authenticate" in url]
    assert len(logins) == 1, f"expected a single login, got {len(logins)}"


def test_stale_cookie_triggers_one_reauth_then_succeeds(mod, wired):
    """A cached cookie can expire. That must self-heal rather than surfacing as
    a confusing read error."""
    s = wired(FakeSession([_peer("someone_laptop", "192.0.2.4/32")]))
    mod.wireguard_list_peers(env=ENV)  # populates the cache

    calls = {"n": 0}
    real_get = s.get

    def flaky_get(url, params=None, timeout=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("HTTP 401")
        return real_get(url, params=params, timeout=timeout)

    s.get = flaky_get
    out = json.loads(mod.wireguard_list_peers(env=ENV))
    assert out["ok"] is True, "a stale cookie should be retried, not reported"
    logins = [url for url, _ in s.posts if "/api/authenticate" in url]
    assert len(logins) == 2, "exactly one re-authentication"


def test_persistent_read_failure_is_reported_after_one_retry(mod, wired):
    s = wired(FakeSession([_peer("someone_laptop", "192.0.2.4/32")]))

    def always_fail(url, params=None, timeout=None):
        raise RuntimeError("connection refused")

    s.get = always_fail
    out = json.loads(mod.wireguard_list_peers(env=ENV))
    assert out["ok"] is False and "re-authenticating" in out["error"]


# ── audit ─────────────────────────────────────────────────────────────────────
def test_audit_flags_full_tunnel_and_unused(mod, wired):
    wired(FakeSession([
        _peer("someone_laptop", "192.0.2.4/32", scope="198.51.100.0/24", transfer=5),
        _peer("orphan", "192.0.2.2/32", scope="0.0.0.0/0", transfer=0,
              hs="No Handshake"),
    ]))
    out = json.loads(mod.wireguard_audit(env=ENV))
    assert out["ok"] is True
    flagged = {f["peer"]: f["flags"] for f in out["findings"]}
    assert "orphan" in flagged
    joined = " ".join(flagged["orphan"])
    assert "full_tunnel" in joined
    assert "no_transfer_recorded" in joined
    assert "name_carries_no_owner" in joined
    assert "someone_laptop" not in flagged


def test_audit_zero_transfer_does_not_claim_never_used(mod, wired):
    """A peer issued minutes ago also has zero transfer. Calling that 'never
    used' would invite revoking somebody's brand-new access."""
    wired(FakeSession([_peer("brand_new", "192.0.2.5/32", transfer=0)]))
    out = json.loads(mod.wireguard_audit(env=ENV))
    flags = " ".join(out["findings"][0]["flags"])
    assert "issued recently" in flags
    assert "vault item" in flags, "must point at where the issue date lives"


def test_audit_handles_non_numeric_transfer(mod, wired):
    """The dashboard's transfer field type is not guaranteed; a string must not
    take the whole audit down."""
    peer = _peer("odd", "192.0.2.6/32")
    peer["total_data"] = "not-a-number"
    wired(FakeSession([peer]))
    out = json.loads(mod.wireguard_audit(env=ENV))
    assert out["ok"] is True


def test_audit_note_warns_handshake_is_weak_evidence(mod, wired):
    """Handshake resets on interface restart; the report must say so, because
    acting on it alone would revoke a live user's access."""
    wired(FakeSession([_peer("p", "192.0.2.2/32")]))
    out = json.loads(mod.wireguard_audit(env=ENV))
    assert "restart" in out["note"] and "never" in out["note"]
