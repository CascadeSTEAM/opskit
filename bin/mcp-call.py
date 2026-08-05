#!/usr/bin/env python3
"""Call one MCP tool from a shell, through this repo's vault-resolving launcher.

opskit #110 (ledger row 31). This repo's MCP servers expose their tools only over
MCP stdio, so a shell, a script, a playbook pre-check or CI has no way to reach
them. For RouterOS that turns a hard rule into a trap: AGENTS.md routes all
RouterOS work through mikromcp, whose CLI offers only serve/doctor/init/update —
so from a shell the only options left are the raw REST and SSH the same document
forbids. A rule with no reachable compliant path gets broken.

Servers are launched with `bin/mcp-run.sh`, deliberately: a shell call and an
agent call then resolve the same credentials against the same config. A second
launch path would drift from the first, which is the class of defect #80 and #105
were both about.

Usage:
  bin/mcp-call.py --servers                     # what can be called
  bin/mcp-call.py <server> --list               # that server's tools
  bin/mcp-call.py <server> <tool>               # call with no arguments
  bin/mcp-call.py <server> <tool> '<json>'      # call with arguments
  bin/mcp-call.py <server> <tool> --arg k=v ... # same, without quoting JSON
  bin/mcp-call.py <server> <tool> --str k=v ... # ditto, but never coerce to JSON

Output is the tool's structured result as JSON when it has one, otherwise its
text content. --raw prints the whole MCP response envelope.

Requires an unlocked vault session for servers with mapped secrets:
  export BW_SESSION=$(bw unlock --raw)
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

REPO_ROOT = Path(os.environ.get("OPSKIT_ROOT", Path(__file__).resolve().parent.parent))
MCP_RUN = REPO_ROOT / "bin" / "mcp-run.sh"

PROTOCOL_VERSION = "2024-11-05"
DEFAULT_TIMEOUT = 120


class McpError(RuntimeError):
    pass


class StdioClient:
    """The smallest MCP client that can list and call tools.

    Only the three messages that matter are implemented — initialize, tools/list,
    tools/call. Anything else the server sends (log notifications, progress) is
    skipped rather than parsed, so a chatty server cannot break the call.
    """

    def __init__(self, argv: list[str], timeout: int = DEFAULT_TIMEOUT):
        self.timeout = timeout
        self._next_id = 0
        self.proc = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1,
        )
        # Drain stderr on a thread. A server that logs heavily to stderr will
        # otherwise fill the pipe buffer and deadlock, which looks exactly like
        # the silent hang this tool exists to make debuggable.
        self.stderr_tail: list[str] = []
        self._stderr_thread = threading.Thread(target=self._drain_stderr, daemon=True)
        self._stderr_thread.start()

    def _drain_stderr(self) -> None:
        assert self.proc.stderr is not None
        for line in self.proc.stderr:
            self.stderr_tail.append(line.rstrip())
            del self.stderr_tail[:-40]

    def _send(self, payload: dict) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.write(json.dumps(payload) + "\n")
        self.proc.stdin.flush()

    def _read_response(self, req_id: int) -> dict:
        assert self.proc.stdout is not None
        while True:
            line = self.proc.stdout.readline()
            if not line:
                raise McpError(
                    "the server exited without responding.\n"
                    + self._stderr_report()
                )
            line = line.strip()
            if not line.startswith("{"):
                continue  # not JSON-RPC — a banner or stray log line
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if msg.get("id") == req_id:
                return msg
            # Notifications and unrelated ids are not ours; keep reading.

    def _stderr_report(self) -> str:
        if not self.stderr_tail:
            return "The server printed nothing to stderr."
        return "Server stderr (last lines):\n  " + "\n  ".join(self.stderr_tail[-15:])

    def request(self, method: str, params: dict) -> dict:
        self._next_id += 1
        req_id = self._next_id
        self._send({"jsonrpc": "2.0", "id": req_id, "method": method, "params": params})
        msg = self._read_response(req_id)
        if "error" in msg:
            err = msg["error"]
            raise McpError(f"{method} failed: {err.get('message')} "
                           f"(code {err.get('code')})")
        return msg.get("result", {})

    def initialize(self) -> None:
        self.request("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "opskit-mcp-call", "version": "1.0"},
        })
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def close(self) -> None:
        try:
            if self.proc.stdin:
                self.proc.stdin.close()
            self.proc.terminate()
            self.proc.wait(timeout=5)
        except Exception:
            self.proc.kill()


def known_servers() -> list[str]:
    result = subprocess.run(["bash", str(MCP_RUN), "--list"],
                            capture_output=True, text=True)
    return result.stdout.split()


def _split_pair(flag: str, pair: str) -> tuple[str, str]:
    if "=" not in pair:
        raise McpError(f"{flag} expects key=value, got '{pair}'")
    key, value = pair.split("=", 1)
    return key, value


def parse_arguments(raw_json: str | None, pairs: list[str],
                    str_pairs: list[str] | None = None) -> dict:
    """--arg k=v is the ergonomic path; a JSON blob is the complete one.

    --arg coerces JSON scalars, so `count=4` is a number and `flag=true` a
    boolean. That bites on identifiers which are digits but are typed as
    strings: a ticket id of 68 became an int and the server rejected it on this
    tool's very first real call. --str is the escape hatch, and it never coerces.
    """
    args: dict = {}
    if raw_json:
        try:
            args = json.loads(raw_json)
        except json.JSONDecodeError as exc:
            raise McpError(f"arguments are not valid JSON: {exc}") from exc
        if not isinstance(args, dict):
            raise McpError("arguments must be a JSON object")
    for pair in pairs:
        key, value = _split_pair("--arg", pair)
        # Real JSON scalars pass through; a bare word stays a string, so
        # routerId=crs326 does not become an error.
        try:
            args[key] = json.loads(value)
        except json.JSONDecodeError:
            args[key] = value
    for pair in str_pairs or []:
        key, value = _split_pair("--str", pair)
        args[key] = value
    return args


def render(result: dict, raw: bool) -> str:
    if raw:
        return json.dumps(result, indent=2)
    if result.get("structuredContent") is not None:
        return json.dumps(result["structuredContent"], indent=2)
    texts = [c.get("text", "") for c in result.get("content", [])
             if c.get("type") == "text"]
    if texts:
        return "\n".join(texts)
    return json.dumps(result, indent=2)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("server", nargs="?", help="server name (see --servers)")
    ap.add_argument("tool", nargs="?", help="tool name (see --list)")
    ap.add_argument("arguments", nargs="?", help="tool arguments as a JSON object")
    ap.add_argument("--arg", action="append", default=[], metavar="KEY=VALUE",
                    help="a single argument; JSON scalars are coerced "
                         "(count=4 is a number). Repeatable, merged over the JSON")
    ap.add_argument("--str", action="append", default=[], dest="str_arg",
                    metavar="KEY=VALUE",
                    help="a single argument kept as a string, never coerced — "
                         "use for ids that look numeric (ticket_id=68)")
    ap.add_argument("--list", action="store_true", help="list the server's tools")
    ap.add_argument("--servers", action="store_true", help="list callable servers")
    ap.add_argument("--raw", action="store_true", help="print the whole MCP response")
    ap.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    args = ap.parse_args()

    if args.servers:
        print("\n".join(known_servers()))
        return 0

    if not args.server:
        ap.print_usage(sys.stderr)
        print("\nerror: a server is required (see --servers)", file=sys.stderr)
        return 2

    servers = known_servers()
    if servers and args.server not in servers:
        print(f"error: unknown server '{args.server}' — available: "
              f"{', '.join(servers)}", file=sys.stderr)
        return 2

    if not args.list and not args.tool:
        print(f"error: a tool is required — list them with: "
              f"bin/mcp-call.py {args.server} --list", file=sys.stderr)
        return 2

    client = StdioClient(["bash", str(MCP_RUN), args.server], timeout=args.timeout)
    try:
        client.initialize()

        if args.list:
            tools = client.request("tools/list", {}).get("tools", [])
            for tool in sorted(tools, key=lambda t: t["name"]):
                desc = (tool.get("description") or "").split("\n")[0]
                print(f"{tool['name']}\t{desc}")
            return 0

        tool_args = parse_arguments(args.arguments, args.arg, args.str_arg)
        result = client.request(
            "tools/call", {"name": args.tool, "arguments": tool_args})

        print(render(result, args.raw))
        # A tool that reports failure in-band must not look like success to a
        # script; isError is how MCP says "this ran and went wrong".
        return 1 if result.get("isError") else 0
    except McpError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(main())
