"""ChatGPT Desktop integration — SSH config registration."""

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from . import auth, config as cfg_mod
from .api_client import ApiClient


SSH_CONFIG = Path.home() / ".ssh" / "config"
MARKER_PREFIX = "# BEGIN codex-saw managed:"
MARKER_SUFFIX = "# END codex-saw managed:"


def _get_descriptor(session: str) -> dict:
    c = cfg_mod.load_config()
    token = auth.get_token(c["oidc"]["token_dir"], c["oidc"].get("client_id", "openshell-cli"))
    client = ApiClient(c["api_url"], token)
    return client.get_shell_info(session)


def _alias(session: str, uid: str) -> str:
    return f"saw-codex-{session}-{uid[:8]}"


def register(session: str):
    """Register an SSH host for ChatGPT Desktop."""
    desc = _get_descriptor(session)
    uid = desc.get("session_uid", "")
    alias = _alias(session, uid)

    codex_saw = shutil.which("codex-saw")
    if not codex_saw:
        codex_saw = shutil.which("python3")
        if codex_saw:
            codex_saw = f"{codex_saw} -m codex_saw"
        else:
            print("Error: codex-saw not found in PATH", file=sys.stderr)
            sys.exit(1)

    stanza = f"""{MARKER_PREFIX} {alias}
Host {alias}
    User sandbox
    ProxyCommand {codex_saw} ssh-proxy {session} --expected-session-uid {uid} --non-interactive
    ServerAliveInterval 15
    ServerAliveCountMax 3
    StrictHostKeyChecking no
    UserKnownHostsFile /dev/null
{MARKER_SUFFIX} {alias}
"""

    # Read existing config, remove old entry for this alias if present
    ssh_dir = SSH_CONFIG.parent
    ssh_dir.mkdir(mode=0o700, exist_ok=True)

    existing = SSH_CONFIG.read_text() if SSH_CONFIG.exists() else ""
    cleaned = _remove_managed_block(existing, alias)

    # Append new stanza
    if cleaned and not cleaned.endswith("\n\n"):
        cleaned = cleaned.rstrip("\n") + "\n\n"
    cleaned += stanza

    SSH_CONFIG.write_text(cleaned)
    os.chmod(SSH_CONFIG, 0o600)

    # Validate
    result = subprocess.run(
        ["ssh", "-G", alias], capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"Warning: ssh -G {alias} failed — check ~/.ssh/config", file=sys.stderr)

    print(f"SSH host '{alias}' registered.")
    print()
    print("┌─ ChatGPT Desktop Setup ─────────────────────────────")
    print("│")
    print("│  1. Open ChatGPT Desktop")
    print("│  2. Go to Settings → Connections → SSH")
    print(f"│  3. Click 'Add host' and select: {alias}")
    print("│  4. Start a new Codex project (+ button)")
    print(f"│  5. Under 'Location', pick the SSH host: {alias}")
    print("│  6. Set the project folder to: /sandbox/<your-repo>")
    print("│  7. Start coding — inference goes through the governed proxy")
    print("│")
    print("└──────────────────────────────────────────────────────")
    print()
    print(f"Or from terminal:  ssh {alias}")


def doctor(session: str):
    """Check Desktop integration health."""
    issues = []

    # Check SSH config
    desc = _get_descriptor(session)
    uid = desc.get("session_uid", "")
    alias = _alias(session, uid)

    if SSH_CONFIG.exists():
        content = SSH_CONFIG.read_text()
        if f"Host {alias}" in content:
            print(f"[OK] SSH config: {alias} registered")
        else:
            issues.append(f"SSH config: {alias} not found — run 'codex-saw desktop register {session}'")
    else:
        issues.append("SSH config: ~/.ssh/config does not exist")

    # Check proxy binary
    codex_saw = shutil.which("codex-saw")
    if codex_saw:
        print(f"[OK] Proxy binary: {codex_saw}")
    else:
        issues.append("Proxy binary: codex-saw not in PATH")

    # Check openshell
    openshell = shutil.which("openshell")
    if openshell:
        r = subprocess.run([openshell, "--version"], capture_output=True, text=True)
        print(f"[OK] OpenShell CLI: {r.stdout.strip()}")
    else:
        issues.append("OpenShell CLI: openshell not in PATH")

    # Check token
    try:
        c = cfg_mod.load_config()
        token = auth.get_token(c["oidc"]["token_dir"])
        print(f"[OK] OIDC token: valid (len={len(token)})")
    except Exception as e:
        issues.append(f"OIDC token: {e}")

    # Check session
    if desc.get("shell_ready"):
        print(f"[OK] Session: {session} shell ready")
    else:
        issues.append(f"Session: {session} shell not ready")

    # Test SSH connectivity
    result = subprocess.run(
        ["ssh", "-o", "ConnectTimeout=10", alias, "echo", "ok"],
        capture_output=True, text=True, timeout=15,
    )
    if result.returncode == 0 and "ok" in result.stdout:
        print(f"[OK] SSH connectivity: working")
    else:
        issues.append(f"SSH connectivity: failed ({result.stderr.strip()[:80]})")

    if issues:
        print()
        for issue in issues:
            print(f"[!!] {issue}")
        sys.exit(1)
    else:
        print()
        print("All checks passed.")


def unregister(session: str):
    """Remove SSH host registration."""
    if not SSH_CONFIG.exists():
        print("No ~/.ssh/config found", file=sys.stderr)
        return

    content = SSH_CONFIG.read_text()

    # Find all managed aliases for this session
    pattern = re.compile(rf"saw-codex-{re.escape(session)}-[a-f0-9]{{8}}")
    aliases = set(pattern.findall(content))

    if not aliases:
        print(f"No managed SSH entries found for session '{session}'")
        return

    for alias in aliases:
        content = _remove_managed_block(content, alias)
        print(f"Removed SSH host '{alias}'")

    SSH_CONFIG.write_text(content)


def _remove_managed_block(content: str, alias: str) -> str:
    """Remove a managed SSH config block by alias."""
    begin = f"{MARKER_PREFIX} {alias}"
    end = f"{MARKER_SUFFIX} {alias}"
    lines = content.split("\n")
    result = []
    skip = False
    for line in lines:
        if line.strip() == begin:
            skip = True
            continue
        if line.strip() == end:
            skip = False
            continue
        if not skip:
            result.append(line)
    return "\n".join(result)
