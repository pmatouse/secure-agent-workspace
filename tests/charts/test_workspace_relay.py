import shutil
import subprocess
from pathlib import Path

import pytest
import yaml
from helm_cache import run_helm

CHART = Path(__file__).resolve().parents[2] / "charts/saw-workspace-relay"
pytestmark = [pytest.mark.ci_external, pytest.mark.skipif(not shutil.which("helm"), reason="Helm required")]


def test_secret_and_membership_boundaries(tmp_path):
    values = dict(enabled=True, clientID="site-agent", keycloakNamespace="kc", keycloakAdminSecret="kc-admin",
                  issuer="https://kc.example/realms/openshell", trustedNamespace="trusted", gatewayNamespace="runtime",
                  installationID="installation", gateway="gateway", workspace="agent", workspaceID="old-id",
                  sandbox="assistant", ownerLogin="alice", ownerSubject="owner", subject="relay",
                  imageBuildNamespace="build", sdkImage="example/sdk@sha256:"+"f"*64,
                  host="alice.apps.example", egress=[{"ports":[{"port":443}]}])
    path = tmp_path / "values.yaml"
    path.write_text(yaml.safe_dump(values))
    output = run_helm(["helm","template","relay",str(CHART),"-n","ui","-f",str(path)],
                      capture_output=True,text=True)
    assert output.returncode == 0, output.stderr
    resources = list(yaml.safe_load_all(output.stdout))
    deployment = next(d for d in resources if d["kind"] == "Deployment")
    pod = deployment["spec"]["template"]["spec"]
    assert pod["automountServiceAccountToken"] is False
    assert [v["secret"]["secretName"] for v in pod["volumes"] if "secret" in v] == ["relay-credentials"]
    containers = {c["name"]:c for c in pod["containers"]}
    assert "credential" not in {v["name"] for v in containers["forward"]["volumeMounts"]}
    assert "--authenticated-emails-file=/config/users" in containers["browser-login"]["args"]
    jobs = {d["metadata"]["namespace"]:d["spec"]["template"]["spec"] for d in resources if d["kind"]=="Job"}
    assert jobs["trusted"]["automountServiceAccountToken"] is False
    assert not any("secret" in v for v in jobs["trusted"]["volumes"])
    volumes = {v["name"]: v for v in jobs["trusted"]["volumes"]}
    assert volumes["identity"]["configMap"]["name"] == "gateway-gateway-ca"
    assert volumes["admin-session"]["emptyDir"] == {"medium": "Memory", "sizeLimit": "4Mi"}
    runtime_role = next(d for d in resources if d["kind"] == "Role" and d["metadata"]["namespace"] == "runtime")
    assert runtime_role["rules"] == [{"apiGroups": [""], "resources": ["secrets"],
                                     "resourceNames": ["gateway-client-ca"], "verbs": ["get", "update"]}]
    binding = next(d for d in resources if d["kind"] == "RoleBinding" and d["metadata"].get("namespace") == "runtime")
    assert binding["subjects"] == [{"kind": "ServiceAccount", "name": "relay", "namespace": "trusted"}]
    assert [v["secret"]["secretName"] for v in jobs["kc"]["volumes"] if "secret" in v] == ["kc-admin"]
    role = next(d for d in resources if d["kind"]=="Role" and d["metadata"].get("namespace", "ui") == "ui")
    assert role["rules"] == [{"apiGroups":[""],"resources":["secrets"],"resourceNames":["relay-credentials"],"verbs":["get","patch"]}]


def test_relay_jobs_change_with_images_and_mount_their_exact_scripts():
    values = dict(enabled=True, clientID="site-agent", keycloakNamespace="kc", keycloakAdminSecret="kc-admin",
                  issuer="https://kc.example/realms/openshell", trustedNamespace="trusted", gatewayNamespace="runtime",
                  installationID="installation", gateway="gateway", workspace="agent", workspaceID="workspace-id",
                  sandbox="assistant", ownerLogin="alice", ownerSubject="owner", subject="relay",
                  imageBuildNamespace="build", sdkImage="example/sdk@sha256:"+"f"*64,
                  host="alice.apps.example", egress=[{"ports":[{"port":443}]}])
    def jobs(v):
        result = subprocess.run(["helm", "template", "relay", str(CHART), "-n", "ui", "-f", "-"],
                          input=yaml.safe_dump(v), capture_output=True, text=True, check=True)
        docs = list(yaml.safe_load_all(result.stdout))
        configs = {(o["metadata"].get("namespace", "ui"), o["metadata"]["name"]): o
                   for o in docs if o["kind"] == "ConfigMap"}
        names = set()
        for job in [o for o in docs if o["kind"] == "Job"]:
            script, = [v for v in job["spec"]["template"]["spec"]["volumes"] if v["name"] == "script"]
            assert configs[(job["metadata"]["namespace"], script["configMap"]["name"])]["immutable"] is True
            names.add(job["metadata"]["name"])
        return names
    initial = jobs(values)
    assert jobs(values) == initial
    changed = jobs({**values, "sdkImage": "example/sdk@sha256:"+"a"*64,
                    "pythonImage": "example/python@sha256:"+"a"*64})
    assert initial.isdisjoint(changed)
