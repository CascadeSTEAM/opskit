#!/usr/bin/env python3
"""
Generate network-architecture.md from gathered Ansible facts.
Reads /tmp/*-network-facts.yml files and combines them into documentation.
"""

import os
import re
import yaml
from pathlib import Path
from datetime import datetime

REPO_ROOT = Path(__file__).parent.parent
DOCS_DIR = REPO_ROOT / 'docs'
ANSIBLE_DIR = REPO_ROOT / 'ansible'

def read_facts_file(filepath):
    """Read a network facts YAML file."""
    try:
        with open(filepath, 'r') as f:
            content = f.read()
        # Remove the comment header if present
        content = re.sub(r'^# Network Facts for .*$', '', content, flags=re.MULTILINE)
        return yaml.safe_load(content)
    except Exception as e:
        print(f"Error reading {filepath}: {e}")
        return None

def get_all_facts():
    """Get facts from all node files."""
    facts = {}
    tmp_dir = Path('/tmp')
    
    for facts_file in tmp_dir.glob('*-network-facts.yml'):
        node_name = facts_file.stem.replace('-network-facts', '')
        data = read_facts_file(facts_file)
        if data:
            facts[node_name] = data
    
    return facts

def generate_docs(facts):
    """Generate the network architecture documentation."""
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    lines = []
    lines.append(f"# Network Architecture")
    lines.append(f"")
    lines.append(f"**Auto-generated:** {now}  ")
    lines.append(f"**Source:** Ansible facts gathering  ")
    lines.append(f"")
    lines.append(f"---")
    lines.append(f"")
    
    # Core Infrastructure
    lines.append(f"## Core Infrastructure")
    lines.append(f"")
    lines.append(f"| Device | IP | Role | Notes |")
    lines.append(f"|--------|-----|------|-------|")
    lines.append(f"| MikroTik Router | 10.99.0.1 | Gateway, NAT, Firewall | Admin: `admin` |")
    lines.append(f"| Technitium DNS | 10.99.0.4 | DNS Server (LXC on Proxmox) | Authoritative + Recursive |")
    lines.append(f"| cluster-llm (LXC on frank) | 10.99.0.201 | AI Cluster Hub | NVIDIA RTX 3090 |")
    lines.append(f"")
    
    # AI Cluster Nodes
    lines.append(f"## AI Cluster Nodes")
    lines.append(f"")
    lines.append(f"| Node | IP Address | Gateway | DNS | Interface | Status |")
    lines.append(f"|------|------------|---------|-----|-----------|--------|")
    
    node_order = ['cluster-llm', 'lab1', 'lab2', 'lab3', 'lab4', 'nuk1']
    
    for node in node_order:
        if node not in facts:
            lines.append(f"| {node} | N/A | N/A | N/A | N/A | No facts gathered |")
            continue
        
        data = facts[node]
        ip = data.get('IP Address', 'N/A')
        gw = data.get('Gateway', 'N/A')
        dns = data.get('DNS Servers', 'N/A')
        intf = data.get('Interface', 'N/A')
        
        # Check if DNS is correct
        dns_status = "✅" if '10.99.0.4' in dns else "⚠️ Incorrect"
        
        lines.append(f"| {node} | {ip} | {gw} | {dns} | {intf} | {dns_status} |")
    
    lines.append(f"")
    
    # Detailed Facts
    lines.append(f"## Detailed Network Facts")
    lines.append(f"")
    
    for node in node_order:
        if node not in facts:
            continue
        
        lines.append(f"### {node}")
        lines.append(f"")
        data = facts[node]
        
        for key, value in data.items():
            if isinstance(value, dict):
                lines.append(f"**{key}:**")
                for k, v in value.items():
                    lines.append(f"  - {k}: {v}")
            elif isinstance(value, list):
                lines.append(f"**{key}:**")
                for item in value:
                    lines.append(f"  - {item}")
            else:
                lines.append(f"**{key}:** {value}")
        lines.append(f"")
    
    # Troubleshooting
    lines.append(f"## Common Issues")
    lines.append(f"")
    lines.append(f"### DNS Misconfiguration")
    lines.append(f"- **Symptom:** Nodes cannot resolve external hostnames")
    lines.append(f"- **Cause:** DNS set to `10.99.0.1` (MikroTik) instead of `10.99.0.4` (Technitium)")
    lines.append(f"- **Fix:** Run `ansible-playbook playbooks/fix-dns.yml`")
    lines.append(f"- **Verify:** `nslookup google.com` should succeed")
    lines.append(f"")
    lines.append(f"### Internet Connectivity")
    lines.append(f"- **Symptom:** Node shows as offline")
    lines.append(f"- **Check:** `ping -c 1 10.99.0.1` (gateway), `nslookup google.com` (DNS)")
    lines.append(f"- **Fix:** Verify physical connection, check MikroTik firewall rules")
    lines.append(f"")
    
    return "\n".join(lines)

def main():
    print("Generating network architecture documentation...")
    
    # Get facts
    facts = get_all_facts()
    
    if not facts:
        print("No facts files found in /tmp/-network-facts.yml")
        print("Run: ansible-playbook playbooks/gather-network-facts.yml")
        return
    
    # Generate documentation
    docs_content = generate_docs(facts)
    
    # Write to docs/
    output_file = DOCS_DIR / 'network-architecture.md'
    output_file.write_text(docs_content)
    
    print(f"✅ Documentation generated: {output_file}")
    print(f"   Nodes documented: {len(facts)}")
    
    # Git commit if in repo
    import subprocess
    try:
        subprocess.run(['git', 'add', str(output_file)], cwd=REPO_ROOT, check=True, capture_output=True)
        msg = 'Auto-update network architecture documentation'
        subprocess.run(['git', 'commit', '-m', msg], cwd=REPO_ROOT, check=True, capture_output=True)
        print(f"✅ Changes committed to git")
    except subprocess.CalledProcessError:
        print(f"⚠️  Could not commit to git (may need to commit manually)")
    except Exception as e:
        print(f"⚠️  Git error: {e}")

if __name__ == '__main__':
    main()
