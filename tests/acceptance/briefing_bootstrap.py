"""Run in the fixture init container. Only a public receipt key leaves the audit writer."""
import json
import shlex
import ssl
import time
from pathlib import Path
from urllib.request import urlopen

from saw_kubernetes import compile_profile_files
from saw_kubernetes.core import shared
from saw_kubernetes.prepare_gate import publish, publish_harness

bom = Path("/bom")
files = {p.name: p.read_text() for p in bom.iterdir() if not p.name.startswith(".")}
cfg = json.loads(Path("/checks/bindings.json").read_text())
gate = cfg["bindings"]["personal-assistant/assistant"]["toolGate"]
ctx = ssl.create_default_context(cafile="/trust/service-ca.crt")
for attempt in range(40):
    try:
        with urlopen("https://localhost:8443/v1/receipt-key", context=ctx, timeout=3) as response:
            gate["receiptKey"] = response.read(128).decode()
        break
    except OSError:
        if attempt == 39:
            raise
        time.sleep(1)
identity = shared.tool_gate_identity("fixture", cfg["ownerSubject"], "personal-assistant", "assistant")
publish_harness(Path("/volume"), bom, gate["harness"]["name"], gate["harness"]["digest"])
publish(Path("/volume"), identity, gate["receiptKey"])
spec = compile_profile_files(files, cfg)["workspaces"][0]["sandboxes"][0]["spec"]
command = spec["command"].copy()
entry = "exec openclaw gateway run --bind loopback --port 18789"
assert command[2].count(entry) == 1
command[2] = command[2].replace(entry, "exec node /checks/check.mjs")
Path("/startup/launch").write_text("exec " + shlex.join(command) + "\n")
