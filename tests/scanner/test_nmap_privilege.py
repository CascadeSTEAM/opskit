"""Tests for scanner_lib.nmap_runner privilege handling (issue #141).

An unprivileged nmap discovery on a directly-attached subnet "succeeds" but
loses all ARP-level data — device YAMLs get empty MACs and no vendor. That
silent degradation is the bug: the scan must either run with root (--sudo)
or warn loudly about exactly what will be missing.
"""

from unittest import mock

from bin.scanner_lib import nmap_runner


# ── is_local_subnet ──────────────────────────────────────────────────────


def _mock_socket_with_source(source_ip):
    """A socket whose kernel-chosen source address is `source_ip`."""
    sock = mock.MagicMock()
    sock.getsockname.return_value = (source_ip, 12345)
    sock.__enter__ = mock.Mock(return_value=sock)
    sock.__exit__ = mock.Mock(return_value=False)
    return sock


def test_local_subnet_when_source_ip_inside_network():
    with mock.patch("socket.socket",
                    return_value=_mock_socket_with_source("192.0.2.42")):
        assert nmap_runner.is_local_subnet("192.0.2.0/24") is True


def test_remote_subnet_when_source_ip_outside_network():
    # Routed subnet: the kernel picks a source address on another interface.
    with mock.patch("socket.socket",
                    return_value=_mock_socket_with_source("198.51.100.7")):
        assert nmap_runner.is_local_subnet("192.0.2.0/24") is False


def test_unreachable_network_is_not_local():
    sock = _mock_socket_with_source("192.0.2.42")
    sock.connect.side_effect = OSError("Network is unreachable")
    with mock.patch("socket.socket", return_value=sock):
        assert nmap_runner.is_local_subnet("192.0.2.0/24") is False


def test_invalid_cidr_is_not_local():
    assert nmap_runner.is_local_subnet("not-a-subnet") is False


def test_host_route_slash32_does_not_crash():
    # ipaddress.hosts() returns a list (not a generator) for /32 and /31,
    # which broke next() — seen live on WireGuard /32 peer addresses.
    with mock.patch("socket.socket",
                    return_value=_mock_socket_with_source("192.0.2.7")):
        assert nmap_runner.is_local_subnet("192.0.2.7/32") is True


# ── unprivileged_scan_warning ────────────────────────────────────────────


def _warning(subnets, privileged, use_sudo, local=True):
    with mock.patch.object(nmap_runner, "is_local_subnet",
                           return_value=local):
        return nmap_runner.unprivileged_scan_warning(
            subnets, privileged, use_sudo)


def test_warns_on_unprivileged_local_scan():
    msg = _warning(["192.0.2.0/24"], privileged=False, use_sudo=False)
    assert msg is not None
    assert "192.0.2.0/24" in msg
    assert "MAC" in msg
    assert "--sudo" in msg


def test_silent_when_root():
    assert _warning(["192.0.2.0/24"], privileged=True, use_sudo=False) is None


def test_silent_when_sudo_requested():
    assert _warning(["192.0.2.0/24"], privileged=False, use_sudo=True) is None


def test_silent_when_no_subnet_is_local():
    assert _warning(["192.0.2.0/24"], privileged=False, use_sudo=False,
                    local=False) is None


def test_warning_names_only_the_local_subnets():
    def one_local(net):
        return net == "192.0.2.0/24"

    with mock.patch.object(nmap_runner, "is_local_subnet",
                           side_effect=one_local):
        msg = nmap_runner.unprivileged_scan_warning(
            ["192.0.2.0/24", "198.51.100.0/24"], False, False)
    assert "192.0.2.0/24" in msg
    assert "198.51.100.0/24" not in msg


# ── use_sudo plumbing ────────────────────────────────────────────────────


def test_discover_prepends_sudo():
    captured = {}

    def fake_run(cmd, timeout=0):
        captured["cmd"] = cmd
        return "", "", 1  # fail fast — command capture is the point

    with mock.patch.object(nmap_runner, "check_nmap", return_value=True), \
         mock.patch.object(nmap_runner, "_run", side_effect=fake_run):
        nmap_runner.discover("192.0.2.0/24", use_sudo=True, timeout=5)
    assert captured["cmd"][0] == "sudo"
    assert captured["cmd"][1] == "nmap"


def test_portscan_prepends_sudo():
    captured = {}

    def fake_run(cmd, timeout=0):
        captured["cmd"] = cmd
        return "", "", 1

    with mock.patch.object(nmap_runner, "check_nmap", return_value=True), \
         mock.patch.object(nmap_runner, "_run", side_effect=fake_run):
        nmap_runner.portscan(["192.0.2.10"], use_sudo=True, timeout=5)
    assert captured["cmd"][0] == "sudo"
    assert captured["cmd"][1] == "nmap"
