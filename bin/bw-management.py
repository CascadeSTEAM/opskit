#!/usr/bin/env python3
"""
Bitwarden Management Utility — used by the bitwarden skill.
Handles creation and encoding of Bitwarden items to avoid protocol errors.
"""
import json
import sys
import subprocess
import base64
import os

def run_bw(args, stdin_data=None):
    session = os.environ.get("BW_SESSION")
    if not session:
        print("ERROR: BW_SESSION environment variable not set.")
        sys.exit(1)
    
    cmd = ["bw"] + args + ["--session", session]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    stdout, stderr = proc.communicate(input=stdin_data)
    
    if proc.returncode != 0:
        print(f"FAILED: {stderr}")
        sys.exit(proc.returncode)
    return stdout

def create_item():
    try:
        data = json.load(sys.stdin)
    except Exception as e:
        print(f"ERROR: Invalid JSON input: {e}")
        sys.exit(1)
    
    # Try base64 encoding as an argument instead of piping raw JSON
    json_str = json.dumps(data)
    b64_json = base64.b64encode(json_str.encode()).decode()
    
    output = run_bw(["create", "item", b64_json])
    print(output)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: bw-management.py <command>")
        sys.exit(1)
    
    cmd = sys.argv[1]
    if cmd == "create":
        create_item()
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
