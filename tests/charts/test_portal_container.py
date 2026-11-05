"""Render the same owner request through both Helm levels and the stock component charts."""
from pathlib import Path
import json
import subprocess

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
U = "sawk8sowner"
REG = "a8cb6cbd0eb62f31"
SITE = yaml.safe_load((ROOT / "examples/portal-container/glmhg.yaml").read_text())["portal"]["containerSites"][U]
GLOBAL = {"repoURL":"https://github.com/pmatouse/secure-agent-workspace","targetRevision":"test",
          "vpArgoNamespace":"vp-gitops","clusterDomain":"cluster.example.com"}


def render(chart, release, ns, values):
    result = subprocess.run(["helm","template",release,str(ROOT/"charts"/chart),"--namespace",ns,
                  "--api-versions","agents.x-k8s.io/v1beta1","--api-versions","policy.networking.k8s.io/v1alpha1/AdminNetworkPolicy",
                  "--api-versions","admissionregistration.k8s.io/v1/ValidatingAdmissionPolicy","-f","-"],
                 input=json.dumps(values),text=True,capture_output=True)
    assert result.returncode == 0, result.stderr
    return [d for d in yaml.safe_load_all(result.stdout) if d]


def child(app):
    src = app["spec"]["source"]
    helm = src["helm"]
    return render(src["path"].split("/")[-1],helm["releaseName"],app["spec"]["destination"]["namespace"],
                  helm.get("valuesObject") or yaml.safe_load(helm["values"]))


def user():
    return {"name":U, "ownerSubject":SITE["subject"],"installationID":"802fe583-9329-54b6-b5b4-7be58ec171f3",
            "registration":REG,"intentGeneration":1,"vaultPrefix":f"secret/data/hub/saw-{U}/{REG}",
            "values":{"deployment":{"mode":"container"}},"profiles":["audited-openclaw"],"pruneOnRemove":True}


def test_container_has_own_gateway_credential_audit_and_policy():
    top = render("saw-users","portal-ws-"+U,"saw-portal",{"global":GLOBAL,"users":[user()],"containerSites":{U:SITE}})
    apps = [a for a in top if a["kind"]=="Application"]
    assert {a["spec"]["source"]["path"] for a in apps} == {"charts/saw-bom","charts/saw-portal-container"}
    resources = [r for a in apps for r in child(a)]
    es, = [r for r in resources if r["kind"]=="ExternalSecret"]
    assert es["metadata"]["namespace"] == "saw-ctl-"+REG
    assert es["spec"]["data"] == [{"secretKey":"api_key","remoteRef":{"key":user()["vaultPrefix"]+"/inference","property":"api_key"}}]
    archived_ns, = [r for r in resources if r["kind"]=="Namespace" and r["metadata"]["name"]=="saw-history-"+REG]
    archive_annotations=archived_ns["metadata"]["annotations"]
    assert archive_annotations["argocd.argoproj.io/compare-options"]=="IgnoreExtraneous"
    assert set(archive_annotations["argocd.argoproj.io/sync-options"].split(","))=={"Delete=false","Prune=false"}
    workloads = [r for a in resources if a["kind"]=="Application" for r in child(a)]
    assert not any(r["kind"]=="VirtualMachine" for r in workloads)
    net, = [r for r in workloads if r["kind"]=="AdminNetworkPolicy"]
    assert net["spec"]["subject"]["pods"]["namespaceSelector"]["matchLabels"]["kubernetes.io/metadata.name"] == "saw-"+U
    assert any(r["kind"]=="StatefulSet" and r["metadata"]["name"] == U+"-gateway" for r in workloads)
    history, = [r for r in workloads if r["kind"]=="PersistentVolumeClaim" and r["metadata"]["name"].endswith("-history")]
    assert history["metadata"]["namespace"] == "saw-history-"+REG
    assert "Delete=false" in history["metadata"]["annotations"]["argocd.argoproj.io/sync-options"]
    assert "saw-sawportalvm" not in json.dumps(workloads)


def test_container_rejects_another_registrations_keys():
    v = dict(owner=U,ownerSubject=SITE["subject"],registration=REG,vaultPrefix="secret/data/hub/saw-other/"+REG)
    with pytest.raises(AssertionError,match="vaultPrefix must match"):
        render("saw-portal-container",U,"saw-"+U,v)


def test_automatic_enrollment_cannot_read_secrets_or_mount_history():
    site=SITE
    v=dict(owner=U,ownerSubject=site["subject"],registration=REG,installationID=user()["installationID"],vaultPrefix=user()["vaultPrefix"],site=site,**{"global":GLOBAL})
    resources=render("saw-portal-container",U,"saw-"+U,v)
    j,=[r for r in resources if r["kind"]=="Job"]
    spec=j["spec"]["template"]["spec"]
    assert not any("persistentVolumeClaim" in v for v in spec["volumes"])
    assert [v["secret"]["items"] for v in spec["volumes"] if "secret" in v]==[[{"key":"ca.crt","path":"ca.crt"}]]
    grants=[rule for r in resources if r["kind"] in ("Role","ClusterRole") and "enroll" in r["metadata"]["name"] for rule in r["rules"]]
    assert all("secrets" not in x["resources"] and "*" not in x["verbs"] for x in grants)
    assert [x["resourceNames"] for x in grants if "patch" in x["verbs"]]==[["saw-portal-enrollment"]]
    files=ROOT/"charts/saw-portal-container/files"
    assert (files/"receipt.py").read_bytes()==(ROOT/"kubernetes-runtime/saw_kubernetes/receipt.py").read_bytes()
    assert (files/"portal_contract.py").read_text()==(ROOT/"kubernetes-runtime/saw_kubernetes/portal_contract.py").read_text().replace("from .boundary import","from saw_kubernetes.boundary import")
