"""Translate a deliberately small SAW profile subset to pinned OpenShell RPCs.

Only the administrator binding file may select PVCs/resources/RuntimeClasses.
No API calls, secret reads or mutations happen during compilation.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from pathlib import Path, PurePosixPath

import yaml

SOURCE_REVISION = "305c8b3d7bbdb97a6f2f7264c3ad43b0087c307f"
OWNER = "saw.redhat.com/runtime-owner"
REVISION = "saw.redhat.com/desired-sha256"
MANAGED = "saw.redhat.com/managed-by"
NAME = re.compile(r"[a-z0-9](?:[-a-z0-9]*[a-z0-9])?\Z")
IMAGE = re.compile(r"[^\s@]+@sha256:[0-9a-f]{64}\Z")
QUANTITY = re.compile(r"[1-9][0-9]*(?:m|Ki|Mi|Gi|Ti)?\Z")


class ContractError(ValueError):
    """An input is invalid or requires an unimplemented capability."""


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def request_id(owner, operation, value):
    return str(uuid.uuid5(uuid.UUID(owner), operation + ":" + digest(value)))


def mapping(value, allowed, required, where):
    if not isinstance(value, dict) or not all(isinstance(k, str) for k in value):
        raise ContractError(f"{where} must be an object")
    if set(value) - set(allowed) or set(required) - set(value):
        raise ContractError(f"{where} has unknown or missing fields")
    return value


def name(value, where, max_length=19):
    if not isinstance(value, str) or len(value) > max_length or not NAME.fullmatch(value):
        raise ContractError(f"{where} must be a DNS label of at most {max_length} characters")
    return value


def enabled(value, where):
    if type(value) is not bool:
        raise ContractError(f"{where}.enabled must be boolean")
    return value


def document(path, kind, spec_fields):
    if path.is_symlink():
        raise ContractError("profile documents must not be symlinks")
    try:
        raw = yaml.safe_load(path.read_text())
    except (OSError, ValueError, yaml.YAMLError):
        raise ContractError(f"cannot load {path.name}") from None
    mapping(raw, {"apiVersion", "kind", "metadata", "spec"}, {"apiVersion", "kind"}, path.name)
    if raw["apiVersion"] != "saw.redhat.com/v1alpha1" or raw["kind"] != kind:
        raise ContractError(f"{path.name} has unsupported apiVersion/kind")
    mapping(raw.get("metadata", {}), {"name", "description", "profile"}, set(), "metadata")
    mapping(raw.get("spec", {}), spec_fields, set(), "spec")
    return raw


def _claim(binding, workspace, mount_path, volume_name):
    mapping(binding, {"claimName", "uid", "readOnly"}, {"claimName", "uid", "readOnly"}, "PVC binding")
    # Intentionally stricter than Kubernetes subdomains for this first adapter.
    name(binding["claimName"], "claimName", 63)
    if not isinstance(binding["uid"], str) or not binding["uid"]:
        raise ContractError("PVC binding requires its observed UID")
    if type(binding["readOnly"]) is not bool:
        raise ContractError("PVC readOnly must be explicit boolean")
    volume = {"name": volume_name, "persistent_volume_claim": {
        "claim_name": binding["claimName"], "read_only": binding["readOnly"]}}
    mount = {"name": volume_name, "mount_path": mount_path, "read_only": binding["readOnly"]}
    reference = {"workspace": workspace, "name": binding["claimName"], "uid": binding["uid"]}
    return volume, mount, reference


def _storage(binding, workspace):
    mapping(binding, {"workspace", "mounts", "resources"}, {"workspace"}, "sandbox binding")
    volume, mount, reference = _claim(binding["workspace"], workspace, "/sandbox", "workspace")
    if binding["workspace"]["readOnly"]:
        raise ContractError("/sandbox must be writable")
    volumes, mounts, refs = [volume], [mount], [reference]
    extra = binding.get("mounts", [])
    if not isinstance(extra, list):
        raise ContractError("mounts must be a list")
    for i, item in enumerate(extra):
        mapping(item, {"claimName", "uid", "readOnly", "mountPath"},
                {"claimName", "uid", "readOnly", "mountPath"}, "mount")
        path = item["mountPath"]
        # Reserve /sandbox for the one retained workspace. Additional data may
        # only mount under /data, never over trusted/runtime/configuration trees.
        if not isinstance(path, str) or not (path == "/data" or path.startswith("/data/")):
            raise ContractError("additional mounts must be at /data or below it")
        if str(PurePosixPath(path)) != path or ".." in PurePosixPath(path).parts or any(ord(c) < 32 for c in path):
            raise ContractError("mountPath must be normalized")
        for existing in mounts:
            other = existing["mount_path"]
            if path == other or path.startswith(other + "/") or other.startswith(path + "/"):
                raise ContractError("overlapping mounts are not supported")
        claim = {k: v for k, v in item.items() if k != "mountPath"}
        volume, mount, reference = _claim(claim, workspace, path, f"data-{i}")
        if any(r["name"] == reference["name"] for r in refs):
            raise ContractError("one PVC cannot be attached through multiple bindings")
        volumes.append(volume); mounts.append(mount); refs.append(reference)
    resources = binding.get("resources", {})
    mapping(resources, {"requests", "limits"}, set(), "resources")
    for group in resources.values():
        mapping(group, {"cpu", "memory", "ephemeral-storage"}, set(), "resource quantities")
        if any(not isinstance(v, str) or not QUANTITY.fullmatch(v) for v in group.values()):
            raise ContractError("resource quantities must be positive supported quantity strings")
    return {"volumes": volumes, "containers": {"agent": {
        "volume_mounts": mounts, "resources": resources}}}, refs


def compile_profile(profile_dir, config):
    """Compile existing SAW YAML with separately approved administrator bindings.

    All inputs are validated before returning any requests. Unsupported active
    profiles fail as a whole; an empty/incomplete plan is never a successful port.
    """
    mapping(config, {"ownerID", "namespace", "namespaceUID", "ownerSubject", "mode",
                     "workloadRuntimeClass", "workloadRuntimeClassUID", "bindings",
                     "approvedCredentialFreeProviders", "gatewayVersion"},
            {"ownerID", "namespace", "namespaceUID", "ownerSubject", "mode", "bindings",
             "approvedCredentialFreeProviders", "gatewayVersion"}, "administrator configuration")
    try:
        owner = str(uuid.UUID(config["ownerID"]))
        if uuid.UUID(owner).int == 0:
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise ContractError("ownerID must be a nonzero UUID") from None
    name(config["namespace"], "namespace", 63)
    for key in ["namespaceUID", "ownerSubject", "gatewayVersion"]:
        if not isinstance(config[key], str) or not config[key].strip():
            raise ContractError(f"{key} must be a nonempty string")
    mode = config["mode"]
    runtime = config.get("workloadRuntimeClass", "")
    if mode not in {"container", "kata"}:
        raise ContractError("this adapter only accepts container or kata; confidential is unimplemented")
    if mode == "container" and (runtime or config.get("workloadRuntimeClassUID")):
        raise ContractError("container mode must not select a RuntimeClass")
    if mode == "kata":
        name(runtime, "Kata RuntimeClass", 63)
        if not isinstance(config.get("workloadRuntimeClassUID"), str) or not config["workloadRuntimeClassUID"]:
            raise ContractError("kata requires the approved RuntimeClass UID")
    approved = config["approvedCredentialFreeProviders"]
    if not isinstance(approved, list) or any(not isinstance(p, str) for p in approved):
        raise ContractError("approvedCredentialFreeProviders must be a list")
    bindings = config["bindings"]
    if not isinstance(bindings, dict):
        raise ContractError("bindings must be an object")
    root = Path(profile_dir)
    if not root.is_dir() or root.is_symlink():
        raise ContractError("profile path must be a real directory")
    workspaces, all_refs, used_bindings, seen = [], [], set(), set()
    for directory in sorted(root.iterdir()):
        if not directory.is_dir() or directory.is_symlink():
            raise ContractError("profile must contain workspace directories only")
        files = {p.name for p in directory.iterdir()}
        if files - {"workspace.yaml", "providers.yaml", "sandbox.yaml"} or "workspace.yaml" not in files:
            raise ContractError("workspace contains unsupported files or lacks workspace.yaml")
        ws = document(directory / "workspace.yaml", "Workspace", {"enabled"})
        if not enabled(ws.get("spec", {}).get("enabled", True), "workspace"):
            continue
        ws_name = name(ws.get("metadata", {}).get("name"), "workspace")
        if ws_name in seen:
            raise ContractError("duplicate workspace name")
        seen.add(ws_name)
        providers = []
        if "providers.yaml" in files:
            doc = document(directory / "providers.yaml", "Providers", {"providers"})
            entries = doc.get("spec", {}).get("providers", [])
            if not isinstance(entries, list):
                raise ContractError("providers must be a list")
            for item in entries:
                if not isinstance(item, dict):
                    raise ContractError("provider must be an object")
                if not enabled(item.get("enabled", True), "provider"):
                    continue
                mapping(item, {"name", "type", "enabled", "credentialFree"},
                        {"name", "type", "credentialFree"}, "credential-free provider")
                pname = name(item["name"], "provider")
                if item["credentialFree"] is not True or item["type"] not in approved or pname != item["type"]:
                    raise ContractError("provider must be a named administrator-approved credential-free profile")
                if any(p["metadata"]["name"] == pname for p in providers):
                    raise ContractError("duplicate provider name")
                providers.append({"metadata": {"name": pname, "labels": {MANAGED: "kubernetes-runtime", OWNER: owner}},
                                  "type": item["type"]})
        sandboxes = []
        if "sandbox.yaml" in files:
            doc = document(directory / "sandbox.yaml", "Sandboxes", {"sandboxes"})
            entries = doc.get("spec", {}).get("sandboxes", [])
            if not isinstance(entries, list):
                raise ContractError("sandboxes must be a list")
            for item in entries:
                if not isinstance(item, dict):
                    raise ContractError("sandbox must be an object")
                if not enabled(item.get("enabled", True), "sandbox"):
                    continue
                if item.get("type", "generic") != "generic":
                    raise ContractError("agent profiles (including openclaw/nemoclaw) are not yet ported to Kubernetes")
                mapping(item, {"name", "type", "enabled", "image", "providers"},
                        {"name", "image"}, "generic sandbox (harness/UI/inference/env are not yet ported)")
                sname = name(item["name"], "sandbox")
                if any(s["name"] == sname for s in sandboxes):
                    raise ContractError("duplicate sandbox name")
                if not isinstance(item["image"], str) or not IMAGE.fullmatch(item["image"]):
                    raise ContractError("sandbox image must be pinned by sha256 digest")
                references = item.get("providers", [])
                if not isinstance(references, list) or any(not isinstance(p, str) for p in references):
                    raise ContractError("sandbox providers must be a list of names")
                if len(set(references)) != len(references) or not set(references) <= {p["metadata"]["name"] for p in providers}:
                    raise ContractError("sandbox provider references must be unique and enabled")
                key = f"{ws_name}/{sname}"
                if key not in bindings:
                    raise ContractError(f"{key} requires an administrator-approved retained workspace PVC")
                used_bindings.add(key)
                driver, refs = _storage(bindings[key], ws_name)
                all_refs.extend(refs)
                if runtime:
                    driver["pod"] = {"runtime_class_name": runtime}
                spec = {"template": {"image": item["image"], "driver_config": {"kubernetes": driver}},
                        "providers": sorted(references), "command": ["sh", "-c", "sleep infinity"], "tty": False}
                sandboxes.append({"name": sname, "spec": spec, "annotations": {REVISION: digest(spec)},
                                  "labels": {MANAGED: "kubernetes-runtime", OWNER: owner}})
        workspaces.append({"name": ws_name, "providers": sorted(providers, key=lambda p: p["metadata"]["name"]),
                           "sandboxes": sorted(sandboxes, key=lambda s: s["name"])})
    if not workspaces or not any(w["sandboxes"] for w in workspaces):
        raise ContractError("profile must contain at least one enabled generic sandbox")
    if set(bindings) != used_bindings:
        raise ContractError("unused administrator bindings must be removed")
    claims = [r["name"] for r in all_refs]
    if len(claims) != len(set(claims)):
        raise ContractError("sharing retained claims between sandboxes is not supported")
    plan = {"schemaVersion": 1, "sourceRevision": SOURCE_REVISION, "ownerID": owner,
            "namespace": config["namespace"], "namespaceUID": config["namespaceUID"],
            "ownerSubject": config["ownerSubject"], "mode": mode, "gatewayVersion": config["gatewayVersion"],
            "requestedPlacement": {"supervisor": "container", "workload": mode},
            "runtimeClass": {"name": runtime, "uid": config.get("workloadRuntimeClassUID", "")},
            "claims": sorted(all_refs, key=lambda r: (r["workspace"], r["name"])),
            "workspaces": sorted(workspaces, key=lambda w: w["name"])}
    return {**plan, "revision": digest(plan)}
