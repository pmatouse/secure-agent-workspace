"""Portable custom-inference site inputs exercise the same Helm BOM as the installer."""
import importlib.util
import json
from pathlib import Path
from uuid import uuid4

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "examples/portal-container"
spec = importlib.util.spec_from_file_location("render_site", ROOT / "scripts/portal-container/render-site.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def inputs():
    return yaml.safe_load((EXAMPLES / "glmhg-custom-inputs.yaml").read_text())


def reference():
    return json.loads((EXAMPLES / "glmhg-custom-boundary.json").read_text())


def test_registered_digest_and_profile_scope():
    s = module.render(inputs(), reference())["portal"]["containerSites"]["sawk8sowner"]
    assert s["automaticEnrollment"]["approvedProfiles"] == {
        "custom-inference": "42a0f00d3ea99f9259194763583b7ce63fb1a1d26984362c0df021897138f261"}
    assert s["profileBoundaries"]["custom-inference"]["reference"] == reference()
    assert s["profileBoundaries"]["custom-inference"]["allowHosts"] == ["api.openai.com"]


def test_site_substitution_and_review_fence():
    v = inputs()
    v.update(owner="alice", subject=str(uuid4()), issuer="https://keycloak.cluster.example/realms/openshell",
             buildNamespace="image-builds", governanceNamespace="policy", apiAddresses=["192.0.2.1"],
             issuerAddresses=["192.0.2.2"], clusterCIDRs=["198.18.0.0/15"], gatewayStorage="rbd",
             historyStorage="rbd-now", exchangeStorage="cephfs")
    for k in ("notebookImage","controllerImage"):
        v[k] = v[k].replace("saw-k8s-build", "image-builds")
    s = module.render(v, None)["portal"]["containerSites"]["alice"]
    text = json.dumps(s)
    for old in ("sawk8sowner","cluster-glmhg","10.10.10.","172.231.","saw-k8s-build","ocs-external"):
        assert old not in text
    assert "$input" not in text
    r = s["profileBoundaries"]["custom-inference"]["reference"]
    assert set(r) == set(reference()) and r["governance"] != reference()["governance"]
    with pytest.raises(ValueError):
        module.validate_reference(r)
    k = s["stack"]["gateway"]["values"]["kubernetes"]
    assert k["governance"]["endpoint"] == "http://governance-interceptor.policy.svc:18081"
    assert k["network"]["gatewayEgress"][0]["to"] == [{"ipBlock":{"cidr":"192.0.2.1/32"}}]
    assert "198.18.0.0/15" in s["stack"]["proxy"]["values"]["network"]["proxyEgress"][1]["to"][0]["ipBlock"]["except"]


def test_unreviewed_or_credential_input_rejected():
    v = inputs()
    with pytest.raises(ValueError):
        module.render({**v, "apiKey": "fixture"}, reference())
    with pytest.raises(ValueError):
        module.render({**v, "controllerImage":"saw-runtime-controller:latest"}, reference())
    unreviewed = reference()
    del unreviewed["governancePolicy"]
    with pytest.raises(ValueError):
        module.render(v, unreviewed)
