#!/usr/bin/env python3
"""Read-only email-authentication health check for a domain (#431).

Answers, for each configured domain: can receivers tell that mail from it is genuine, and is anything about
its DNS or sending addresses likely to get that mail junked? Checks:

  delegation   every nameserver answers and agrees on the zone serial
  mx           mail is routed as expected (null MX on a domain that sends no mail)
  spf          exactly one record, a sensible ending, at most 10 DNS lookups, no include loops
  dkim         the key at each configured selector exists, parses, is RSA and large enough
  dmarc        exactly one record with a valid policy and a report address
  blocklist    configured sending addresses and the domain against public blocklists
  extras       MTA-STS, TLS-RPT, CAA, DNSSEC (information only)

It NEVER changes DNS. It reports; a human decides and applies any change, one record at a time, after a snapshot
(see the `mail-auth-check` skill). Every lookup goes through a resolver object, so tests need no network.

    bin/mail-auth-check.py                      # all domains in environments/<env>/mail-domains.yml
    bin/mail-auth-check.py --domain example.com --no-blocklists
    bin/mail-auth-check.py --save --fail-on regression     # what the weekly timer runs
    bin/mail-auth-check.py --status --max-age-days 10      # how old is the last saved run

Exit codes: 0 ok, 1 warnings (only with --fail-on warn), 2 failure or regression, 3 never run / too old (--status),
4 bad or missing configuration, 5 `dig` not installed.

Configuration (environment data, so it lives in the private layer, never in the public repo):

    domains:
      - name: example.com
        provider: google-workspace        # google-workspace | generic | none
        dkim_selectors: [google]          # DNS cannot list selectors, so name them
        sending_ips: [203.0.113.7]        # only addresses YOU send from (public IPv4)
        expect_mail: true                 # false for a domain that must send no mail
"""

from __future__ import annotations

import argparse
import base64
import binascii
import dataclasses
import ipaddress
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

BIN_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BIN_DIR))

PASS, WARN, FAIL, INFO = "PASS", "WARN", "FAIL", "INFO"
RANK = {PASS: 0, INFO: 0, WARN: 1, FAIL: 2}

PROVIDERS = ("google-workspace", "generic", "none")
PROVIDER_SPF_INCLUDE = {"google-workspace": "_spf.google.com"}
PROVIDER_MX_HINT = {"google-workspace": "google"}
PROVIDER_DKIM_SELECTORS = {"google-workspace": ["google"]}

SPF_LOOKUP_LIMIT = 10
DNSBL_IP_ZONES = ("bl.spamcop.net", "zen.spamhaus.org", "b.barracudacentral.org", "dnsbl.dronebl.org", "psbl.surriel.com")
DNSBL_DOMAIN_ZONES = ("multi.surbl.org", "multi.uribl.com", "dbl.spamhaus.org")
HOSTNAME = re.compile(r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z][a-z0-9-]{1,62}$")
SELECTOR = re.compile(r"^[A-Za-z0-9._-]+$")
# Documentation ranges (RFC 5737) are accepted on purpose: examples and tests use them, and Python's is_global rejects them.
# Everything else must be globally routable: private, shared, loopback, link-local and reserved space says nothing to a
# public blocklist.
DOCUMENTATION_NETS = [ipaddress.ip_network(n) for n in ("192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24")]


class ConfigError(Exception):
    pass


class ToolMissing(Exception):
    pass


@dataclasses.dataclass
class Finding:
    domain: str
    check: str
    status: str
    message: str


@dataclasses.dataclass
class DomainSpec:
    name: str
    provider: str = "generic"
    dkim_selectors: list = dataclasses.field(default_factory=list)
    sending_ips: list = dataclasses.field(default_factory=list)
    expect_mail: bool = True


# --- resolver -------------------------------------------------------------------------------------------------------


DEFAULT_RESOLVER = "1.1.1.1"


class DigResolver:
    """Read-only lookups through `dig +short`. TXT strings split into several chunks are joined.

    A query with no explicit server goes to a PUBLIC recursive resolver, never the system one: on a network with
    split-horizon DNS the system resolver returns an internal view of the domain, and what matters is what
    receivers on the internet see. Per-nameserver queries (delegation) name their server explicitly.
    """

    def __init__(self, timeout: int = 4, recursive: str = DEFAULT_RESOLVER):
        if not shutil.which("dig"):
            raise ToolMissing("`dig` is not installed (package: dnsutils or bind-utils); it is the only lookup tool used.")
        self.timeout = timeout
        self.recursive = recursive

    def query(self, name: str, rtype: str, server: str | None = None) -> list:
        cmd = ["dig", "+short", f"+time={self.timeout}", "+tries=2", "@" + (server or self.recursive), name, rtype]
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=self.timeout * 3 + 5).stdout
        except subprocess.TimeoutExpired:
            return []
        lines = [line.strip() for line in out.splitlines() if line.strip() and not line.startswith(";")]
        if rtype.upper() == "TXT":
            joined = []
            for line in lines:
                chunks = re.findall(r'"((?:[^"\\]|\\.)*)"', line)
                joined.append("".join(chunks) if chunks else line)
            return joined
        return lines


# --- helpers --------------------------------------------------------------------------------------------------------


def reverse_ip(ip: str) -> str:
    return ".".join(reversed(ip.split(".")))


def _host(value: str) -> str:
    return value.strip().rstrip(".").lower()


def _tags(text: str) -> dict:
    tags = {}
    for part in text.split(";"):
        if "=" in part:
            key, value = part.split("=", 1)
            tags[key.strip().lower()] = value.strip()
    return tags


def _one_or_pass(domain: str, check: str, issues: list, ok_message: str) -> list:
    """The issues, or a single PASS when there are none (so a healthy check has exactly one status)."""
    if issues:
        return [Finding(domain, check, status, message) for status, message in issues]
    return [Finding(domain, check, PASS, ok_message)]


def _effective(spec: DomainSpec) -> dict:
    return {
        "spf_include": PROVIDER_SPF_INCLUDE.get(spec.provider),
        "mx_hint": PROVIDER_MX_HINT.get(spec.provider),
        "selectors": spec.dkim_selectors or PROVIDER_DKIM_SELECTORS.get(spec.provider, []),
    }


# --- SPF ------------------------------------------------------------------------------------------------------------


def spf_records(resolver, domain: str) -> list:
    return [t for t in resolver.query(domain, "TXT") if re.match(r"(?i)^v=spf1(\s|$)", t.strip())]


def parse_spf(text: str) -> dict:
    mechanisms, all_qualifier, redirect = [], None, None
    for term in text.split()[1:]:
        low = term.lower()
        match = re.match(r"^([+\-~?]?)all$", low)
        if match:
            all_qualifier = match.group(1) or "+"
            continue
        if low.startswith("redirect="):
            redirect = term.split("=", 1)[1]
            continue
        match = re.match(r"^[+\-~?]?(include|a|mx|ptr|exists|ip4|ip6)(?:[:/](.*))?$", low)
        if match:
            mechanisms.append((match.group(1), (term.split(":", 1)[1] if ":" in term else "")))
    return {"mechanisms": mechanisms, "all": all_qualifier, "redirect": redirect}


def spf_lookup_count(domain: str, resolver, _seen: tuple = (), _depth: int = 0) -> tuple:
    """DNS-lookup mechanisms a receiver must evaluate (limit 10), and the problems found while following includes."""
    problems = []
    if domain in _seen:
        return 0, [f"include loop through {domain}"]
    if _depth > 12:
        return 0, [f"include chain too deep at {domain}"]
    records = spf_records(resolver, domain)
    if not records:
        return 0, [f"{domain} has no SPF record but is included or redirected to"]
    parsed = parse_spf(records[0])
    count = 0
    for kind, target in parsed["mechanisms"]:
        if kind in ("a", "mx", "ptr", "exists"):
            count += 1
        elif kind == "include":
            count += 1
            sub, sub_problems = spf_lookup_count(_host(target), resolver, _seen + (domain,), _depth + 1)
            count += sub
            problems += sub_problems
    if parsed["redirect"]:
        count += 1
        sub, sub_problems = spf_lookup_count(_host(parsed["redirect"]), resolver, _seen + (domain,), _depth + 1)
        count += sub
        problems += sub_problems
    return min(count, 99), problems


def check_spf(spec: DomainSpec, resolver) -> list:
    domain, eff = spec.name, _effective(spec)
    records = spf_records(resolver, domain)
    if not records:
        status = FAIL if spec.expect_mail else WARN
        advice = "publish one" if spec.expect_mail else "publish `v=spf1 -all` so nobody can send as this domain"
        return [Finding(domain, "spf", status, f"no SPF record; {advice}")]
    if len(records) > 1:
        return [Finding(domain, "spf", FAIL, f"more than one SPF record ({len(records)}): receivers treat that as a permanent error")]
    parsed = parse_spf(records[0])
    issues = []
    qualifier = parsed["all"]
    if qualifier == "+":
        issues.append((FAIL, "ends in +all: anyone may send as this domain"))
    elif qualifier == "?":
        issues.append((WARN, "ends in ?all (neutral): it protects nothing; use ~all or -all"))
    elif qualifier is None and not parsed["redirect"]:
        issues.append((WARN, "has no `all` ending, so the policy is open-ended"))
    elif not spec.expect_mail and qualifier != "-":
        issues.append((WARN, "this domain sends no mail but its SPF does not end in -all"))
    count, problems = spf_lookup_count(domain, resolver)
    if count > SPF_LOOKUP_LIMIT:
        issues.append((FAIL, f"needs {count} DNS lookups; the limit is {SPF_LOOKUP_LIMIT} (receivers give up with a permanent error)"))
    elif count == SPF_LOOKUP_LIMIT:
        issues.append((WARN, f"uses {count} DNS lookups, exactly at the limit of {SPF_LOOKUP_LIMIT}"))
    issues += [(FAIL, problem) for problem in problems]
    wanted = eff["spf_include"]
    if wanted and spec.expect_mail and not any(kind == "include" and _host(target) == wanted for kind, target in parsed["mechanisms"]):
        issues.append((WARN, f"does not include {wanted}, which the {spec.provider} provider needs"))
    qualifier_name = {"~": "soft-fail (~all)", "-": "reject (-all)"}.get(qualifier or "", "")
    return _one_or_pass(domain, "spf", issues, f"one record, {qualifier_name or 'valid'}, {count} of {SPF_LOOKUP_LIMIT} lookups")


# --- DKIM -----------------------------------------------------------------------------------------------------------


def _der_read(data: bytes, pos: int) -> tuple:
    """(tag, content_start, content_end) of the DER element at pos."""
    if pos + 2 > len(data):
        raise ValueError("truncated DER")
    tag, length, pos = data[pos], data[pos + 1], pos + 2
    if length & 0x80:
        count = length & 0x7F
        if count == 0 or count > 4 or pos + count > len(data):
            raise ValueError("bad DER length")
        length = int.from_bytes(data[pos : pos + count], "big")
        pos += count
    end = pos + length
    if end > len(data):
        raise ValueError("truncated DER")
    return tag, pos, end


def rsa_modulus_bits(b64: str) -> int:
    """Bit length of the RSA modulus in a base64 SubjectPublicKeyInfo (what DKIM publishes in p=)."""
    try:
        data = base64.b64decode(b64.strip(), validate=True)
    except (binascii.Error, ValueError) as error:
        raise ValueError(f"p= is not valid base64: {error}") from None
    if not data:
        raise ValueError("p= is empty")
    tag, start, end = _der_read(data, 0)
    if tag != 0x30:
        raise ValueError("not a DER SEQUENCE")
    tag, a_start, a_end = _der_read(data, start)
    if tag != 0x30:
        raise ValueError("no algorithm identifier")
    tag, oid_start, oid_end = _der_read(data, a_start)
    if tag != 0x06 or data[oid_start:oid_end] != bytes.fromhex("2a864886f70d010101"):
        raise ValueError("not an RSA key")
    tag, b_start, b_end = _der_read(data, a_end)
    if tag != 0x03:
        raise ValueError("no key bit string")
    inner = data[b_start + 1 : b_end]
    tag, s_start, s_end = _der_read(inner, 0)
    if tag != 0x30:
        raise ValueError("no RSA public key structure")
    tag, n_start, n_end = _der_read(inner, s_start)
    if tag != 0x02:
        raise ValueError("no RSA modulus")
    return int.from_bytes(inner[n_start:n_end], "big").bit_length()


def check_dkim(spec: DomainSpec, resolver) -> list:
    domain, selectors = spec.name, _effective(spec)["selectors"]
    if not selectors:
        return [Finding(domain, "dkim", INFO, "no DKIM selectors configured, so nothing was checked (DNS cannot list selectors)")]
    findings = []
    for selector in selectors:
        check = f"dkim:{selector}"
        records = resolver.query(f"{selector}._domainkey.{domain}", "TXT")
        if not records:
            findings.append(Finding(domain, check, FAIL, f"no record at {selector}._domainkey.{domain}"))
            continue
        tags = _tags(records[0])
        if tags.get("v", "DKIM1").upper() != "DKIM1" or "p" not in tags:
            findings.append(Finding(domain, check, FAIL, "the record is not a DKIM key (no v=DKIM1 and p=)"))
            continue
        if not tags["p"]:
            findings.append(Finding(domain, check, FAIL, "the key is revoked (empty p=)"))
            continue
        if tags.get("k", "rsa").lower() != "rsa":
            findings.append(Finding(domain, check, PASS, f"published, key type {tags.get('k')}"))
            continue
        try:
            bits = rsa_modulus_bits(tags["p"])
        except ValueError as error:
            findings.append(Finding(domain, check, FAIL, f"the key cannot be parsed: {error}"))
            continue
        if bits < 1024:
            findings.append(Finding(domain, check, FAIL, f"{bits}-bit RSA key is too weak"))
        elif bits < 2048:
            findings.append(Finding(domain, check, WARN, f"{bits}-bit RSA key; 2048 is the current recommendation"))
        else:
            findings.append(Finding(domain, check, PASS, f"valid {bits}-bit RSA key"))
    return findings


# --- DMARC ----------------------------------------------------------------------------------------------------------


def check_dmarc(spec: DomainSpec, resolver) -> list:
    domain = spec.name
    records = [t for t in resolver.query(f"_dmarc.{domain}", "TXT") if re.match(r"(?i)^v=DMARC1\b", t.strip())]
    if not records:
        return [Finding(domain, "dmarc", WARN, "no DMARC record; publish at least `v=DMARC1; p=none` with a report address")]
    if len(records) > 1:
        return [Finding(domain, "dmarc", FAIL, "more than one DMARC record: receivers ignore all of them")]
    tags = _tags(records[0])
    policy = tags.get("p", "").lower()
    if policy not in ("none", "quarantine", "reject"):
        return [Finding(domain, "dmarc", FAIL, f"invalid policy p={tags.get('p', '')!r}")]
    note = "monitor only (p=none): move to quarantine or reject once the reports are clean" if policy == "none" else f"enforcing (p={policy})"
    findings = [Finding(domain, "dmarc", PASS, note)]
    if "rua" not in tags:
        findings.append(Finding(domain, "dmarc", INFO, "no rua= report address, so no aggregate reports are received"))
    return findings


# --- MX -------------------------------------------------------------------------------------------------------------


def check_mx(spec: DomainSpec, resolver) -> list:
    domain, hint = spec.name, _effective(spec)["mx_hint"]
    records = resolver.query(domain, "MX")
    hosts = [_host(r.split()[-1]) for r in records if r.split()]
    null_mx = bool(records) and all(h in ("", ".") for h in hosts)
    if not spec.expect_mail:
        if null_mx:
            return [Finding(domain, "mx", PASS, "null MX: this domain accepts no mail")]
        if not records:
            return [Finding(domain, "mx", WARN, "no MX; publish a null MX (`0 .`) so mail to this domain is refused outright")]
        return [Finding(domain, "mx", WARN, "this domain should send and accept no mail but has MX records")]
    if not records:
        return [Finding(domain, "mx", FAIL, "no MX record: mail to this domain has nowhere to go")]
    if null_mx:
        return [Finding(domain, "mx", FAIL, "null MX on a domain that is expected to receive mail")]
    if hint and not all(hint in h for h in hosts):
        return [Finding(domain, "mx", WARN, f"MX hosts are not all {hint}'s: {', '.join(hosts)}")]
    return [Finding(domain, "mx", PASS, f"{len(hosts)} MX record(s)")]


# --- delegation -----------------------------------------------------------------------------------------------------


def check_delegation(spec: DomainSpec, resolver) -> list:
    domain = spec.name
    servers = sorted({_host(n) for n in resolver.query(domain, "NS") if n.strip()})
    if not servers:
        return [Finding(domain, "delegation", FAIL, "no nameservers answer for this domain")]
    issues, serials = [], {}
    for server in servers:
        soa = resolver.query(domain, "SOA", server=server)
        parts = soa[0].split() if soa else []
        if len(parts) < 3 or not parts[2].isdigit():
            issues.append((WARN, f"nameserver {server} does not answer"))
        else:
            serials[server] = int(parts[2])
    if len(set(serials.values())) > 1:
        issues.append((WARN, "nameservers disagree on the zone serial: " + ", ".join(f"{s}={n}" for s, n in sorted(serials.items()))))
    return _one_or_pass(domain, "delegation", issues, f"{len(servers)} nameserver(s) answer and agree")


# --- blocklists -----------------------------------------------------------------------------------------------------


def _blocklist_answer(zone: str, answers: list) -> str:
    """'listed', 'inconclusive' (the list refuses open resolvers) or 'clean' for a DNSBL answer."""
    if not answers:
        return "clean"
    if any(a.startswith("127.255.255.") for a in answers):
        return "inconclusive"
    if zone == "multi.uribl.com" and answers == ["127.0.0.1"]:
        return "inconclusive"
    return "listed"


def check_blocklists(spec: DomainSpec, resolver) -> list:
    domain, findings = spec.name, []

    def scan(subject: str, label: str, zones: tuple, check: str):
        listed, vague = [], []
        for zone in zones:
            answers = resolver.query(f"{label}.{zone}", "A")
            verdict = _blocklist_answer(zone, answers)
            if verdict == "listed":
                listed.append(f"{zone} ({', '.join(answers)})")
            elif verdict == "inconclusive":
                vague.append(zone)
        for entry in listed:
            findings.append(Finding(domain, check, WARN, f"{subject} is listed at {entry}"))
        if not listed:
            findings.append(Finding(domain, check, PASS, f"{subject} is not listed at the {len(zones) - len(vague)} lists that answered"))
        if vague:
            findings.append(Finding(domain, check, INFO, f"inconclusive: {', '.join(vague)} refuse queries from open resolvers"))

    for ip in spec.sending_ips:
        scan(ip, reverse_ip(ip), DNSBL_IP_ZONES, f"blocklist:{ip}")
    scan(domain, domain, DNSBL_DOMAIN_ZONES, "blocklist:domain")
    return findings


# --- information-only extras ----------------------------------------------------------------------------------------


def check_extras(spec: DomainSpec, resolver) -> list:
    domain = spec.name
    sts = [t for t in resolver.query(f"_mta-sts.{domain}", "TXT") if t.upper().startswith("V=STSV1")]
    rpt = [t for t in resolver.query(f"_smtp._tls.{domain}", "TXT") if t.upper().startswith("V=TLSRPTV1")]
    caa = resolver.query(domain, "CAA")
    ds = resolver.query(domain, "DS")
    return [
        Finding(domain, "mta-sts", PASS if sts else INFO, "MTA-STS published" if sts else "MTA-STS not published (optional hardening)"),
        Finding(domain, "tls-rpt", PASS if rpt else INFO, "TLS-RPT published" if rpt else "TLS-RPT not published (optional)"),
        Finding(domain, "caa", PASS if caa else INFO, "CAA restricts certificate issuance" if caa else "no CAA record: any certificate authority may issue"),
        Finding(domain, "dnssec", PASS if ds else INFO, "DNSSEC enabled (DS at the registry)" if ds else "DNSSEC not enabled"),
    ]


# --- the whole run, verdicts ----------------------------------------------------------------------------------------


def run_checks(spec: DomainSpec, resolver, blocklists: bool = True) -> list:
    findings = []
    findings += check_delegation(spec, resolver)
    findings += check_mx(spec, resolver)
    findings += check_spf(spec, resolver)
    findings += check_dkim(spec, resolver)
    findings += check_dmarc(spec, resolver)
    if blocklists:
        findings += check_blocklists(spec, resolver)
    findings += check_extras(spec, resolver)
    return findings


def summarize(findings: list) -> dict:
    counts = {PASS: 0, WARN: 0, FAIL: 0, INFO: 0}
    for finding in findings:
        counts[finding.status] += 1
    overall = FAIL if counts[FAIL] else WARN if counts[WARN] else PASS
    return {**counts, "overall": overall}


def _as_report(findings: list) -> dict:
    return {"findings": [dataclasses.asdict(f) for f in findings]}


def regressions(previous, current) -> list:
    """(domain, check) pairs whose status got worse than in the previous report. No previous report: none."""
    if not previous:
        return []
    before = {}
    for item in previous.get("findings", []):
        key = (item["domain"], item["check"])
        before[key] = max(before.get(key, 0), RANK[item["status"]])
    worse, seen = [], set()
    for item in current.get("findings", []):
        key = (item["domain"], item["check"])
        if RANK[item["status"]] > before.get(key, 0) and key not in seen:
            seen.add(key)
            worse.append(key)
    return worse


def exit_code(findings: list, fail_on: str, previous=None) -> int:
    worst = max((RANK[f.status] for f in findings), default=0)
    if worst >= 2:
        return 2
    if fail_on == "warn":
        return 1 if worst == 1 else 0
    if fail_on == "regression" and regressions(previous, _as_report(findings)):
        return 2
    return 0


# --- configuration --------------------------------------------------------------------------------------------------


def load_config(text: str) -> list:
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise ConfigError(f"the configuration is not valid YAML: {error}") from None
    if not isinstance(data, dict) or "domains" not in data:
        raise ConfigError("the configuration needs a top-level `domains:` list")
    items = data["domains"]
    if not isinstance(items, list) or not items:
        raise ConfigError("`domains:` must be a non-empty list")
    specs, seen = [], set()
    for item in items:
        if not isinstance(item, dict) or "name" not in item:
            raise ConfigError("every domain needs a `name:`")
        name = str(item["name"]).strip().lower()
        if not HOSTNAME.match(name):
            raise ConfigError(f"{item['name']!r} is not a valid domain name")
        if name in seen:
            raise ConfigError(f"{name} is listed more than once")
        seen.add(name)
        provider = item.get("provider", "generic")
        if provider not in PROVIDERS:
            raise ConfigError(f"{name}: provider must be one of {', '.join(PROVIDERS)}, got {provider!r}")
        selectors = [str(s) for s in item.get("dkim_selectors", [])]
        for selector in selectors:
            if not SELECTOR.match(selector):
                raise ConfigError(f"{name}: {selector!r} is not a valid DKIM selector")
        ips = []
        for raw in item.get("sending_ips", []):
            try:
                ip = ipaddress.ip_address(str(raw))
            except ValueError:
                raise ConfigError(f"{name}: {raw!r} is not an IP address") from None
            if ip.version != 4 or not (ip.is_global or any(ip in net for net in DOCUMENTATION_NETS)):
                raise ConfigError(f"{name}: sending_ips must be public IPv4 addresses (blocklists say nothing about private ones), got {raw}")
            ips.append(str(ip))
        specs.append(DomainSpec(name, provider, selectors, ips, bool(item.get("expect_mail", True))))
    return specs


# --- saved state ----------------------------------------------------------------------------------------------------


def _env_state(state_dir: Path, env: str) -> Path:
    return Path(state_dir) / "mail-auth" / env


def save_report(state_dir, env: str, report: dict, keep: int = 20) -> None:
    folder = _env_state(state_dir, env)
    history = folder / "history"
    history.mkdir(parents=True, exist_ok=True)
    text = json.dumps(report, indent=1)
    (folder / "last-run.json").write_text(text)
    stamp = re.sub(r"[^0-9A-Za-z]", "-", str(report.get("generated", "unknown")))
    (history / f"{stamp}.json").write_text(text)
    for old in sorted(history.glob("*.json"))[:-keep]:
        old.unlink()


def last_report(state_dir, env: str):
    path = _env_state(state_dir, env) / "last-run.json"
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def status(state_dir, env: str, max_age_days: int, now: datetime) -> tuple:
    report = last_report(state_dir, env)
    if not report:
        return 3, f"mail-auth-check has never run for environment {env!r}"
    try:
        age = (now - datetime.fromisoformat(report["generated"])).days
    except (KeyError, ValueError):
        return 3, "the last saved report has no usable timestamp"
    summary = report.get("summary", {})
    overall = summary.get("overall", "unknown")
    if age > max_age_days:
        return 3, f"the last check was {age} days ago (limit {max_age_days}); result then: {overall}"
    if overall == FAIL:
        return 2, f"the last check ({age} days ago) found a FAIL: {summary.get('FAIL', '?')} failing check(s)"
    if overall == WARN:
        return 0, f"the last check ({age} days ago) has warnings: {summary.get('WARN', '?')}"
    return 0, f"the last check was {age} days ago: {overall}"


# --- command line ---------------------------------------------------------------------------------------------------


def _repo_root() -> Path:
    import os

    return Path(os.environ.get("OPSKIT_ROOT") or BIN_DIR.parent)


def _main_checkout(root: Path) -> Path:
    """The primary checkout, so worktrees share one environment layer and one state directory."""
    try:
        common = subprocess.run(["git", "rev-parse", "--git-common-dir"], cwd=root, capture_output=True, text=True, check=True).stdout.strip()
        return (root / common).resolve().parent
    except (subprocess.CalledProcessError, OSError):
        return root


def _default_env(root: Path) -> str:
    try:
        import active_env

        name, _source = active_env.resolve(root)
        return name or "default"
    except Exception:
        return "default"


def _render(findings: list, specs: list) -> str:
    lines = []
    for spec in specs:
        mine = [f for f in findings if f.domain == spec.name]
        lines.append(f"{spec.name}  ({spec.provider}{'' if spec.expect_mail else ', no mail expected'})")
        for finding in mine:
            lines.append(f"  [{finding.status:<4}] {finding.check:<26} {finding.message}")
        lines.append("")
    return "\n".join(lines)


def main(argv=None, resolver=None, now=None) -> int:
    parser = argparse.ArgumentParser(prog="mail-auth-check", description="Read-only email-authentication health check.")
    parser.add_argument("--config", help="mail-domains.yml (default: environments/<env>/mail-domains.yml)")
    parser.add_argument("--domain", action="append", default=[], help="check this domain (repeatable); no config file needed")
    parser.add_argument("--env", help="environment name (default: the active environment)")
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    parser.add_argument("--save", action="store_true", help="save the report under <main checkout>/.local/mail-auth/<env>/")
    parser.add_argument("--state-dir", help="state directory (default: <main checkout>/.local)")
    parser.add_argument("--no-blocklists", action="store_true", help="skip the blocklist lookups")
    parser.add_argument("--resolver", default=DEFAULT_RESOLVER,
                        help=f"public recursive resolver to ask (default {DEFAULT_RESOLVER}); never the local one, which may be split-horizon")
    parser.add_argument("--fail-on", choices=("fail", "warn", "regression"), default="fail",
                        help="what makes the exit code non-zero (regression = only a result worse than the last saved run)")
    parser.add_argument("--status", action="store_true", help="report the age and result of the last saved run, then exit")
    parser.add_argument("--max-age-days", type=int, default=10, help="with --status: older than this is a problem (default 10)")
    args = parser.parse_args(argv)

    now = now or datetime.now(timezone.utc)
    root = _repo_root()
    env = args.env or _default_env(root)
    state_dir = Path(args.state_dir) if args.state_dir else _main_checkout(root) / ".local"

    if args.status:
        code, message = status(state_dir, env, args.max_age_days, now)
        print(message)
        return code

    try:
        if args.domain:
            specs = [DomainSpec(name=d.strip().lower()) for d in args.domain]
            for spec in specs:
                if not HOSTNAME.match(spec.name):
                    raise ConfigError(f"{spec.name!r} is not a valid domain name")
        else:
            path = Path(args.config) if args.config else _main_checkout(root) / "environments" / env / "mail-domains.yml"
            if not path.is_file():
                raise ConfigError(f"configuration file not found: {path}")
            specs = load_config(path.read_text())
        resolver = resolver or DigResolver(recursive=args.resolver)
    except ConfigError as error:
        print(f"mail-auth-check: {error}", file=sys.stderr)
        return 4
    except ToolMissing as error:
        print(f"mail-auth-check: {error}", file=sys.stderr)
        return 5

    findings = []
    for spec in specs:
        findings += run_checks(spec, resolver, blocklists=not args.no_blocklists)
    report = {"generated": now.isoformat(), "env": env, "findings": [dataclasses.asdict(f) for f in findings], "summary": summarize(findings)}
    previous = last_report(state_dir, env)
    code = exit_code(findings, args.fail_on, previous)
    if args.json:
        print(json.dumps(report, indent=1))
    else:
        summary = report["summary"]
        print(_render(findings, specs))
        print(f"Result: {summary['overall']}  ({summary['PASS']} pass, {summary['WARN']} warn, {summary['FAIL']} fail, {summary['INFO']} info)")
    if args.save:
        save_report(state_dir, env, report)
    return code


if __name__ == "__main__":
    sys.exit(main())
