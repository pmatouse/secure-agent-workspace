import shutil
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
                  imageBuildNamespace="build", sdkImage="example/sdk@sha256:"+"f"*64, gatewayAdminSecret="admin",
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
    assert [v["secret"]["secretName"] for v in jobs["trusted"]["volumes"] if "secret" in v] == ["admin"]
    assert [v["secret"]["secretName"] for v in jobs["kc"]["volumes"] if "secret" in v] == ["kc-admin"]
    role = next(d for d in resources if d["kind"]=="Role")
    assert role["rules"] == [{"apiGroups":[""],"resources":["secrets"],"resourceNames":["relay-credentials"],"verbs":["get","patch"]}]
