"""Registration bootstrap: compare reviewed configuration, then publish public, fenced runtime inputs."""
import json
import os
import ssl
import time
import urllib.request as h
from pathlib import Path
from saw_kubernetes.adapters import KubernetesResourceVerifier
from saw_kubernetes.audit import capture
from saw_kubernetes.compiler import compile_profile_files, digest
from saw_kubernetes.intent import build_intent
from portal_contract import verify_contract
from receipt import receipt_key

S=Path("/var/run/secrets/kubernetes.io/serviceaccount")
class NoRedirect(h.HTTPRedirectHandler):
    def redirect_request(self,*args): raise ValueError("redirect")
client=h.build_opener(h.ProxyHandler({}),NoRedirect(),h.HTTPSHandler(context=ssl.create_default_context(cafile=str(S/"ca.crt"))))
def api(path, patch=None):
    req=h.Request("https://kubernetes.default.svc"+path,method="PATCH" if patch is not None else "GET",
        headers={"Authorization":"Bearer "+(S/"token").read_text().strip(),"Content-Type":"application/merge-patch+json"},data=json.dumps(patch).encode() if patch is not None else None)
    with client.open(req,timeout=9) as response:return json.load(response)

def once(x):
    u,r,sub,ident=x["user"],x["registration"],x["subject"],x["installation"]
    ns,t,hist="saw-"+u,"saw-ctl-"+r,"saw-history-"+r
    def obj(kind,name,namespace=ns):
        if kind=="namespace":return api("/api/v1/namespaces/"+name)
        plural={"persistentvolumeclaim":"persistentvolumeclaims","configmap":"configmaps"}[kind]
        return api("/api/v1/namespaces/"+namespace+"/"+plural+"/"+name)
    nsobj=obj("namespace",ns)["metadata"]
    if nsobj["labels"].get("saw.redhat.com/runtime-owner")!=ident or nsobj.get("deletionTimestamp"):raise ValueError("namespace ownership")
    cfg=dict(namespace=ns,namespaceUID=nsobj["uid"],ownerID=ident,mode="container",trustedNamespace=t,
             governanceNamespace=x["governance"],gateway=u,proxyPolicy=u+"-proxy-policy")
    cache={}
    def get(p):
        if p not in cache:cache[p]=api(p)
        return cache[p]
    approved=capture(cfg,get)["approved"]
    verify_contract(cfg,get,x["reference"])
    profile=obj("configmap","saw-bom-profiles")
    if digest(profile["data"])!=x["profileSHA256"]:raise ValueError("unapproved BOM")
    def pvc(name,ro):
        return dict(claimName=name,uid=obj("persistentvolumeclaim",name)["metadata"]["uid"],readOnly=ro)
    slot={"workspace":pvc("workspace-"+u,False),"toolGate":{"ownerLogin":u,"receiptKey":receipt_key(u,hist,"/writer-ca/service-ca.crt"),
          "trusted":pvc("saw-gate-"+u,True),"audit":pvc("saw-audit-"+u,False)},
          "resources":x["resources"],"browser":{"ownerLogin":u,"origin":"https://"+u+"-agent-audited-ui.apps."+x["domain"]}}
    bindings=dict(ownerID=ident,namespace=ns,namespaceUID=nsobj["uid"],ownerSubject=sub,mode="container",
       gatewayVersion="0.1.2-rhaiv.6",openAIProxySecret="inference",approvedCredentialFreeProviders=[],bindings={"agent/audited":slot})
    plan=compile_profile_files(profile["data"],bindings)
    KubernetesResourceVerifier(obj,lambda _:None)(plan)  # same snapshot verified above
    intent=json.loads(build_intent(profile,bindings,name="saw-runtime-intent",generation=1,pin_plan=True)["data"]["intent.json"])
    public_ca=Path("/gateway-ca/ca.crt").read_text()
    ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT).load_verify_locations(cadata=public_ca)
    result=json.dumps(dict(registration=r,approved=approved,intent=intent,gatewayCA=public_ca),sort_keys=True)
    path=f"/api/v1/namespaces/{t}/configmaps/saw-portal-enrollment"
    current=api(path)
    if current["metadata"]["labels"].get("saw.redhat.com/runtime-owner")!=ident:raise ValueError("publication ownership")
    if current.get("data",{}).get("binding.json",result)!=result:raise ValueError("existing enrollment differs")
    # Immutable after publication. Neither the tenant nor the portal has write access.
    api(path,{"metadata":{"resourceVersion":current["metadata"]["resourceVersion"]},"immutable":True,"data":{"binding.json":result}})
    print("Published reviewed registration "+r,flush=True)

if __name__=="__main__":
    x=json.loads(Path("/bootstrap/config.json").read_text())
    for n in range(100):
        try:once(x);break
        except Exception as exc:
            # Never log an API body, credential, or other input.
            print("Waiting for reviewed inputs: "+type(exc).__name__+(" "+str(exc)[:120] if type(exc).__name__=="BoundaryError" else ""),flush=True)
            if n==99:raise SystemExit(1)
            time.sleep(5)

