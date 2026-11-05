"""Render a disposable, credential-free OpenShift runtime qualification Job."""
import argparse
import base64
import json
from pathlib import Path
import re
import subprocess
import sys

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/"kubernetes-runtime"))
from saw_kubernetes.core import shared
from saw_kubernetes.harness import read_bundles

IMAGE = "ghcr.io/validatedpatterns-sandbox/nemoclaw-sandbox@sha256:28457eec59e71eca310cd72fc4b57c71506c3fce4c30f2636a237dca85725dbd"


def briefing_inputs(image=IMAGE):
    manifests = subprocess.check_output(["helm", "template", "fixture", str(ROOT/"charts/saw-bom"),
        "--set", "profiles[0]=personal-assistant", "--set", "harnessEnabled=true",
        "--set-string", "imageOverrides.assistant="+image], text=True)
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


def render(runtime_image, suffix):
    if not re.fullmatch(r"[a-z0-9-]{1,20}", suffix) or not re.fullmatch(r"[^\s]+@sha256:[0-9a-f]{64}", runtime_image):
        raise ValueError("a unique test suffix and digest-pinned runtime are required")
    name = "briefing-fixture-" + suffix
    labels = {"saw.redhat.com/fixture": name}
    meta = {"name":name, "labels":labels}
    files, cfg = briefing_inputs()
    gate = cfg["bindings"]["personal-assistant/assistant"]["toolGate"]
    restricted = {"runAsNonRoot":True,"allowPrivilegeEscalation":False,"capabilities":{"drop":["ALL"]}}
    def mount(name, path, **extra):
        return {"name":name,"mountPath":path,**extra}
    resources = [{"apiVersion":"networking.k8s.io/v1","kind":"NetworkPolicy","metadata":meta,
                  "spec":{"podSelector":{"matchLabels":labels},"policyTypes":["Ingress","Egress"],"ingress":[],"egress":[]}},
                 {"apiVersion":"v1","kind":"ConfigMap","metadata":meta,"immutable":True,"data":files},
                 {"apiVersion":"v1","kind":"ConfigMap","metadata":{**meta,"name":name+"-checks"},"immutable":True,
                  "data":{"apis.mjs":(ROOT/"tests/fixtures/briefing-apis.mjs").read_text(),
                          "check.mjs":Path(__file__).with_name("briefing_check.mjs").read_text()}}]
    checks = resources[-1]["data"]
    checks.update({"bindings.json":json.dumps(cfg), "bootstrap.py":Path(__file__).with_name("briefing_bootstrap.py").read_text(),
                   "model.mjs":Path(__file__).with_name("briefing_model.mjs").read_text()})
    for script in ("writer.mjs","forward.mjs"):
        checks[script]=(ROOT/"charts/saw-audit-writer/files"/script).read_text()
    def helper(name, image, command, mounts, **extra):
        return {"name":name,"image":image,"command":command,"securityContext":restricted,"volumeMounts":mounts,**extra}
    check_mount=mount("checks","/checks",readOnly=True)
    trust=mount("trust","/trust",readOnly=True)
    bootstrap=[helper("fixture-tls",IMAGE,["sh","-ec",
                   "umask 077; openssl req -x509 -nodes -newkey rsa:2048 -days 1 -subj /CN=localhost -addext subjectAltName=DNS:localhost -out /tls/tls.crt -keyout /tls/tls.key; cp /tls/tls.crt /trust/service-ca.crt"],
                  [mount("tls","/tls"),mount("trust","/trust")]),
               helper("writer",IMAGE,["node","/checks/writer.mjs"],[check_mount,mount("tls","/tls",readOnly=True),mount("history","/history")],
                      restartPolicy="Always",env=[{"name":"IDENTITY","value":json.dumps(shared.tool_gate_identity("fixture",cfg["ownerSubject"],"personal-assistant","assistant"))}]),
               helper("forward",IMAGE,["node","/checks/forward.mjs"],[check_mount,trust,mount("audit","/exchange")],
                      restartPolicy="Always",env=[{"name":"WRITER_URL","value":"https://localhost:8443"}]),
               helper("publish",runtime_image,["python3","/checks/bootstrap.py"],[check_mount,trust,mount("gate","/volume"),
                      mount("startup","/startup"),mount("bom","/bom",readOnly=True)])]
    pod = {"restartPolicy":"Never","automountServiceAccountToken":False,"activeDeadlineSeconds":1200,
           "securityContext":{"seccompProfile":{"type":"RuntimeDefault"}},
           "volumes":[{"name":"gate","emptyDir":{}},{"name":"audit","emptyDir":{}},{"name":"workspace","emptyDir":{}},
                      {"name":"briefing","emptyDir":{}},{"name":"bom","configMap":{"name":name}},
                      {"name":"checks","configMap":{"name":name+"-checks"}}],
           "initContainers":bootstrap,
           "containers":[{"name":"agent","image":IMAGE,"command":["sh","/startup/launch"],"securityContext":restricted,
                          "env":[{"name":k,"value":v} for k,v in {"NVIDIA_API_KEY":"fixture","SLACK_BOT_TOKEN":"slack-ph",
                                 "GMAIL_ACCESS_TOKEN":"gmail-ph","NODE_EXTRA_CA_CERTS":"/etc/ssl/certs/ca-certificates.crt","TMPDIR":"/tmp","OPENCLAW_NIX_MODE":"0"}.items()],
                          "volumeMounts":[mount("workspace","/sandbox/workspace"),mount("audit","/sandbox/.saw/audit",subPath="log"),mount("startup","/startup",readOnly=True),
                                          mount("gate","/sandbox/.saw/trusted",subPath="bundle",readOnly=True),
                                          mount("gate","/sandbox/harness",subPath="harness-"+gate["harness"]["digest"][7:],readOnly=True),
                                          mount("briefing","/sandbox/briefing"),mount("checks","/checks",readOnly=True)]}]}
    pod["volumes"].extend({"name":n,"emptyDir":{}} for n in ("tls","trust","history","startup"))
    resources.append({"apiVersion":"batch/v1","kind":"Job","metadata":meta,
                      "spec":{"backoffLimit":0,"template":{"metadata":{"labels":labels},"spec":pod}}})
    return {"apiVersion":"v1","kind":"List","items":resources}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-image", required=True)
    parser.add_argument("--suffix", required=True)
    args = parser.parse_args()
    print(json.dumps(render(args.runtime_image, args.suffix)))
