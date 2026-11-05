#!/usr/bin/env python3
"""Exercise the stock OpenClaw gateway through an existing ordinary OIDC CLI login."""
import argparse
import json
from pathlib import Path
import secrets
import subprocess
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("gateway", "workspace", "sandbox", "model"):
        parser.add_argument("--" + key, required=True)
    parser.add_argument("--provider", default="openai")
    parser.add_argument("--verify-transcript", action="store_true",
                        help="correlate the fresh reply with the provider response in OpenClaw's transcript")
    args = parser.parse_args()
    # OpenShell exec is a fresh process. Point the CLI at the same private
    # configuration that the stock gateway uses inside the workspace.
    scope = ["openshell", "sandbox", "exec", "-g", args.gateway, "--workspace", args.workspace,
             "--name", args.sandbox, "--no-login-shell", "--no-tty", "--timeout", "150", "--",
             "env", "HOME=/sandbox/workspace", "OPENCLAW_HOME=/sandbox/workspace",
             "OPENCLAW_CONFIG_PATH=/sandbox/workspace/.openclaw/openclaw.json",
             "TMPDIR=/sandbox/workspace/.openclaw/state", "SQLITE_TMPDIR=/sandbox/workspace/.openclaw/state"]
    nonce = secrets.token_hex(10)
    session = "agent:main:portal-" + secrets.token_hex(8) + "-owner"
    def run(command, *, check=True):
        result = subprocess.run(scope + command, capture_output=True, text=True, timeout=160)
        if result.returncode and check:
            raise SystemExit("OpenClaw owner command failed (exit %d)" % result.returncode)
        return result
    # gateway call uses the running gateway; 'agent --local' could mask an
    # unreachable service by starting a second agent in the CLI process.
    deadline = time.monotonic() + 360
    while run(["openclaw", "gateway", "call", "health", "--timeout", "8000", "--json"], check=False).returncode:
        if time.monotonic() >= deadline:
            raise SystemExit("OpenClaw gateway did not become healthy")
        time.sleep(10)
    out = run(["openclaw", "gateway", "call", "agent", "--expect-final", "--timeout", "100000",
               "--json", "--params", json.dumps({"agentId":"main", "sessionKey":session,
               "message": "Reply with exactly " + nonce + ". Do not use tools.", "idempotencyKey":nonce})]).stdout
    data = json.loads(out[out.index("{"):])
    result = data.get("result", data)
    if not any(p.get("text", "").strip() == nonce for p in result.get("payloads", [])):
        raise SystemExit("Agent did not return the expected unique reply")
    meta = result.get("meta", {}).get("agentMeta", {})
    if meta.get("model") != args.model or meta.get("provider") != args.provider:
        raise SystemExit("Unexpected model or provider in the agent response")
    evidence = {"ownerGatewayHealth":True, "freshReplyMatched":True,
                "provider":meta["provider"], "model":meta["model"]}
    if args.verify_transcript:
        source = Path(__file__).with_name("portal_model_evidence.cjs").read_text()
        completion = json.loads(run(["node", "-e", source, nonce, session]).stdout)
        model = completion.get("responseModel") or ""
        if (completion.get("provider") != args.provider or completion.get("model") != args.model
                or not completion.get("providerResponse")
                or not (model == args.model or model.startswith(args.model + "-"))):
            raise SystemExit("Transcript does not match the requested provider and model")
        evidence["completion"] = completion
    print(json.dumps(evidence))


if __name__ == "__main__":
    main()
