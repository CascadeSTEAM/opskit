"""Tests for scripts/scanner/lib/enricher.py — the dedup/collate/link engine.

Covers the 2026-07-14 defect classes (see
proposals/approved/ansible-codebase-audit-remediation.md session work and the
critique plan): parent-inference corruption, dead DNS-link check, zombie
duplicates, unsafe IP merges, nondeterministic host resolution, and the
idempotency contract (a second enrichment run must change nothing).

Run:  python3 -m unittest discover scripts/scanner/tests -v
(stdlib only — no pytest dependency)
"""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.scanner.lib import enricher  # noqa: E402


def _device(name, dtype='server', mac=None, ip=None, description='',
            gateway=None, dns=None, deps=None, maturity='L1'):
    iface = {'name': 'eth0'}
    if mac:
        iface['mac'] = mac
    if ip:
        iface['ipv4'] = f'{ip}/24'
    if gateway:
        iface['gateway'] = gateway
    if dns:
        iface['dns'] = dns
    doc = {
        'device': {
            'hostname': name,
            'type': dtype,
            'description': description,
            'networking': {'interfaces': [iface]},
            'metadata': {'maturity': maturity},
        }
    }
    if deps:
        doc['device']['dependencies'] = deps
    return doc


class EnricherTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='enricher-test-'))
        self.devices_dir = self.tmp / 'devices'
        self.devices_dir.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, name, doc):
        with open(self.devices_dir / f'{name}.yml', 'w') as fh:
            yaml.dump(doc, fh, default_flow_style=False, sort_keys=False)

    def _read(self, name):
        with open(self.devices_dir / f'{name}.yml') as fh:
            return yaml.safe_load(fh)

    def _snapshot(self):
        return {
            f.name: f.read_text()
            for f in sorted(self.devices_dir.glob('*.yml'))
        }

    # ── D4/D3: deduplication ─────────────────────────────────────

    def test_mac_dup_keeps_curated_name_and_deletes_stub(self):
        self._write('alpha', _device('alpha', mac='AA:BB:CC:00:00:01',
                                     ip='10.99.0.10', maturity='L1'))
        # Fat stub, same MAC — must lose to the curated name anyway
        stub = _device('host-10-10-0-10', mac='AA:BB:CC:00:00:01',
                       ip='10.99.0.10', maturity='L2',
                       description='x' * 500)
        self._write('host-10-10-0-10', stub)

        merged = enricher.deduplicate(self.devices_dir)

        self.assertEqual(merged, {'host-10-10-0-10': 'alpha'})
        self.assertFalse((self.devices_dir / 'host-10-10-0-10.yml').exists(),
                         'discarded duplicate must be deleted, not left as a zombie')
        self.assertTrue((self.devices_dir / 'alpha.yml').exists())

    def test_shared_ip_with_different_macs_never_merges(self):
        self._write('vip-a', _device('vip-a', mac='AA:BB:CC:00:00:0A', ip='10.99.0.20'))
        self._write('vip-b', _device('vip-b', mac='AA:BB:CC:00:00:0B', ip='10.99.0.20'))

        merged = enricher.deduplicate(self.devices_dir)

        self.assertEqual(merged, {},
                         'two devices with disjoint MACs sharing an IP are a '
                         'VIP/DHCP signal, not duplicates')
        self.assertTrue((self.devices_dir / 'vip-a.yml').exists())
        self.assertTrue((self.devices_dir / 'vip-b.yml').exists())

    def test_dedup_remaps_references_to_kept_name(self):
        self._write('alpha', _device('alpha', mac='AA:BB:CC:00:00:01', ip='10.99.0.10'))
        self._write('host-10-10-0-10', _device('host-10-10-0-10',
                                               mac='AA:BB:CC:00:00:01', ip='10.99.0.10'))
        self._write('leaf', _device('leaf', ip='10.99.0.30',
                                    deps={'depends_on': ['host-10-10-0-10']}))

        enricher.enrich_dataset(self.tmp)

        leaf = self._read('leaf')
        self.assertIn('alpha', leaf['device']['dependencies']['depends_on'],
                      'refs to a merged-away name must follow the merge')
        self.assertNotIn('host-10-10-0-10',
                         leaf['device']['dependencies']['depends_on'])

    # ── D1: parent inference ─────────────────────────────────────

    def test_physical_host_never_gains_hosted_on(self):
        # A hypervisor whose depends_on already lists the router (as the old
        # Phase 5 would leave it) must NOT become "hosted on" the router.
        self._write('router', _device('router', dtype='router', ip='10.99.0.1'))
        self._write('hv1', _device('hv1', dtype='hypervisor', ip='10.99.0.5',
                                   gateway='10.99.0.1',
                                   deps={'depends_on': ['router']}))

        enricher.enrich_dataset(self.tmp)

        hv1 = self._read('hv1')
        self.assertNotIn('hosted_on', hv1['device'].get('dependencies', {}),
                         'the 2026-07-14 corruption: depends_on[0] treated as parent')

    def test_container_gets_hosted_on_from_description(self):
        self._write('hv1', _device('hv1', dtype='hypervisor', ip='10.99.0.5'))
        self._write('ct101', _device('ct101', dtype='lxc', ip='10.99.0.50',
                                     description='Web app (LXC 101 on hv1)'))

        enricher.enrich_dataset(self.tmp)

        ct = self._read('ct101')
        deps = ct['device']['dependencies']
        self.assertEqual(deps['hosted_on'], ['hv1'])
        self.assertTrue(deps.get('hosted_on_inferred'),
                        'prose-derived links must be marked inferred')
        hv = self._read('hv1')
        self.assertIn('ct101', hv['device']['dependencies']['children'])

    def test_on_docker_is_not_a_parent(self):
        self._write('hv1', _device('hv1', dtype='hypervisor', ip='10.99.0.5'))
        self._write('svc', _device('svc', dtype='lxc', ip='10.99.0.60',
                                   description='Nginx Proxy Manager on Docker'))

        enricher.enrich_dataset(self.tmp)

        svc = self._read('svc')
        self.assertNotIn('hosted_on', svc['device'].get('dependencies', {}))

    # ── D2: infrastructure links ─────────────────────────────────

    def test_dns_and_gateway_links_created(self):
        self._write('router', _device('router', dtype='router', ip='10.99.0.1'))
        self._write('dns1', _device('dns1', dtype='server', ip='10.99.0.4',
                                    description='Technitium DNS server'))
        self._write('web', _device('web', ip='10.99.0.40',
                                   gateway='10.99.0.1', dns=['10.99.0.4']))

        summary = enricher.enrich_dataset(self.tmp)

        web = self._read('web')
        deps = web['device']['dependencies']['depends_on']
        self.assertIn('dns1', deps, 'DNS link (dead code before the fix: '
                                    'dns_ip != dns_ip was always False)')
        self.assertIn('router', deps)
        self.assertGreaterEqual(summary['infra_links'], 2)

    def test_dns_server_does_not_depend_on_itself(self):
        self._write('dns1', _device('dns1', dtype='server', ip='10.99.0.4',
                                    dns=['10.99.0.4'],
                                    description='Technitium DNS server'))

        enricher.enrich_dataset(self.tmp)

        dns1 = self._read('dns1')
        self.assertNotIn('dns1',
                         dns1['device'].get('dependencies', {}).get('depends_on', []))

    # ── D5: host resolution determinism ──────────────────────────

    def test_ambiguous_prefix_resolves_to_none(self):
        # "on pve" with pve1 AND pve2 present must link to NEITHER.
        self._write('pve1', _device('pve1', dtype='hypervisor', ip='10.99.0.5'))
        self._write('pve2', _device('pve2', dtype='hypervisor', ip='10.99.0.6'))
        self._write('ct1', _device('ct1', dtype='lxc', ip='10.99.0.70',
                                   description='LXC 200 on pve'))

        enricher.enrich_dataset(self.tmp)

        ct = self._read('ct1')
        self.assertNotIn('hosted_on', ct['device'].get('dependencies', {}),
                         'ambiguous parent must not be guessed')

    # ── D7 + idempotency contract ────────────────────────────────

    def test_second_run_changes_nothing(self):
        self._write('hv1', _device('hv1', dtype='hypervisor', ip='10.99.0.5'))
        self._write('ct101', _device('ct101', dtype='lxc', ip='10.99.0.50',
                                     description='LXC 101 on hv1',
                                     gateway='10.99.0.1'))
        self._write('router', _device('router', dtype='router', ip='10.99.0.1'))
        self._write('alpha', _device('alpha', mac='AA:BB:CC:00:00:01', ip='10.99.0.10'))
        self._write('host-10-10-0-10', _device('host-10-10-0-10',
                                               mac='AA:BB:CC:00:00:01', ip='10.99.0.10'))

        enricher.enrich_dataset(self.tmp)
        after_first = self._snapshot()

        summary2 = enricher.enrich_dataset(self.tmp)
        after_second = self._snapshot()

        self.assertEqual(after_first, after_second,
                         'enrichment must be idempotent — run 2 is a no-op')
        self.assertEqual(summary2.get('files_written', 0), 0)
        self.assertEqual(summary2.get('dedup_merged', 0), 0,
                         'previously merged pairs must not re-merge')


if __name__ == '__main__':
    unittest.main(verbosity=2)
