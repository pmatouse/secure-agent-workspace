"""The portal adapter and other installation entry points share one projection."""
import copy
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("shared_workspace", ROOT / "charts/saw-users/files/workspace.py")
workspace = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(workspace)
CATALOG = json.loads((ROOT / "charts/saw-users/files/profile-catalog.json").read_text())["profiles"]


def inputs():
    owner = dict(name="alice", ownerSubject="11111111-1111-4111-8111-111111111111",
                 installationID="22222222-2222-4222-8222-222222222222", registration="a"*16,
                 profiles=["data-science"], values={"deployment": {"mode": "container"}},
                 lifecycleVersion=1, initialModelInputs={"inference.model": "first"},
                 modelInputs={"inference.model": "second"}, desiredState="Running", restartGeneration=2)
    site = dict(subject=owner["ownerSubject"], automaticEnrollment={"approvedProfiles": {"data-science": "b"*64}},
                profileImageOverrides={"data-science": {"default": {"notebook": "example/agent@sha256:"+"c"*64}}})
    return owner, site


def test_projection_uses_catalog_targets_and_preserves_callers_inputs():
    owner, site = inputs()
    before = copy.deepcopy((owner, site))
    result = workspace.project_workspace(owner, {"defaults": {}}, site, CATALOG)
    projected = result["containerSites"]["alice"]
    assert set(projected["targets"]) == {"default/notebook", "cuda-dev/cuda-sandbox"}
    assert projected["modelInputs"] == {"inference.model": "first"}
    assert projected["requestedModels"] == {"inference.model": "second"}
    assert projected["restartGeneration"] == 2
    assert projected["selectedDigest"] == "b"*64
    assert result["users"][0]["imageOverrides"] == site["profileImageOverrides"]["data-science"]
    assert (owner, site) == before
    assert "enrollment" not in projected


@pytest.mark.parametrize("fault", ["subject", "profile", "identity", "endpoint"])
def test_projection_rejects_unbound_input(fault):
    owner, site = inputs()
    if fault == "subject": site["subject"] = "replacement-owner"
    if fault == "profile": owner["profiles"] = ["personal-assistant"]
    if fault == "identity": del owner["installationID"]
    if fault == "endpoint": owner["customInferenceURL"] = "https://unexpected.example/v1"
    with pytest.raises(workspace.WorkspaceError):
        workspace.project_workspace(owner, {}, site, CATALOG)


def test_legacy_vm_remains_vm_and_reserved_modes_never_fall_back():
    result = workspace.project_workspace({"name": "alice"}, {}, {}, CATALOG)
    assert result["users"][0]["values"]["deployment"]["mode"] == "vm"
    for mode in ("kata", "confidential"):
        with pytest.raises(workspace.WorkspaceError, match="unsupported"):
            workspace.project_workspace({"name": "alice", "values": {"deployment": {"mode": mode}}}, {}, {}, CATALOG)


def test_packaged_projector_is_exactly_the_canonical_source():
    assert (ROOT / "charts/openshell-rhdh/files/workspace.py").read_bytes() == Path(SPEC.origin).read_bytes()


def test_disabling_enrollment_cannot_silently_prune_an_existing_runtime():
    owner, site = inputs()
    site["automaticEnrollment"]["enabled"] = False
    observed = {"immutable": True, "metadata": {"labels": {"saw.redhat.com/runtime-owner": owner["installationID"]}},
                "data": {"binding.json": "{}"}}
    with pytest.raises(workspace.WorkspaceError, match="cannot disable"):
        workspace.project_workspace(owner, {}, site, CATALOG, lambda _: observed)
    projected = workspace.project_workspace(owner, {}, site, CATALOG, lambda _: {})
    assert "enrollment" not in projected["containerSites"]["alice"]


def test_foundation_requires_no_synthetic_approval_hash():
    owner, site = inputs()
    site["automaticEnrollment"] = {"enabled": False}
    result = workspace.project_workspace(owner, {}, site, CATALOG, lambda _: {})
    assert not result["containerSites"]["alice"]["selectedDigest"]
    site["automaticEnrollment"]["enabled"] = True
    with pytest.raises(workspace.WorkspaceError):
        workspace.project_workspace(owner, {}, site, CATALOG, lambda _: {})
