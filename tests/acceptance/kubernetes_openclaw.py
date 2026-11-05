#!/usr/bin/env python3
"""Exercise the stock OpenClaw gateway through an existing ordinary OIDC CLI login."""
import argparse
import json
import secrets
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("gateway", "workspace", "sandbox", "model"):
        parser.add_argument("--" + key, required=True)
    args = parser.parse_args()
    # OpenShell exec is a fresh process. Point the CLI at the same private
    # configuration that the stock gateway uses inside the workspace.
    scope = ["openshell", "sandbox", "exec", "-g", args.gateway, "--workspace", args.workspace,
             "--name", args.sandbox, "--no-login-shell", "--no-tty", "--timeout", "150", "--",
             "env", "HOME=/sandbox/workspace", "OPENCLAW_HOME=/sandbox/workspace",
             "OPENCLAW_CONFIG_PATH=/sandbox/workspace/.openclaw/openclaw.json",
             "TMPDIR=/sandbox/workspace/.openclaw/state", "SQLITE_TMPDIR=/sandbox/workspace/.openclaw/state"]
    nonce = "SAW_" + secrets.token_hex(8)
    def run(command):
        result = subprocess.run(scope + command, capture_output=True, text=True, timeout=160)
        if result.returncode:
            raise SystemExit("OpenClaw owner command failed (exit %d)" % result.returncode)
        return result.stdout
    # gateway call uses the running gateway; 'agent --local' could mask an
    # unreachable service by starting a second agent in the CLI process.
    run(["openclaw", "gateway", "call", "health", "--json"])
    out = run(["openclaw", "gateway", "call", "agent", "--expect-final", "--timeout", "100000",
               "--json", "--params", json.dumps({"agentId":"main", "sessionKey":"agent:main:saw-" + nonce,
               "message": "Reply with exactly " + nonce + ". Do not use tools.", "idempotencyKey":nonce})])
    data = json.loads(out[out.index("{"):])
    result = data.get("result", data)
    if not any(p.get("text", "").strip() == nonce for p in result.get("payloads", [])):
        raise SystemExit("Agent did not return the expected unique reply")
    meta = result.get("meta", {}).get("agentMeta", {})
    if meta.get("model") != args.model or meta.get("provider") != "openai":
        raise SystemExit("Unexpected model or provider in the agent response")
    print(json.dumps({"ownerGatewayHealth":True, "freshReplyMatched":True,
                      "provider":meta["provider"], "model":meta["model"]}))


if __name__ == "__main__":
    main()
