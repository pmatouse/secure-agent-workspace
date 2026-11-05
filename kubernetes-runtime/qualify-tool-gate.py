"""Render a network-isolated OpenShift hook qualification Job. Apply through Argo."""
import argparse
import hashlib
from pathlib import Path

import yaml

from saw_kubernetes.compiler import IMAGE
from saw_kubernetes.gate import projection

p = argparse.ArgumentParser(description=__doc__)
for field in ("namespace", "owner", "subject", "workspace", "sandbox", "image"):
    p.add_argument("--" + field, required=True)
args = vars(p.parse_args())
image = args.pop("image")
if not IMAGE.fullmatch(image):
    p.error("the stock OpenClaw image must be digest-pinned")
cm, volume = projection(**args)
namespace = args["namespace"]
name = "saw-gate-check-" + cm["metadata"]["name"][-12:]
source = Path(__file__).with_name("check-tool-gate.mjs").read_text()
name += "-" + hashlib.sha256((source + image).encode()).hexdigest()[:8]
meta = {"name": name, "namespace": namespace}
script = {"apiVersion": "v1", "kind": "ConfigMap", "metadata": meta, "immutable": True,
          "data": {"check.mjs": source}}
labels = {"saw.redhat.com/tool-gate-check": name}
policy = {"apiVersion": "networking.k8s.io/v1", "kind": "NetworkPolicy", "metadata": meta,
          "spec": {"podSelector": {"matchLabels": labels}, "policyTypes": ["Ingress", "Egress"]}}
job = {"apiVersion": "batch/v1", "kind": "Job", "metadata": meta,
       "spec": {"backoffLimit": 0, "activeDeadlineSeconds": 300, "template": {
           "metadata": {"labels": labels}, "spec": {
               "automountServiceAccountToken": False, "restartPolicy": "Never",
               "securityContext": {"runAsNonRoot": True, "seccompProfile": {"type": "RuntimeDefault"}},
               "volumes": [{"name": "gate", "configMap": volume},
                           {"name": "check", "configMap": {"name": name}},
                           {"name": "audit", "emptyDir": {}}, {"name": "home", "emptyDir": {}}],
               "containers": [{"name": "gate", "image": image, "command": ["node", "/check/check.mjs"],
                               "securityContext": {"allowPrivilegeEscalation": False, "capabilities": {"drop": ["ALL"]}},
                               "env": [{"name": k, "value": v} for k, v in {
                                   "HOME": "/work", "OPENCLAW_HOME": "/work",
                                   "OPENCLAW_CONFIG_PATH": "/work/openclaw.json", "TMPDIR": "/tmp"}.items()],
                               "resources": {"requests": {"memory": "256Mi", "cpu": "100m"},
                                             "limits": {"memory": "2Gi", "cpu": "2"}},
                               "volumeMounts": [{"name": "gate", "mountPath": "/sandbox/.saw/trusted", "readOnly": True},
                                                {"name": "check", "mountPath": "/check", "readOnly": True},
                                                {"name": "home", "mountPath": "/work"},
                                                {"name": "audit", "mountPath": "/sandbox/.saw/audit"}]}]}}}}
print(yaml.safe_dump_all([cm, script, policy, job], sort_keys=False))
