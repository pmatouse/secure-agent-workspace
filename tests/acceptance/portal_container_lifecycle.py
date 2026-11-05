#!/usr/bin/env python3
"""Destructive only to the new registration created by this invocation. Requires oc and operator test access."""
import argparse
import json
from pathlib import Path
import re
import secrets
import subprocess
import sys
import time

HERE=Path(__file__).resolve().parent

def run(*args, stdin=None):
    return subprocess.check_output(args,input=stdin,text=True,timeout=240).strip()

def eventually(fn, label, seconds=1200):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        value=fn()
        if value:return value
        time.sleep(6)
    raise TimeoutError(label)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for k in ("user","portal","issuer","domain","openclaw-version","password-file","key-file"):
        p.add_argument("--"+k,required=True)
    p.add_argument("--resume-create",nargs=2,metavar=("TASK_UUID","REGISTRATION"),help="resume observation of this exact owner registration after a client interruption")
    a=p.parse_args()
    if not re.fullmatch(r"[a-z0-9]([-a-z0-9]{0,17}[a-z0-9])?",a.user) or not re.fullmatch(r"[a-z0-9.-]+",a.domain):
        p.error("explicit owner and cluster domain required")
    if not a.portal.startswith("https://") or not a.issuer.startswith("https://"):p.error("HTTPS required")
    pw=Path(a.password_file).read_text().strip()+"\n"
    ns="saw-"+a.user
    def get(kind,name,namespace=None):
        args=["oc","get",kind,name,"--ignore-not-found","--request-timeout=15s","-o","json"]
        if namespace:args+=["-n",namespace]
        raw=run(*args)
        return json.loads(raw) if raw else {}
    def reg():
        d=get("cm","saw-ws-"+a.user,"saw-portal").get("data",{})
        return json.loads(d.get("user.json","{}"))
    if get("ingress.config.openshift.io","cluster").get("spec",{}).get("domain") != "apps."+a.domain:
        raise RuntimeError("current oc context does not match the requested application domain")
    if a.resume_create:
        task_id,expected=a.resume_create
        if not re.fullmatch("[a-f0-9-]{36}",task_id) or not re.fullmatch("[a-f0-9]{16}",expected) or not reg().get("vaultPrefix","").endswith("/"+ns+"/"+expected) or reg().get("intentGeneration")!=1:
            raise RuntimeError("refusing to resume a different registration or update")
    elif reg() or get("namespace",ns):raise RuntimeError("refusing existing workspace or namespace")
    def rh(action,*more):
        return json.loads(run(sys.executable,str(HERE/"rhdh_workspace.py"),action,"--user",a.user,
            "--origin",a.portal,"--issuer",a.issuer,*more,stdin=pw))
    def done(task):
        try:state=rh("status","--task",task,"--wait","90")["status"]
        except subprocess.CalledProcessError:
            # Bounded read-only reauthentication after timeout/session loss.
            # Never repeat create/update/delete submissions.
            return False
        if state in ("failed","cancelled"):raise RuntimeError("RHDH task "+task+" "+state)
        return state=="completed"
    def submit(action):
        result=rh(action,*(["--key-file",a.key_file] if action!="delete" else []))
        print(action,result["task"],flush=True)
        eventually(lambda:done(result["task"]),action+" task",3600)
        return result["task"]
    if a.resume_create:
        eventually(lambda:done(task_id),"owner create task",1800)
        if not reg()["vaultPrefix"].endswith("/"+expected):raise RuntimeError("registration changed")
        tasks={"create":task_id}
    else:tasks={"create":submit("create")}
    registration=reg()["vaultPrefix"].rsplit("/",1)[-1]
    if not re.fullmatch("[a-f0-9]{16}",registration):raise RuntimeError("invalid registration")
    archive="saw-history-"+registration
    def runtime():
        return json.loads(get("cm","saw-runtime-status",ns)["data"]["status.json"])
    def check_generation(n):
        return runtime()["phase"]=="GenericReady" and runtime()["observedGeneration"]==n
    assert check_generation(1)
    pod="agent--audited"
    puid=get("pod",pod,ns)["metadata"]["uid"]
    claim=a.user+"-history"; uid=get("pvc",claim,archive)["metadata"]["uid"]
    writer=get("deploy",a.user+"-writer",archive)["spec"]["template"]["spec"]["containers"][0]["image"]
    folder="/sandbox/workspace/portal-"+registration[:8]
    canary=secrets.token_hex(16)
    def agent(*args):
        return run("oc","-n",ns,"exec",pod,"-c","agent","--",*args)
    agent("sh","-ec",'umask 077; mkdir "$1"; cd "$1"; printf %s "$2" >canary; touch allow-me deny-me',"fixture",folder,canary)
    origin="https://"+a.user+"-agent-audited-ui.apps."+a.domain
    prefix="agent:main:portal-"+registration[:8]+"-"
    def turn(name,prompt,*extra):
        return run(sys.executable,str(HERE/"openclaw_audit_chat.py"),"--origin",origin,"--issuer",a.issuer,
            "--user",a.user,"--version",a.openclaw_version,"--session",prefix+name,"--prompt",prompt,*extra,stdin=pw)
    print(turn("read","Use the read tool to read "+folder+"/canary and reply with the exact contents.","--contains",canary))
    for name,decision,file in (("deny","deny","deny-me"),("approve","allow-once","allow-me")):
        print(turn(name,"I confirm this disposable test. Invoke the exec tool now with exactly rm "+folder+"/"+file+" and let the tool approval dialog decide. If denied, stop.","--decision",decision,"--confirm-fixture-once"))
    def files():
        agent("sh","-ec",'test -f "$1/deny-me" && test ! -e "$1/allow-me" && test "$(cat "$1/canary")" = "$2"',"verify",folder,canary)
    files()
    source=(HERE/"portal_audit_evidence.cjs").read_text()
    def evidence():return json.loads(run("oc","-n",archive,"exec","-i","deploy/"+a.user+"-writer","--","node","-",prefix,stdin=source))
    before=evidence()
    tasks["update"]=submit("update")
    assert reg()["vaultPrefix"].endswith("/"+registration) and check_generation(2)
    assert get("pod",pod,ns)["metadata"]["uid"]==puid and get("pvc",claim,archive)["metadata"]["uid"]==uid
    files()
    assert evidence()==before
    if not reg()["vaultPrefix"].endswith("/"+registration):raise RuntimeError("registration changed before delete")
    tasks["delete"]=submit("delete")
    assert not reg() and all(not get("namespace",n) for n in (ns,"saw-ctl-"+registration,"saw-ui-"+registration))
    assert get("pvc",claim,archive)["metadata"]["uid"]==uid
    if not re.fullmatch(r".+@sha256:[a-f0-9]{64}",writer):raise RuntimeError("expected pinned writer image")
    inspect="verify-"+secrets.token_hex(6)
    job={"apiVersion":"batch/v1","kind":"Job","metadata":{"name":inspect,"namespace":archive},"spec":{"backoffLimit":0,"ttlSecondsAfterFinished":120,"activeDeadlineSeconds":180,"template":{"spec":{"restartPolicy":"Never","automountServiceAccountToken":False,"securityContext":{"runAsNonRoot":True,"seccompProfile":{"type":"RuntimeDefault"}},"containers":[{"name":"check","image":writer,"command":["node","-e",source,"audit-check",prefix],"securityContext":{"readOnlyRootFilesystem":True,"allowPrivilegeEscalation":False,"capabilities":{"drop":["ALL"]}},"volumeMounts":[{"name":"history","mountPath":"/history","readOnly":True}]}],"volumes":[{"name":"history","persistentVolumeClaim":{"claimName":claim,"readOnly":True}}]}}}}
    run("oc","create","-f","-",stdin=json.dumps(job))
    run("oc","-n",archive,"wait","--for=condition=complete","job/"+inspect,"--timeout=180s")
    assert json.loads(run("oc","-n",archive,"logs","job/"+inspect))==before
    print(json.dumps({"registration":registration,"tasks":tasks,"archiveUID":uid,"verified":before},indent=2))

if __name__=="__main__":
    if not __debug__:raise SystemExit("test assertions must be enabled")
    main()
