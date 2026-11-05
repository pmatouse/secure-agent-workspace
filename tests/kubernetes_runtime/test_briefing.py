"""Compile the same Helm-rendered personal-assistant BOM as the VM."""
import base64
import json
from pathlib import Path
import subprocess

import pytest
import yaml

from saw_kubernetes import compile_profile_files, ContractError
from saw_kubernetes.core import shared
from saw_kubernetes.harness import read_bundles
from saw_kubernetes.prepare_gate import publish_harness

ROOT = Path(__file__).resolve().parents[2]
IMAGE = "ghcr.io/validatedpatterns-sandbox/nemoclaw-sandbox@sha256:28457eec59e71eca310cd72fc4b57c71506c3fce4c30f2636a237dca85725dbd"


def briefing_inputs():
    manifests = subprocess.check_output(["helm", "template", "fixture", str(ROOT/"charts/saw-bom"),
        "--set", "profiles[0]=personal-assistant", "--set", "harnessEnabled=true",
        "--set-string", "imageOverrides.assistant="+IMAGE], text=True)
    files = yaml.safe_load(manifests)["data"]
    docs, raw, index = shared.split_bom_files(files)
    bundle = read_bundles(raw, index)["daily-briefing"]
    owner = "fixture"
    def pvc(name, ro):
        return {"claimName": name, "uid": "test-"+name, "readOnly": ro}
    # Public SPKI for a fixture writer. No signing or provider key in the test.
    key = base64.b64encode(bytes.fromhex("302a300506032b6570032100")+bytes(range(32))).decode()
    slot = {"workspace": pvc("workspace-fixture",False), "browser":{"origin":"https://fixture.example","ownerLogin":owner},
            "toolGate":{"receiptKey":key,"ownerLogin":owner,"trusted":pvc("saw-gate-fixture",True),
                        "audit":pvc("saw-audit-fixture",False),"harness":{"name":bundle.name,"digest":bundle.digest}}}
    ws, = shared.parse_profiles(docs)[0].workspaces
    bindings = [{"secret":p.credential_secret,"key":p.credential_secret_key,"type":p.type,
                 "refresh": bool(p.refresh_strategy)} for p in ws.providers if p.enabled]
    cfg = dict(ownerID="b032b2e4-2cd5-47a7-8ef8-ac73e15700b1",namespace="saw-fixture",
               namespaceUID="fixture-ns",ownerSubject="fixture-subject",mode="container",gatewayVersion="0.1.2-rhaiv.6",
               approvedCredentialFreeProviders=[],proxyBindings=bindings,bindings={"personal-assistant/assistant":slot})
    return files, cfg


def test_briefing_plan_and_volume(tmp_path):
    files, cfg = briefing_inputs()
    plan = compile_profile_files(files, cfg)
    ws, = plan["workspaces"]
    sb, = ws["sandboxes"]
    spec = sb["spec"]
    assert {p["type"]:p["credentials"] for p in ws["providers"]} == {
        "gmail":{"GMAIL_ACCESS_TOKEN":"saw-cred.gmail.access_token"},
        "slack":{"SLACK_BOT_TOKEN":"saw-cred.slack.bot_token"},
        "nvidia":{"NVIDIA_API_KEY":"saw-cred.inference.api_key"}}
    mount, = [m for m in spec["template"]["driver_config"]["kubernetes"]["containers"]["agent"]["volume_mounts"]
              if m["mount_path"]=="/sandbox/harness"]
    assert mount["read_only"] and mount["name"]=="saw-gate"
    bom=tmp_path/"bom"; gate=tmp_path/"gate"; bom.mkdir(); gate.mkdir()
    for k,v in files.items(): (bom/k).write_text(v)
    pin="sha256:"+mount["sub_path"].removeprefix("harness-")
    for _ in range(2): publish_harness(gate,bom,"daily-briefing",pin)
    path=gate/mount["sub_path"]/"mcp/slack-reader.mjs"
    assert path.read_bytes()==(ROOT/"harness-bundles/daily-briefing/mcp/slack-reader.mjs").read_bytes()
    path.chmod(0o600); path.write_text("tampered")
    with pytest.raises(ValueError): publish_harness(gate,bom,"daily-briefing",pin)


@pytest.mark.parametrize("fault", ["missing","edited","no-approval","missing-provider","no-index"])
def test_untrusted_briefing_is_rejected(fault):
    files,cfg=briefing_inputs()
    ks=sorted(k for k in files if k.startswith("harness__") and not k.endswith("__map"))
    if fault=="missing": del files[ks[0]]
    if fault=="edited": files[ks[0]]=base64.b64encode(b"tampered").decode()
    if fault=="no-index": del files["harness-index.yaml"]
    if fault=="no-approval": del cfg["bindings"]["personal-assistant/assistant"]["toolGate"]["harness"]
    if fault=="missing-provider": cfg["proxyBindings"]=[b for b in cfg["proxyBindings"] if b["type"]!="gmail"]
    with pytest.raises(ContractError): compile_profile_files(files,cfg)
