"""SSH proxy and config generation for SAW sessions."""

import os
import shutil
import subprocess
import sys

from . import auth, config as cfg_mod
from .api_client import ApiClient
from .openshell_adapter import GatewayConfig


def _get_token():
    """Get an access token using the stored config."""
    c = cfg_mod.load_config()
    return auth.get_token(
        token_dir=c["oidc"]["token_dir"],
        client_id=c["oidc"].get("client_id", "openshell-cli"),
        issuer=c["oidc"].get("issuer_url"),
    )


def _get_client():
    """Get an authenticated API client."""
    c = cfg_mod.load_config()
    token = _get_token()
    return ApiClient(c["api_url"], token), token


def _login_interactive() -> tuple:
    """Attempt interactive browser login, return (client, token) or exit."""
    c = cfg_mod.load_config()
    print("codex-saw: opening browser for login...", file=sys.stderr)
    token = auth.browser_login(
        c["oidc"].get("issuer_url", ""),
        c["oidc"].get("client_id", "openshell-cli"),
        c["oidc"]["token_dir"],
    )
    if not token:
        print("codex-saw: login failed", file=sys.stderr)
        sys.exit(1)
    return ApiClient(c["api_url"], token), token


def _get_descriptor(client, token, session: str, interactive: bool):
    """Get shell descriptor, retry with login on 401 if interactive."""
    try:
        return client.get_shell_info(session), client, token
    except Exception as e:
        msg = str(e)
        if "401" in msg and interactive:
            print("codex-saw: token expired, re-authenticating...", file=sys.stderr)
            client, token = _login_interactive()
            return client.get_shell_info(session), client, token
        elif "401" in msg:
            print("codex-saw: session expired — run 'codex-saw' and log in again", file=sys.stderr)
        elif "403" in msg:
            print(f"codex-saw: access denied to session '{session}'", file=sys.stderr)
        elif "404" in msg:
            print(f"codex-saw: session '{session}' not found", file=sys.stderr)
        elif "503" in msg:
            print(f"codex-saw: session '{session}' not ready for shell access", file=sys.stderr)
        else:
            print(f"codex-saw: {msg}", file=sys.stderr)
        sys.exit(1)


def ssh_proxy(
    session: str,
    expected_uid: str | None = None,
    non_interactive: bool = False,
):
    """Run as an SSH ProxyCommand — connects stdin/stdout to the sandbox shell.

    All diagnostics go to stderr. stdout is clean for SSH transport.
    """
    interactive = not non_interactive

    try:
        client, token = _get_client()
    except Exception:
        if non_interactive:
            print("codex-saw: login required — run 'codex-saw' to authenticate", file=sys.stderr)
            sys.exit(1)
        client, token = _login_interactive()

    descriptor, client, token = _get_descriptor(client, token, session, interactive)

    if expected_uid and descriptor.get("session_uid") != expected_uid:
        print(
            f"codex-saw: session UID mismatch (expected {expected_uid[:8]}..., "
            f"got {descriptor.get('session_uid', '?')[:8]}...). "
            f"Session may have been recreated. Run 'codex-saw desktop unregister {session}' "
            f"and re-register.",
            file=sys.stderr,
        )
        sys.exit(1)

    openshell = shutil.which("openshell")
    if not openshell:
        print("codex-saw: openshell CLI not found in PATH", file=sys.stderr)
        sys.exit(1)

    with GatewayConfig(session, descriptor, token) as gw:
        env = {**os.environ, **gw.env}
        cmd = [
            openshell,
            "ssh-proxy",
            "--gateway-name", gw.gateway_name,
            "--name", "codex",
            "--workspace", "default",
        ]
        print(f"codex-saw: connecting to {session}...", file=sys.stderr)
        os.execve(openshell, cmd, env)


def generate_ssh_config(session: str) -> str:
    """Generate an SSH config stanza for a session."""
    client, token = _get_client()
    descriptor = client.get_shell_info(session)

    uid = descriptor.get("session_uid", "")
    uid_suffix = uid[:8] if uid else "unknown"
    alias = f"saw-codex-{session}-{uid_suffix}"

    codex_saw = shutil.which("codex-saw")
    if not codex_saw:
        codex_saw = "/usr/local/bin/codex-saw"

    return f"""# BEGIN codex-saw managed: {alias}
Host {alias}
    User sandbox
    ProxyCommand {codex_saw} ssh-proxy {session} --expected-session-uid {uid} --non-interactive
    ServerAliveInterval 15
    ServerAliveCountMax 3
    StrictHostKeyChecking no
    UserKnownHostsFile /dev/null
# END codex-saw managed: {alias}
"""


def shell(session: str):
    """Open an interactive shell in a sandbox."""
    try:
        client, token = _get_client()
    except Exception:
        client, token = _login_interactive()

    descriptor, client, token = _get_descriptor(client, token, session, interactive=True)

    openshell = shutil.which("openshell")
    if not openshell:
        print("codex-saw: openshell CLI not found in PATH")
        sys.exit(1)

    with GatewayConfig(session, descriptor, token) as gw:
        env = {**os.environ, **gw.env}
        cmd = [
            openshell,
            "--gateway", gw.gateway_name,
            "sandbox", "connect", "codex",
            "--workspace", "default",
        ]
        result = subprocess.run(cmd, env=env)
        sys.exit(result.returncode)
