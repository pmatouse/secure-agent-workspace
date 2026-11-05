#!/usr/bin/env python3
"""Read registration-bound public evidence. Output is a candidate, not authority.

Run with the checkout's kubernetes-runtime on PYTHONPATH and an oc login.
No Secret or workload-exec permission is needed. Do not pass raw credentials.
"""
import argparse
import base64
import json
import re
import subprocess
import uuid
from saw_kubernetes.audit import capture
from saw_kubernetes.adapters import KubernetesResourceVerifier
from saw_kubernetes.compiler import compile_profile_files
from saw_kubernetes.intent import build_intent


def oc(*args):
    return subprocess.check_output(["oc",*args,"--request-timeout=20s"],text=True)
def resource(kind,name,ns):
    return json.loads(oc("get",kind,name,"-n",ns,"-o","json"))


def reject_drift():
    raise ValueError("boundary changed during collection")


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for k in ("owner","subject","registration","domain","governance-namespace","build-namespace","revision","image"):
        p.add_argument("--"+k,required=True)
    a=p.parse_args()
    u,reg=a.owner,a.registration
    if not re.fullmatch(r"[a-z0-9]([-a-z0-9]{0,17}[a-z0-9])?",u) or not re.fullmatch("[0-9a-f]{16}",reg) or not re.fullmatch("[a-f0-9]{40}",a.revision) or not re.fullmatch(r"[a-zA-Z0-9./:_-]+@sha256:[a-f0-9]{64}",a.image):
        p.error("invalid owner, registration, revision, or image")
    uid=str(uuid.uuid5(uuid.NAMESPACE_URL,"urn:saw:portal:"+u+":"+reg))
    ns,t,h="saw-"+u,"saw-ctl-"+reg,"saw-history-"+reg
    entry=json.loads(resource("cm","saw-ws-"+u,"saw-portal")["data"]["user.json"])
    assert entry["name"]==u and entry["profiles"]==["audited-openclaw"] and entry["values"]["deployment"]["mode"]=="container"
    assert entry["vaultPrefix"].endswith("/"+ns+"/"+reg)
    runtime=resource("namespace",ns,ns)["metadata"]
    assert runtime["labels"]["saw.redhat.com/runtime-owner"]==uid and not runtime.get("deletionTimestamp")
    cfg=dict(namespace=ns,namespaceUID=runtime["uid"],ownerID=uid,mode="container",trustedNamespace=t,
             governanceNamespace=a.governance_namespace,gateway=u,proxyPolicy=u+"-proxy-policy")
    approved=capture(cfg,lambda path:json.loads(oc("get","--raw",path)))["approved"]
    profile=resource("cm","saw-bom-profiles",ns)
    writer=resource("deployment",u+"-writer",h)
    assert writer["spec"]["template"]["spec"]["containers"][0]["name"]=="writer"
    # Select only this deployment's documented public-key record. Never log raw Pod logs.
    keys=set(re.findall(r"^receipt-public-key=([A-Za-z0-9+/=]+)$",oc("logs","deploy/"+u+"-writer","-n",h),re.M))
    assert len(keys)==1
    key=keys.pop()
    assert len(base64.b64decode(key,validate=True))==44 and base64.b64decode(key).startswith(bytes.fromhex("302a300506032b6570032100"))
    def pvc(name,ro):
        d=resource("pvc",name,ns)
        return {"claimName":name,"uid":d["metadata"]["uid"],"readOnly":ro}
    slot={"workspace":pvc("workspace-"+u,False),"toolGate":{"ownerLogin":u,"receiptKey":key,
          "trusted":pvc("saw-gate-"+u,True),"audit":pvc("saw-audit-"+u,False)},
          "resources":{"requests":{"cpu":"500m","memory":"1Gi"},"limits":{"cpu":"2","memory":"4Gi"}},
          "browser":{"ownerLogin":u,"origin":"https://"+u+"-agent-audited-ui.apps."+a.domain}}
    b=dict(ownerID=uid,namespace=ns,namespaceUID=runtime["uid"],ownerSubject=a.subject,mode="container",
           gatewayVersion="0.1.2-rhaiv.6",openAIProxySecret="inference",approvedCredentialFreeProviders=[],
           bindings={"agent/audited":slot})
    plan=compile_profile_files(profile["data"],b)
    def check(kind,name,namespace=None):
        return resource(kind,name,namespace or ns)
    # capture verified the boundary above; additionally verify real PVC ownership, UIDs and mount modes.
    KubernetesResourceVerifier(check,lambda _: capture(cfg,lambda path:json.loads(oc("get","--raw",path)))["approved"] == approved or reject_drift())(plan)
    intent=json.loads(build_intent(profile,b,name="saw-runtime-intent",generation=entry["intentGeneration"],pin_plan=True)["data"]["intent.json"])
    print(json.dumps(dict(registration=reg,approved=approved,intent=intent,image=a.image,
                          revision=a.revision,buildNamespace=a.build_namespace),sort_keys=True))

if __name__=="__main__":
    main()
