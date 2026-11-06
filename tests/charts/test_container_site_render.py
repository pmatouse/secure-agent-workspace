"""Portable container site inputs exercise the same Helm BOM as the installer."""
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
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


@pytest.fixture
def openai_bom(tmp_path):
    """A site fork selects OpenAI in its shared VM/container BOM, not in the renderer."""
    chart = tmp_path / "saw-bom"
    shutil.copytree(ROOT / "charts/saw-bom", chart)
    for path in (chart / "profiles/data-science").glob("*/providers.yaml"):
        doc = yaml.safe_load(path.read_text())
        doc["spec"]["providers"] = [{"name": "openai", "type": "openai",
                                    "credentialSecret": "inference", "credentialSecretKey": "api_key"}]
        path.write_text(yaml.safe_dump(doc))
    for path in (chart / "profiles/data-science").glob("*/sandbox.yaml"):
        doc = yaml.safe_load(path.read_text())
        for sandbox in doc["spec"]["sandboxes"]:
            sandbox["providers"] = ["openai"]
            if sandbox.get("enabled", True):
                sandbox["inference"].update(providerRef="openai", protocol="openai", baseUrl="https://api.openai.com/v1")
        path.write_text(yaml.safe_dump(doc))
    return chart


def test_data_science_uses_exact_site_bom_and_selected_revision(openai_bom):
    revision = "1" * 40
    s = module.render(inputs(), reference(), profile="data-science", controller_revision=revision,
                      bom_chart=openai_bom)["portal"]["containerSites"]["sawk8sowner"]
    actual = yaml.safe_load(subprocess.check_output([
        "helm", "template", "verify", str(openai_bom), "--set", "profiles[0]=data-science",
        "--set", "webSearch.enabled=false", "--set", "harnessEnabled=false", "--set-string",
        "imageOverrides.notebook=" + inputs()["notebookImage"]], text=True))["data"]
    assert s["automaticEnrollment"]["revision"] == revision
    assert s["automaticEnrollment"]["approvedProfiles"] == {"data-science": module.fingerprint(actual)}
    assert s["profileImageOverrides"] == {"data-science": {"notebook": inputs()["notebookImage"]}}
    assert s["profileBoundaries"] == {"data-science": {"allowHosts": ["api.openai.com"], "reference": reference()}}
    assert s["modelLifecycle"] is True
    assert "custom-inference" not in json.dumps(s)


def test_data_science_rejects_provider_boundary_mismatch(openai_bom):
    with pytest.raises(ValueError, match="enabled OpenAI providers"):
        module.render(inputs(), reference(), profile="data-science")
    path = openai_bom / "profiles/data-science/cuda-dev/sandbox.yaml"
    path.write_text(path.read_text().replace("https://api.openai.com/v1", "https://unapproved.example/v1"))
    with pytest.raises(ValueError, match="official OpenAI inference"):
        module.render(inputs(), reference(), profile="data-science", bom_chart=openai_bom)


@pytest.mark.parametrize("revision", ["main", "431ce74", "A" * 40])
def test_rejects_unpinned_controller_revision(revision):
    with pytest.raises(ValueError, match="full lowercase Git commit"):
        module.render(inputs(), reference(), controller_revision=revision)
    result = foundation("--controller-revision", revision, check=False)
    assert result.returncode != 0
    assert "full lowercase Git commit" in result.stderr


def foundation(*args, check=True):
    return subprocess.run([sys.executable, str(ROOT / "scripts/portal-container/render-foundation.py"), "build",
                           "--repo", "https://github.com/example/saw.git", "--build-namespace", "image-builds",
                           "--governance-namespace", "policy", *args], text=True, capture_output=True, check=check)


def test_foundation_revision_changes_only_controller_build():
    original = list(yaml.safe_load_all(foundation().stdout))
    revision = "1234567890abcdef1234567890abcdef12345678"
    selected = list(yaml.safe_load_all(foundation("--controller-revision", revision).stdout))
    controller = selected[1]
    assert controller["metadata"]["name"] == "saw-runtime-controller-" + revision[:7]
    assert controller["spec"]["source"]["git"]["ref"] == revision
    assert controller["spec"]["output"]["to"]["name"] == "saw-runtime-controller:" + revision[:12]
    assert selected[:1] + selected[2:] == original[:1] + original[2:]
