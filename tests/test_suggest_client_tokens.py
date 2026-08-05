"""Tests for bin/suggest-client-tokens.py (opskit #133).

Every publication guard resolves its token list from `.client-tokens` plus the
`environments/*` directory names. That list was hand-maintained and nothing verified
it, so an unlisted client was simply unprotected and nothing said so — which is how a
client-named branch reached the public remote.

Two properties matter more than the extraction itself:

- **It reports, never writes.** A token list that grew itself would start blocking
  innocuous words, and the response to a guard that cries wolf is
  `ALLOW_CLIENT_TOKENS=1` — which disables every guard at once, not just the noisy one.
- **Signal over recall.** The first version scanned whole hostnames and suggested
  `alpine`, `ansible`, `apache`, `brother`, `bulb` — device names, not clients. A
  report full of noise gets ignored, so a missed client is preferable to a list nobody
  reads. Hence: domain labels only, stopwords, and a minimum length.
"""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUGGEST = ROOT / "bin" / "suggest-client-tokens.py"


def _make(tmp_path: Path, envs: dict, tokens: str | None = None) -> Path:
    """envs: {name: {"env_yml": str, "hostnames": [str]}}"""
    root = tmp_path / "repo"
    for name, spec in envs.items():
        d = root / "environments" / name / "datasets" / "devices"
        d.mkdir(parents=True, exist_ok=True)
        (root / "environments" / name / "env.yml").write_text(spec.get("env_yml", f"name: {name}\n"))
        for i, host in enumerate(spec.get("hostnames", [])):
            (d / f"dev{i}.md").write_text(f"---\nname: dev{i}\nhostname: {host}\n---\n")
    if tokens is not None:
        (root / ".client-tokens").write_text(tokens)
    root.mkdir(parents=True, exist_ok=True)
    return root


def _run(root: Path, *args: str):
    env = {k: v for k, v in os.environ.items() if k != "CLIENT_TOKENS"}
    env["OPSKIT_ROOT"] = str(root)
    return subprocess.run([sys.executable, str(SUGGEST), "--repo-root", str(root), *args],
                          capture_output=True, text=True, env=env, timeout=60)


ENV_YML = """name: site1
display_name: Acme Widgets
ticket:
  prefix: ACME
domains:
  primary: acmewidgets.example
vault:
  collection: acmewidgets
"""


# ── extraction ────────────────────────────────────────────────────────────────

def test_display_name_domain_and_collection_are_all_sources(tmp_path):
    root = _make(tmp_path, {"site1": {"env_yml": ENV_YML}}, tokens="")

    out = _run(root).stdout

    assert "acmewidgets" in out
    assert "acme" in out
    assert "widgets" in out


def test_the_source_of_each_candidate_is_named(tmp_path):
    """An operator deciding whether a word is a client needs to know where it came
    from — 'trust me' is not actionable."""
    root = _make(tmp_path, {"site1": {"env_yml": ENV_YML}}, tokens="")

    out = _run(root).stdout

    assert "display_name" in out
    assert "vault.collection" in out


def test_already_covered_tokens_are_not_suggested(tmp_path):
    root = _make(tmp_path, {"site1": {"env_yml": ENV_YML}},
                 tokens="acmewidgets\nacme\nwidgets\n")

    out = _run(root).stdout

    assert "No unguarded candidates" in out


def test_the_environment_directory_name_counts_as_covered(tmp_path):
    """The guards match on it already, so suggesting it would be a false positive."""
    root = _make(tmp_path, {"acme": {"env_yml": "name: acme\ndisplay_name: acme\n"}},
                 tokens="")

    out = _run(root).stdout

    assert "No unguarded candidates" in out


# ── signal over recall ────────────────────────────────────────────────────────

def test_only_the_domain_part_of_a_hostname_is_used(tmp_path):
    """Regression: scanning whole hostnames suggested alpine/ansible/apache/bulb —
    device names, not clients. A noisy report gets ignored entirely."""
    root = _make(tmp_path, {"site1": {
        "env_yml": "name: site1\n",
        "hostnames": ["alpine-cacher.acmewidgets.example", "brother-printer.acmewidgets.example"],
    }}, tokens="")

    out = _run(root).stdout

    assert "acmewidgets" in out
    for device_word in ("alpine", "cacher", "brother", "printer"):
        assert device_word not in out, f"{device_word} is a device name, not a client"


def test_a_bare_hostname_with_no_domain_contributes_nothing(tmp_path):
    root = _make(tmp_path, {"site1": {"env_yml": "name: site1\n",
                                      "hostnames": ["alpha-ups", "bulb-01"]}}, tokens="")

    out = _run(root).stdout

    assert "alpha" not in out
    assert "bulb" not in out


def test_public_suffixes_and_infra_words_are_not_suggested(tmp_path):
    root = _make(tmp_path, {"site1": {
        "env_yml": "name: site1\n",
        "hostnames": ["host.dhcp.acmewidgets.example", "mail.acmewidgets.example"],
    }}, tokens="")

    out = _run(root).stdout

    assert "acmewidgets" in out
    for noise in ("dhcp", "mail", "example"):
        assert f"✗ {noise}" not in out


def test_short_candidates_are_flagged_not_suggested(tmp_path):
    """A short token matches ordinary prose, and the reflex response is
    ALLOW_CLIENT_TOKENS=1, which switches off every guard at once."""
    root = _make(tmp_path, {"site1": {"env_yml": "name: site1\ndisplay_name: Ltd\n"}},
                 tokens="")

    out = _run(root).stdout

    assert "Too short or generic" in out
    assert "ltd" in out


def test_spelling_variants_are_suggested(tmp_path):
    """Word-boundary matching means each spelling needs its own entry: a client
    listed only by its short form is unguarded for its long form."""
    root = _make(tmp_path, {"site1": {"env_yml": "name: site1\ndisplay_name: Widgets\n"}},
                 tokens="")

    out = _run(root).stdout

    assert "suggested entries:" in out
    assert "widget" in out and "widgets" in out


# ── it must not act on its own ────────────────────────────────────────────────

def test_it_never_writes_the_token_file(tmp_path):
    root = _make(tmp_path, {"site1": {"env_yml": ENV_YML}}, tokens="# nothing\n")
    before = (root / ".client-tokens").read_text()

    _run(root)

    assert (root / ".client-tokens").read_text() == before


def test_it_warns_that_its_own_output_is_sensitive(tmp_path):
    """It prints a list of client identifiers by construction."""
    root = _make(tmp_path, {"site1": {"env_yml": ENV_YML}}, tokens="")

    out = _run(root).stdout

    assert "do not paste" in out.lower()


def test_it_exits_zero_even_with_findings(tmp_path):
    """A report, not a gate — it must be safe in any preflight."""
    root = _make(tmp_path, {"site1": {"env_yml": ENV_YML}}, tokens="")

    assert _run(root).returncode == 0


def test_no_environment_layers_is_not_an_error(tmp_path):
    root = tmp_path / "repo"
    (root / "environments").mkdir(parents=True)

    result = _run(root)

    assert result.returncode == 0
    assert "No environment layers" in result.stdout


def test_the_example_layer_is_ignored(tmp_path):
    root = _make(tmp_path, {"example": {"env_yml": "name: example\ndisplay_name: Placeholder Inc\n"}},
                 tokens="")

    out = _run(root).stdout

    assert "placeholder" not in out.lower()
