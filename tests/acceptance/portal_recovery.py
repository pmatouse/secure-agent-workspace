#!/usr/bin/env python3
"""Fault injection for a disposable custom-inference RHDH registration."""
import argparse
import json
import re
import subprocess
import time
from uuid import uuid5, NAMESPACE_URL


def oc(*args, stdin=None):
    return subprocess.check_output(["oc", "--request-timeout=25s", *args], input=stdin, text=True, timeout=35)


def get(ns, kind, name):
    return json.loads(oc("-n", ns, "get", kind, name, "-o", "json"))


def owner_ref(obj):
    ref, = [r for r in obj["metadata"]["ownerReferences"] if r.get("controller")]
    return ref


def wait(fn, seconds=900):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        value = fn()
        if value:
            return value
        time.sleep(3)
    raise TimeoutError("expected recovery state was not reached")


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("fault", choices=["enrollment", "controller"])
    cli.add_argument("--owner", required=True)
    cli.add_argument("--registration", required=True)
    cli.add_argument("--api-server", required=True, help="expected oc whoami --show-server")
    a = cli.parse_args()
    if not re.fullmatch("[a-z0-9]([-a-z0-9]{0,17}[a-z0-9])?", a.owner) or not re.fullmatch("[0-9a-f]{16}", a.registration):
        cli.error("invalid owner or registration")
    runtime, ctl = "saw-" + a.owner, "saw-ctl-" + a.registration
    identity = str(uuid5(NAMESPACE_URL, "urn:saw:portal:" + a.owner + ":" + a.registration))

    def guard():
        if oc("whoami", "--show-server").strip() != a.api_server:
            raise RuntimeError("unexpected cluster")
        entry = json.loads(get("saw-portal", "cm", "saw-ws-" + a.owner)["data"]["user.json"])
        if (entry["name"] != a.owner or entry["profiles"] != ["custom-inference"] or
                entry["values"]["deployment"]["mode"] != "container" or entry["intentGeneration"] != 1 or
                not entry["vaultPrefix"].endswith("/" + runtime + "/" + a.registration)):
            raise RuntimeError("refusing a different registration or generation")
        labels = get(ctl, "namespace", ctl)["metadata"]["labels"]
        if labels.get("saw.redhat.com/runtime-owner") != identity or labels.get("saw.redhat.com/registration") != a.registration:
            raise RuntimeError("unexpected namespace identity")

    def candidates():
        label = ("app=enroll-" + a.registration if a.fault == "enrollment" else
                 "app.kubernetes.io/instance=" + a.owner + ",openshell.pattern/role=reconciler")
        return [p for p in json.loads(oc("-n", ctl, "get", "pods", "-l", label, "-o", "json"))["items"]
                if not p["metadata"].get("deletionTimestamp")]

    def running():
        items = candidates()
        if a.fault == "enrollment" and any(p["status"]["phase"] == "Succeeded" for p in items):
            raise RuntimeError("enrollment already completed; no Pod was interrupted")
        pods = [p for p in items if p["status"]["phase"] == "Running"]
        return pods[0] if len(pods) == 1 else None

    def ledger(pod):
        # Report identities and a write timestamp, never provider material.
        cmd = """import json
from pathlib import Path
p=Path('/state/core/state.json')
print(json.dumps({'ids':json.loads(p.read_text())['objectIDs'],'written':p.stat().st_mtime_ns}))"""
        return json.loads(oc("-n", ctl, "exec", pod, "--", "python3", "-c", cmd))

    def status():
        obj = get(runtime, "cm", "saw-runtime-status")
        return json.loads(obj.get("data", {}).get("status.json", "{}"))

    def retained():
        objects = [(ctl, "pvc", "portal-ledger"), (ctl, "cm", "saw-portal-enrollment"),
                   (runtime, "pod", "default--notebook"), (runtime, "pod", a.owner + "-gateway-0")]
        claims = json.loads(oc("-n", runtime, "get", "pvc", "-o", "json"))["items"]
        objects.extend((runtime, "pvc", c["metadata"]["name"]) for c in claims)
        return {f"{ns}/{kind}/{name}":get(ns, kind, name)["metadata"]["uid"] for ns,kind,name in objects}

    if a.fault == "enrollment":
        wait(lambda: oc("get", "namespace", ctl, "--ignore-not-found", "-o", "name").strip())
    guard()
    if a.fault == "controller":
        if status().get("phase") != "GenericReady":
            raise RuntimeError("wait for GenericReady before testing controller recovery")
        pins = retained()
    pod = wait(running)
    meta = pod["metadata"]
    parent = owner_ref(pod)
    job = "enroll-" + a.registration + "-"
    if a.fault == "enrollment":
        if (parent["kind"] != "Job" or not parent["name"].startswith(job) or
                get(ctl,"job",parent["name"])["metadata"]["uid"] != parent["uid"] or
                get(ctl,"cm","saw-portal-enrollment").get("data",{}).get("binding.json")):
            raise RuntimeError("enrollment already published or unexpected Job")
    else:
        deployment = get(ctl, "deploy", a.owner + "-reconciler")
        rs = get(ctl, "rs", parent["name"])
        if (parent["kind"] != "ReplicaSet" or parent["uid"] != rs["metadata"]["uid"]
                or owner_ref(rs)["uid"] != deployment["metadata"]["uid"]):
            raise RuntimeError("unexpected controller owner chain")
        before = ledger(meta["name"])
        if not any(k.startswith("sandbox/") for k in before["ids"]):
            raise RuntimeError("no enrolled sandbox identity")
    guard()
    delete = {"apiVersion":"v1","kind":"DeleteOptions","preconditions":{"uid":meta["uid"]}}
    oc("delete","--raw",f"/api/v1/namespaces/{ctl}/pods/{meta['name']}","-f","-",stdin=json.dumps(delete))
    evidence = {"fault":a.fault,"registration":a.registration,"oldPodUID":meta["uid"]}
    if a.fault == "controller":
        evidence.update(retainedUIDs=pins, openShellIDs=before["ids"])
    print(json.dumps(evidence), flush=True)

    def recovered():
        for p in candidates():
            if p["metadata"]["uid"] == meta["uid"] or owner_ref(p)["uid"] != parent["uid"]:
                continue
            if a.fault == "enrollment":
                if p["status"]["phase"] == "Succeeded":
                    cm = get(ctl,"cm","saw-portal-enrollment")
                    if cm.get("immutable") and json.loads(cm["data"]["binding.json"])["registration"] == a.registration:
                        return p["metadata"]["uid"]
            elif p["status"]["phase"] == "Running" and all(c["ready"] for c in p["status"].get("containerStatuses", []) or [{"ready":False}]):
                try:
                    after = ledger(p["metadata"]["name"])
                except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                    # The kubelet exec endpoint can lag the replacement Pod status.
                    return None
                # Require new core writes AFTER observing the replacement, to rule out stale status.
                if after["ids"] != before["ids"]:
                    raise RuntimeError("OpenShell object identity drift")
                first = after["written"]
                wait(lambda: ledger(p["metadata"]["name"])["written"] > first, seconds=150)
                if status().get("phase") != "GenericReady" or retained() != pins or ledger(p["metadata"]["name"])["ids"] != before["ids"]:
                    raise RuntimeError("post-restart reconciliation or storage identity check failed")
                return p["metadata"]["uid"]
        return None

    evidence["replacementPodUID"] = wait(recovered)
    guard()
    if a.fault == "controller":
        evidence["freshReconcile"] = True
    print(json.dumps(evidence,sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
