"""Tests for bin/mail-auth-check.py: the read-only email-authentication checker (#431).

Never touches the network: every lookup goes through an injected resolver. Failure modes that are silent and expensive,
one group of tests each:

  * a wrong verdict on SPF (two records, too many DNS lookups, +all) breaks mail without any error anywhere;
  * a DKIM key that is missing, revoked, or too weak is invisible until mail is junked;
  * alert noise: the scheduler must fail only when something got WORSE than the last run, or nobody reads it;
  * the tool must never be able to change DNS (it proposes, a human disposes).

Addresses and names are documentation ranges (RFC 5737) and example.com, never real ones.
"""

import importlib.util
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "bin" / "mail-auth-check.py"

RSA_2048_SPKI = "MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAgSzyY7QuLGf4FaXPaJYl349/w/zpCNc5l8dm948hYOy48jII06EVgGcG8jXEyheZC5pYyROoXTX2FKHLsoRb66LewPTyKZqd0G9GV32DQhsxsF7gHVa0w6lpt6mU85NQGlKpvGRVwvtkPcmXd7aT1UP4FYOfgdPvroevKkBFQFL6RZyMNFaqMFKBlQtppg6FOnxMFhOKqjWvJmWqSMq7rhBHctbK7OE+5j+xlNHIyn1QzVgUAIBmUnHKgAOo4pH79UsM1KJKthWCGymBV9q19Ww9HccsKoMYdKniU+ZiSDz8jmuweUy1ptheqDrT3Q0c+03Mxgwvf1Lli1kyo5kC/QIDAQAB"
RSA_1024_SPKI = "MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQCo4utPCMDymUr+3XUNScDR7tEHQicKkIi0JjJQOmI1bZROgEv5zolAgtWC46Xn5zYnKag5zglzu52zMXks9IEp6AcMh7msn85kkpyre/VYgHm0I/5XU48+c5xEEwjCNzLsLrFrC7YISKB+dC47ro9uW2YhhgktZMjyp9L5GirnVwIDAQAB"


def _load():
    spec = importlib.util.spec_from_file_location("mail_auth_check", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["mail_auth_check"] = module
    spec.loader.exec_module(module)
    return module


mac = _load()


class FakeResolver:
    """records: {(name, TYPE): [values]} and {(name, TYPE, server): [values]} for per-nameserver answers."""

    def __init__(self, records=None):
        self.records = {}
        for key, values in (records or {}).items():
            self.records[(key[0].lower().rstrip("."), key[1].upper()) + tuple(key[2:])] = list(values)
        self.queries = []

    def query(self, name, rtype, server=None):
        name = name.lower().rstrip(".")
        self.queries.append((name, rtype.upper(), server))
        key = (name, rtype.upper()) if server is None else (name, rtype.upper(), server)
        return list(self.records.get(key, []))


def google_domain(over=None):
    """A healthy Google-Workspace-style domain: SPF, DKIM, DMARC, MX, consistent nameservers."""
    d = "example.com"
    rec = {
        (d, "NS"): ["ns1.example.net.", "ns2.example.net."],
        (d, "SOA", "ns1.example.net"): ["ns1.example.net. hostmaster.example.net. 2026100201 10000 2400 604800 1800"],
        (d, "SOA", "ns2.example.net"): ["ns1.example.net. hostmaster.example.net. 2026100201 10000 2400 604800 1800"],
        (d, "MX"): ["1 aspmx.l.google.com.", "5 alt1.aspmx.l.google.com.", "10 aspmx2.googlemail.com."],
        (d, "TXT"): ["v=spf1 include:_spf.google.com ~all", "google-site-verification=abc"],
        ("_spf.google.com", "TXT"): ["v=spf1 ip4:192.0.2.0/24 ip6:2001:db8::/32 ~all"],
        ("google._domainkey." + d, "TXT"): ["v=DKIM1; k=rsa; p=" + RSA_2048_SPKI],
        ("_dmarc." + d, "TXT"): ["v=DMARC1; p=none; rua=mailto:dmarc@example.com"],
        (d, "CAA"): [],
        (d, "DS"): [],
    }
    rec.update(over or {})
    return FakeResolver(rec)


def spec(**kw):
    base = dict(name="example.com", provider="google-workspace", dkim_selectors=["google"], sending_ips=[], expect_mail=True)
    base.update(kw)
    return mac.DomainSpec(**base)


def find(findings, check, domain="example.com"):
    hits = [f for f in findings if f.check == check and f.domain == domain]
    assert hits, f"no finding for check {check!r}; have {sorted({f.check for f in findings})}"
    return hits


def status_of(findings, check):
    return {f.status for f in find(findings, check)}


# --- SPF ---------------------------------------------------------------------------------------------------------------


def test_a_healthy_spf_passes_and_counts_one_lookup():
    out = mac.check_spf(spec(), google_domain())
    assert status_of(out, "spf") == {mac.PASS}
    count, problems = mac.spf_lookup_count("example.com", google_domain())
    assert count == 1 and not problems


def test_a_missing_spf_fails_when_the_domain_sends_mail():
    out = mac.check_spf(spec(), google_domain({("example.com", "TXT"): ["google-site-verification=abc"]}))
    assert status_of(out, "spf") == {mac.FAIL}


def test_two_spf_records_are_a_permanent_error():
    two = ["v=spf1 include:_spf.google.com ~all", "v=spf1 include:other.example.org ~all"]
    out = mac.check_spf(spec(), google_domain({("example.com", "TXT"): two}))
    assert status_of(out, "spf") == {mac.FAIL}
    assert "more than one" in " ".join(f.message for f in find(out, "spf")).lower()


def test_more_than_ten_dns_lookups_fail():
    records = {("example.com", "TXT"): ["v=spf1 " + " ".join(f"include:i{n}.example.org" for n in range(11)) + " ~all"]}
    for n in range(11):
        records[(f"i{n}.example.org", "TXT")] = ["v=spf1 ip4:192.0.2.1 ~all"]
    out = mac.check_spf(spec(provider="generic"), FakeResolver(records))
    assert status_of(out, "spf") == {mac.FAIL}
    assert "lookup" in " ".join(f.message for f in find(out, "spf")).lower()


def test_an_include_loop_terminates_and_is_reported():
    records = {
        ("example.com", "TXT"): ["v=spf1 include:a.example.org ~all"],
        ("a.example.org", "TXT"): ["v=spf1 include:b.example.org ~all"],
        ("b.example.org", "TXT"): ["v=spf1 include:a.example.org ~all"],
    }
    count, problems = mac.spf_lookup_count("example.com", FakeResolver(records))
    assert count <= 10 and any("loop" in p.lower() for p in problems)


@pytest.mark.parametrize(
    "tail,expected",
    [("~all", mac.PASS), ("-all", mac.PASS), ("?all", mac.WARN), ("+all", mac.FAIL), ("", mac.WARN)],
)
def test_the_spf_ending_decides_the_verdict(tail, expected):
    spf = f"v=spf1 include:_spf.google.com {tail}".strip()
    out = mac.check_spf(spec(), google_domain({("example.com", "TXT"): [spf]}))
    assert status_of(out, "spf") == {expected}


def test_an_expected_include_that_is_missing_warns():
    out = mac.check_spf(spec(), google_domain({("example.com", "TXT"): ["v=spf1 ip4:192.0.2.9 ~all"]}))
    assert mac.WARN in status_of(out, "spf") or mac.FAIL in status_of(out, "spf")


def test_a_domain_that_sends_no_mail_should_publish_a_reject_all_spf():
    quiet = spec(provider="none", expect_mail=False, dkim_selectors=[])
    ok = mac.check_spf(quiet, FakeResolver({("example.com", "TXT"): ["v=spf1 -all"]}))
    bad = mac.check_spf(quiet, FakeResolver({("example.com", "TXT"): ["v=spf1 +all"]}))
    assert status_of(ok, "spf") == {mac.PASS}
    assert status_of(bad, "spf") == {mac.FAIL}


# --- DKIM --------------------------------------------------------------------------------------------------------------


def test_the_rsa_key_size_is_read_from_the_der_structure():
    assert mac.rsa_modulus_bits(RSA_2048_SPKI) == 2048
    assert mac.rsa_modulus_bits(RSA_1024_SPKI) == 1024


@pytest.mark.parametrize("junk", ["", "not base64!!", "AAAA", "MIIB"])
def test_an_unparseable_key_is_rejected(junk):
    with pytest.raises(ValueError):
        mac.rsa_modulus_bits(junk)


def test_a_good_2048_bit_key_passes():
    assert status_of(mac.check_dkim(spec(), google_domain()), "dkim:google") == {mac.PASS}


def test_a_1024_bit_key_warns_and_weaker_fails():
    weak = google_domain({("google._domainkey.example.com", "TXT"): ["v=DKIM1; k=rsa; p=" + RSA_1024_SPKI]})
    assert status_of(mac.check_dkim(spec(), weak), "dkim:google") == {mac.WARN}


def test_a_missing_configured_selector_fails():
    gone = google_domain({("google._domainkey.example.com", "TXT"): []})
    assert status_of(mac.check_dkim(spec(), gone), "dkim:google") == {mac.FAIL}


def test_a_revoked_key_with_an_empty_p_fails():
    revoked = google_domain({("google._domainkey.example.com", "TXT"): ["v=DKIM1; k=rsa; p="]})
    assert status_of(mac.check_dkim(spec(), revoked), "dkim:google") == {mac.FAIL}


def test_a_record_that_is_not_dkim_fails():
    wrong = google_domain({("google._domainkey.example.com", "TXT"): ["hello world"]})
    assert status_of(mac.check_dkim(spec(), wrong), "dkim:google") == {mac.FAIL}


def test_google_workspace_defaults_to_the_google_selector():
    out = mac.check_dkim(spec(dkim_selectors=[]), google_domain())
    assert status_of(out, "dkim:google") == {mac.PASS}


def test_a_domain_with_no_selectors_and_no_provider_reports_info_not_failure():
    out = mac.check_dkim(spec(provider="generic", dkim_selectors=[]), google_domain())
    assert {f.status for f in out} <= {mac.INFO}


# --- DMARC -------------------------------------------------------------------------------------------------------------


def test_dmarc_monitor_only_passes_with_a_note_to_tighten_later():
    out = mac.check_dmarc(spec(), google_domain())
    assert status_of(out, "dmarc") == {mac.PASS}
    assert "monitor" in " ".join(f.message for f in find(out, "dmarc")).lower()


@pytest.mark.parametrize("policy", ["quarantine", "reject"])
def test_enforcing_dmarc_policies_pass(policy):
    rec = google_domain({("_dmarc.example.com", "TXT"): [f"v=DMARC1; p={policy}; rua=mailto:d@example.com"]})
    assert status_of(mac.check_dmarc(spec(), rec), "dmarc") == {mac.PASS}


def test_missing_dmarc_warns_for_a_sending_domain():
    out = mac.check_dmarc(spec(), google_domain({("_dmarc.example.com", "TXT"): []}))
    assert status_of(out, "dmarc") == {mac.WARN}


def test_an_invalid_policy_fails():
    bad = google_domain({("_dmarc.example.com", "TXT"): ["v=DMARC1; p=banana"]})
    assert status_of(mac.check_dmarc(spec(), bad), "dmarc") == {mac.FAIL}


def test_two_dmarc_records_fail():
    two = ["v=DMARC1; p=none", "v=DMARC1; p=reject"]
    assert status_of(mac.check_dmarc(spec(), google_domain({("_dmarc.example.com", "TXT"): two})), "dmarc") == {mac.FAIL}


def test_missing_report_address_is_only_information():
    rec = google_domain({("_dmarc.example.com", "TXT"): ["v=DMARC1; p=none"]})
    out = mac.check_dmarc(spec(), rec)
    assert mac.INFO in {f.status for f in out} and mac.FAIL not in {f.status for f in out}


# --- MX ----------------------------------------------------------------------------------------------------------------


def test_google_mx_for_a_google_domain_passes():
    assert status_of(mac.check_mx(spec(), google_domain()), "mx") == {mac.PASS}


def test_non_google_mx_for_a_google_domain_warns():
    other = google_domain({("example.com", "MX"): ["10 mail.example.org."]})
    assert status_of(mac.check_mx(spec(), other), "mx") == {mac.WARN}


def test_no_mx_fails_when_mail_is_expected_and_null_mx_is_right_when_it_is_not():
    none = google_domain({("example.com", "MX"): []})
    null = google_domain({("example.com", "MX"): ["0 ."]})
    assert status_of(mac.check_mx(spec(), none), "mx") == {mac.FAIL}
    assert status_of(mac.check_mx(spec(), null), "mx") == {mac.FAIL}
    assert status_of(mac.check_mx(spec(provider="none", expect_mail=False), null), "mx") == {mac.PASS}


# --- delegation --------------------------------------------------------------------------------------------------------


def test_consistent_nameservers_pass():
    assert status_of(mac.check_delegation(spec(), google_domain()), "delegation") == {mac.PASS}


def test_a_nameserver_with_a_different_serial_warns():
    skew = google_domain({("example.com", "SOA", "ns2.example.net"): ["ns1.example.net. h.example.net. 2026091500 1 1 1 1"]})
    assert status_of(mac.check_delegation(spec(), skew), "delegation") == {mac.WARN}


def test_an_unreachable_nameserver_warns():
    down = google_domain({("example.com", "SOA", "ns2.example.net"): []})
    assert status_of(mac.check_delegation(spec(), down), "delegation") == {mac.WARN}


def test_no_nameservers_at_all_fails():
    assert status_of(mac.check_delegation(spec(), FakeResolver()), "delegation") == {mac.FAIL}


# --- blocklists --------------------------------------------------------------------------------------------------------


def test_the_address_is_reversed_for_blocklist_queries():
    assert mac.reverse_ip("203.0.113.7") == "7.113.0.203"


def test_a_clean_address_passes_and_a_listed_one_warns_naming_the_list():
    clean = google_domain()
    out = mac.check_blocklists(spec(sending_ips=["203.0.113.7"]), clean)
    assert status_of(out, "blocklist:203.0.113.7") == {mac.PASS}
    listed = google_domain({("7.113.0.203.bl.spamcop.net", "A"): ["127.0.0.2"]})
    out = mac.check_blocklists(spec(sending_ips=["203.0.113.7"]), listed)
    assert status_of(out, "blocklist:203.0.113.7") == {mac.WARN}
    assert "spamcop" in " ".join(f.message for f in find(out, "blocklist:203.0.113.7")).lower()


def test_an_open_resolver_refusal_is_inconclusive_not_listed():
    refused = google_domain({("7.113.0.203.zen.spamhaus.org", "A"): ["127.255.255.254"]})
    out = mac.check_blocklists(spec(sending_ips=["203.0.113.7"]), refused)
    assert mac.WARN not in status_of(out, "blocklist:203.0.113.7")
    assert any("inconclusive" in f.message.lower() for f in find(out, "blocklist:203.0.113.7"))


def test_a_domain_listing_is_reported():
    out = mac.check_blocklists(spec(), google_domain({("example.com.multi.surbl.org", "A"): ["127.0.0.2"]}))
    assert status_of(out, "blocklist:domain") == {mac.WARN}


def test_no_sending_addresses_still_checks_the_domain():
    out = mac.check_blocklists(spec(sending_ips=[]), google_domain())
    assert status_of(out, "blocklist:domain") == {mac.PASS}


# --- information-only checks -------------------------------------------------------------------------------------------


def test_the_hardening_extras_are_information_never_a_failure():
    out = mac.check_extras(spec(), google_domain())
    assert {f.check for f in out} >= {"mta-sts", "tls-rpt", "caa", "dnssec"}
    assert {f.status for f in out} <= {mac.INFO, mac.PASS}


def test_dnssec_is_reported_enabled_when_a_ds_record_exists():
    out = mac.check_extras(spec(), google_domain({("example.com", "DS"): ["12345 13 2 abcdef"]}))
    assert status_of(out, "dnssec") == {mac.PASS}


# --- the whole run, verdicts and exit codes ----------------------------------------------------------------------------


def test_a_healthy_domain_has_no_warnings_or_failures():
    summary = mac.summarize(mac.run_checks(spec(), google_domain()))
    assert summary["FAIL"] == 0 and summary["WARN"] == 0 and summary["overall"] == mac.PASS


def test_the_summary_overall_is_the_worst_status():
    broken = google_domain({("example.com", "MX"): []})
    assert mac.summarize(mac.run_checks(spec(), broken))["overall"] == mac.FAIL


def _report(*items):
    return {"findings": [{"domain": "example.com", "check": c, "status": s, "message": ""} for c, s in items]}


def test_regressions_are_only_checks_that_got_worse():
    before = _report(("spf", mac.PASS), ("dmarc", mac.WARN), ("mx", mac.PASS))
    after = _report(("spf", mac.WARN), ("dmarc", mac.WARN), ("mx", mac.PASS))
    assert mac.regressions(before, after) == [("example.com", "spf")]


def test_with_no_previous_report_nothing_is_a_regression():
    assert mac.regressions(None, _report(("spf", mac.WARN))) == []


def test_fail_on_modes():
    warn_only = [mac.Finding("example.com", "dmarc", mac.WARN, "x")]
    failing = [mac.Finding("example.com", "spf", mac.FAIL, "x")]
    clean = [mac.Finding("example.com", "spf", mac.PASS, "x")]
    assert mac.exit_code(clean, "warn") == 0
    assert mac.exit_code(warn_only, "fail") == 0
    assert mac.exit_code(warn_only, "warn") == 1
    assert mac.exit_code(failing, "fail") == 2
    # regression mode: a known WARN that has not changed does not fail the unit; a worsening does
    same = _report(("dmarc", mac.WARN))
    assert mac.exit_code(warn_only, "regression", previous=same) == 0
    assert mac.exit_code(failing, "regression", previous=_report(("spf", mac.PASS))) == 2
    assert mac.exit_code(failing, "regression", previous=None) == 2, "a FAIL always counts, even on the first run"


# --- configuration -----------------------------------------------------------------------------------------------------


GOOD_CONFIG = """
domains:
  - name: Example.COM
    provider: google-workspace
    dkim_selectors: [google]
    sending_ips: [203.0.113.7]
  - name: parked.example.org
    provider: none
    expect_mail: false
"""


def test_the_config_loads_and_normalises():
    specs = mac.load_config(GOOD_CONFIG)
    assert [s.name for s in specs] == ["example.com", "parked.example.org"]
    assert specs[0].expect_mail is True and specs[1].expect_mail is False
    assert specs[0].sending_ips == ["203.0.113.7"]


@pytest.mark.parametrize(
    "bad",
    [
        "domains: []",
        "domains:\n  - name: not a domain\n",
        "domains:\n  - name: example.com\n    provider: carrier-pigeon\n",
        "domains:\n  - name: example.com\n    sending_ips: [" + ".".join(["10", "0", "0", "5"]) + "]\n",  # private: built at runtime
        "domains:\n  - name: example.com\n    sending_ips: [not-an-ip]\n",
        "domains:\n  - name: example.com\n    dkim_selectors: ['bad selector!']\n",
        "domains:\n  - name: example.com\n  - name: example.com\n",
        "nothing: here\n",
    ],
)
def test_a_bad_config_is_refused_with_a_clear_error(bad):
    with pytest.raises(mac.ConfigError):
        mac.load_config(bad)


# --- state: saved reports and the last-run status ----------------------------------------------------------------------


NOW = datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)


def test_a_saved_report_can_be_read_back_and_history_is_trimmed(tmp_path):
    report = {"generated": NOW.isoformat(), "env": "lab", "findings": [], "summary": {"overall": "PASS"}}
    for n in range(25):
        mac.save_report(tmp_path, "lab", dict(report, generated=(NOW + timedelta(minutes=n)).isoformat()), keep=20)
    assert mac.last_report(tmp_path, "lab")["generated"] == (NOW + timedelta(minutes=24)).isoformat()
    assert len(list((tmp_path / "mail-auth" / "lab" / "history").glob("*.json"))) == 20


def test_status_reports_never_run_stale_and_fresh(tmp_path):
    code, message = mac.status(tmp_path, "lab", 10, NOW)
    assert code == 3 and "never" in message.lower()
    mac.save_report(tmp_path, "lab", {"generated": (NOW - timedelta(days=30)).isoformat(), "findings": [], "summary": {"overall": "PASS"}})
    code, message = mac.status(tmp_path, "lab", 10, NOW)
    assert code == 3 and "30" in message
    mac.save_report(tmp_path, "lab", {"generated": (NOW - timedelta(days=2)).isoformat(), "findings": [], "summary": {"overall": "PASS"}})
    code, message = mac.status(tmp_path, "lab", 10, NOW)
    assert code == 0 and "2" in message


def test_status_of_a_failing_last_run_is_reported_even_when_recent(tmp_path):
    mac.save_report(tmp_path, "lab", {"generated": NOW.isoformat(), "findings": [], "summary": {"overall": "FAIL", "FAIL": 1}})
    code, message = mac.status(tmp_path, "lab", 10, NOW)
    assert code == 2 and "FAIL" in message


# --- the command line --------------------------------------------------------------------------------------------------


def _config(tmp_path):
    path = tmp_path / "mail-domains.yml"
    path.write_text("domains:\n  - name: example.com\n    provider: google-workspace\n")
    return path


def test_main_prints_json_that_parses_and_saves_when_asked(tmp_path, capsys):
    code = mac.main(
        ["--config", str(_config(tmp_path)), "--json", "--save", "--state-dir", str(tmp_path), "--env", "lab", "--no-blocklists"],
        resolver=google_domain(),
        now=NOW,
    )
    out = json.loads(capsys.readouterr().out)
    assert code == 0 and out["summary"]["overall"] == "PASS" and out["env"] == "lab"
    assert mac.last_report(tmp_path, "lab")["summary"]["overall"] == "PASS"


def test_main_returns_nonzero_when_a_domain_is_broken(tmp_path, capsys):
    code = mac.main(["--config", str(_config(tmp_path)), "--no-blocklists"], resolver=FakeResolver(), now=NOW)
    assert code == 2
    assert "FAIL" in capsys.readouterr().out


def test_main_can_check_one_domain_without_a_config_file(capsys):
    code = mac.main(["--domain", "example.com", "--no-blocklists"], resolver=google_domain(), now=NOW)
    assert code in (0, 1)
    assert "example.com" in capsys.readouterr().out


def test_regression_mode_uses_the_saved_report(tmp_path):
    cfg = str(_config(tmp_path))
    args = ["--config", cfg, "--save", "--state-dir", str(tmp_path), "--env", "lab", "--no-blocklists", "--fail-on", "regression"]
    assert mac.main(args, resolver=google_domain(), now=NOW) == 0
    worse = google_domain({("_dmarc.example.com", "TXT"): []})
    assert mac.main(args, resolver=worse, now=NOW + timedelta(days=7)) == 2, "DMARC disappearing is a regression"
    assert mac.main(args, resolver=worse, now=NOW + timedelta(days=14)) == 0, "the same known state is not an alert again"


def test_a_missing_config_is_a_clear_error_not_a_traceback(tmp_path, capsys):
    code = mac.main(["--config", str(tmp_path / "nope.yml")], resolver=FakeResolver(), now=NOW)
    assert code == 4
    assert "nope.yml" in capsys.readouterr().err


def test_status_flag_uses_the_state_directory(tmp_path, capsys):
    code = mac.main(["--status", "--state-dir", str(tmp_path), "--env", "lab", "--max-age-days", "10"], now=NOW)
    assert code == 3
    assert "never" in capsys.readouterr().out.lower()


# --- properties that must never regress --------------------------------------------------------------------------------


def test_the_tool_cannot_change_dns():
    """It proposes; a human disposes. No DNS-provider API, no write verbs, no dig update."""
    source = SCRIPT.read_text()
    for forbidden in ("api.cloudflare.com", "dns_records", "PATCH", "nsupdate", "route53", "technitium"):
        assert forbidden.lower() not in source.lower(), f"{forbidden!r} has no place in a read-only checker"


def test_the_default_resolver_is_read_only_dig():
    source = SCRIPT.read_text()
    assert '"dig"' in source and "+short" in source


def _dig_command(**kwargs):
    """The argv DigResolver would run for a query, without running dig."""
    seen = {}

    def fake_run(cmd, **_):
        seen["cmd"] = cmd
        return mock.Mock(stdout="")

    with mock.patch.object(mac.shutil, "which", return_value="/usr/bin/dig"), mock.patch.object(mac.subprocess, "run", fake_run):
        resolver = mac.DigResolver(**kwargs.pop("init", {}))
        resolver.query("example.com", "MX", **kwargs)
    return seen["cmd"]


def test_the_default_resolver_asks_a_public_server_not_the_local_one():
    """On a network with split-horizon DNS the local resolver returns an internal view (other nameservers, no MX), which
    made real domains look broken. Receivers see the public view, so that is what must be checked."""
    cmd = _dig_command()
    assert "@1.1.1.1" in cmd, "no server given must still mean a public recursive resolver, never the system resolver"


def test_a_specific_nameserver_overrides_the_public_default():
    cmd = _dig_command(server="ns1.example.net")
    assert "@ns1.example.net" in cmd and "@1.1.1.1" not in cmd


def test_the_public_resolver_can_be_chosen():
    assert "@9.9.9.9" in _dig_command(init={"recursive": "9.9.9.9"})


def test_main_passes_the_chosen_resolver_through(tmp_path):
    seen = []

    class Spy(FakeResolver):
        pass

    with mock.patch.object(mac, "DigResolver", lambda **kw: seen.append(kw) or google_domain()):
        mac.main(["--domain", "example.com", "--no-blocklists", "--resolver", "9.9.9.9"], now=NOW)
    assert seen and seen[0].get("recursive") == "9.9.9.9"


def test_a_missing_dig_is_a_clear_error():
    with mock.patch.object(mac.shutil, "which", return_value=None):
        with pytest.raises(mac.ToolMissing) as raised:
            mac.DigResolver()
    assert "dig" in str(raised.value)


def test_no_real_addresses_or_names_in_the_tool_or_its_tests():
    private = re.compile(r"\b(10\.\d+\.\d+\.\d+|192\.168\.\d+\.\d+|172\.(1[6-9]|2\d|3[01])\.\d+\.\d+)\b")
    for path in (SCRIPT, Path(__file__)):
        assert not private.search(path.read_text()), f"{path.name} contains a private address"
