"""One browser acceptance client respects each deployment mode's offered profiles."""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("rhdh_acceptance_modes", ROOT / "tests/acceptance/rhdh_workspace.py")
client = importlib.util.module_from_spec(spec)
spec.loader.exec_module(client)


@pytest.fixture
def form():
    return {"properties": {"deploymentMode": {"enum": ["vm", "container"]}},
            "dependencies": {"deploymentMode": {"oneOf": [
                {"properties": {"deploymentMode": {"enum": ["vm"]},
                                "profile": {"enum": ["data-science", "developer"]}}},
                {"properties": {"deploymentMode": {"enum": ["container"]},
                                "profile": {"enum": ["data-science", "audited-openclaw"]}}}]}}}


@pytest.mark.parametrize("mode", ["vm", "container"])
def test_same_profile_selects_requested_backend_without_credentials(form, mode):
    assert client.workspace_values(form, mode, "data-science") == {
        "profile": "data-science", "deploymentMode": mode, "inference__api_key": "********"}


@pytest.mark.parametrize("mode,profile", [("vm", "audited-openclaw"), ("container", "developer")])
def test_profile_approval_cannot_cross_backend(form, mode, profile):
    with pytest.raises(RuntimeError, match=f"requested {mode} profile"):
        client.workspace_values(form, mode, profile)
