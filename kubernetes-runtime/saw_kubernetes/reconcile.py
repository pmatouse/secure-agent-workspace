"""Serialized, restart-safe reconciliation over the stock OpenShell RPC surface.

The adapter implements ``call(method, request) -> response`` using protobuf-field
names. It must not retry unsafe writes itself or log request/response bodies.
"""

from __future__ import annotations

import contextlib
import copy
import fcntl
import json
import os
from pathlib import Path
import tempfile

from .compiler import ContractError, MANAGED, OWNER, REVISION, SOURCE_REVISION, digest, request_id


class RpcError(Exception):
    def __init__(self, code):
        # Do not persist arbitrary gateway errors that could contain credentials.
        self.code = code if code in {
            "NOT_FOUND", "ALREADY_EXISTS", "UNAVAILABLE", "DEADLINE_EXCEEDED",
            "ABORTED", "RESOURCE_EXHAUSTED", "PERMISSION_DENIED", "UNAUTHENTICATED",
            "INVALID_ARGUMENT", "FAILED_PRECONDITION", "UNKNOWN"} else "UNKNOWN"
        super().__init__(self.code)


class Busy(Exception):
    pass


class StateStore:
    """Single local/shared-filesystem writer; not a distributed Kubernetes lease."""

    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.directory.is_symlink():
            raise ContractError("state directory must not be a symlink")
        self.path = self.directory / "state.json"

    @contextlib.contextmanager
    def locked(self):
        fd = os.open(self.directory / "reconcile.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise Busy() from None
            yield
        finally:
            os.close(fd)

    def load(self):
        if not self.path.exists():
            return {}
        if self.path.is_symlink():
            raise ContractError("state must not be a symlink")
        try:
            value = json.loads(self.path.read_text())
        except (ValueError, OSError):
            raise ContractError("cannot read retained reconciler state") from None
        if not isinstance(value, dict):
            raise ContractError("retained reconciler state must be an object")
        return value

    def save(self, value):
        fd, tmp = tempfile.mkstemp(prefix="state-", dir=self.directory)
        try:
            with os.fdopen(fd, "w") as stream:
                json.dump(value, stream, sort_keys=True)
                stream.flush(); os.fsync(stream.fileno())
            os.replace(tmp, self.path)
            dirfd = os.open(self.directory, os.O_RDONLY)
            try:
                os.fsync(dirfd)
            finally:
                os.close(dirfd)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)


class Reconciler:
    """One bounded observation/apply pass; callers schedule the next pass.

    `verify_resources(plan)` must independently read/validate current cluster
    resource identity and integration security prerequisites. It is mandatory,
    called before every pass, and must fail closed. Tests use fake resources;
    providing a no-op in a deployment is not qualification.
    """

    def __init__(self, rpc, state_directory, verify_resources):
        self.rpc = rpc
        self.store = StateStore(state_directory)
        if not callable(verify_resources):
            raise ContractError("resource verifier is required")
        self.verify_resources = verify_resources

    def _get(self, method, request, field):
        try:
            response = self.rpc.call(method, request)
        except RpcError as exc:
            if exc.code == "NOT_FOUND":
                return None
            raise
        if not isinstance(response.get(field), dict):
            raise ContractError("gateway returned an invalid object")
        return response[field]

    def _mutate(self, method, request, plan, generation):
        body = copy.deepcopy(request)
        body["request_id"] = request_id(plan["ownerID"], method,
                                        {"request": request, "generation": generation})
        try:
            self.rpc.call(method, body)
        except RpcError as exc:
            if exc.code != "ALREADY_EXISTS":
                raise
        # Observe on the next pass, including ALREADY_EXISTS and ambiguous
        # timeouts. Never assume the mutation response proves convergence.

    def _identity(self, kind, workspace, name, obj, plan, state, default=False):
        meta = obj.get("metadata", {})
        labels = meta.get("labels", {})
        if meta.get("deletion_time"):
            raise ContractError("managed object is being deleted")
        if meta.get("name") != name or not meta.get("id"):
            raise ContractError("gateway object identity is missing or changed")
        if kind != "workspace" and meta.get("workspace", "default") != workspace:
            raise ContractError("gateway object is in the wrong workspace")
        if not default and (labels.get(OWNER) != plan["ownerID"] or labels.get(MANAGED) != "kubernetes-runtime"):
            raise ContractError("refusing to adopt an object owned by another installation")
        key = f"{kind}/{workspace}/{name}"
        previous = state.setdefault("objectIDs", {}).get(key)
        if previous is not None and previous != meta["id"]:
            raise ContractError("same-name replacement detected; explicit recovery is required")
        state["objectIDs"][key] = meta["id"]
        self.store.save(state)

    @staticmethod
    def _sandbox_spec_matches(actual, desired):
        # The pinned gateway adds provider_attachment_epoch and normalizes an
        # unspecified restart policy to Never during create (grpc/sandbox.rs).
        # Policy is governed by the platform, not compiled by this adapter;
        # do not confuse that policy with permission to add other spec fields.
        allowed = {"template", "providers", "command", "tty", "policy",
                   "provider_attachment_epoch", "restart_policy", "environment",
                   "resource_requirements", "log_level"}
        if not isinstance(actual, dict) or set(actual) - allowed:
            return False
        if any(actual.get(field) for field in ["environment", "resource_requirements", "log_level"]):
            return False
        if actual.get("restart_policy", "SANDBOX_RESTART_POLICY_NEVER") != "SANDBOX_RESTART_POLICY_NEVER":
            return False
        for field in ["template", "providers", "command", "tty"]:
            default = False if field == "tty" else ([] if field == "providers" else None)
            if actual.get(field, default) != desired[field]:
                return False
        return True

    def reconcile(self, plan, *, generation, desired_state="Running"):
        if type(generation) is not int or generation < 1 or desired_state not in {"Running", "Stopped"}:
            raise ContractError("a positive intent generation and Running/Stopped state are required")
        body = {k: v for k, v in plan.items() if k != "revision"}
        if plan.get("sourceRevision") != SOURCE_REVISION or plan.get("schemaVersion") != 1 or digest(body) != plan.get("revision"):
            raise ContractError("invalid or modified compiled plan")
        if plan.get("mode") not in {"container", "kata"} or plan.get("requestedPlacement") != {
                "supervisor": "container", "workload": plan["mode"]}:
            raise ContractError("stock adapter requires an ordinary-container supervisor")
        with self.store.locked():
            state = self.store.load()
            identity = {key: plan[key] for key in ["ownerID", "namespaceUID", "ownerSubject", "mode"]}
            if state and state.get("identity") != identity:
                raise ContractError("workspace identity, owner and deployment mode are immutable")
            previous = state.get("intent", {})
            intent = {"generation": generation, "revision": plan["revision"], "desiredState": desired_state}
            if previous.get("generation", 0) > generation or (previous.get("generation") == generation and previous != intent):
                raise ContractError("stale generation or conflicting intent at the same generation")
            self.verify_resources(plan)
            state.update(identity=identity, intent=intent)
            self.store.save(state)
            try:
                return self._pass(plan, state, generation, desired_state)
            except RpcError as exc:
                attempts = min(state.get("transientAttempts", 0) + 1, 8)
                state["transientAttempts"] = attempts
                self.store.save(state)
                if exc.code in {"UNAVAILABLE", "DEADLINE_EXCEEDED", "ABORTED", "RESOURCE_EXHAUSTED"}:
                    return self._status(plan, generation, "Retry", reason=exc.code,
                                        retry_after_seconds=min(2 ** attempts, 60))
                raise

    @staticmethod
    def _status(plan, generation, phase, **extra):
        return {"observedGeneration": generation, "desiredRevision": plan["revision"],
                "phase": phase, "requestedPlacement": plan["requestedPlacement"], **extra}

    def _pass(self, plan, state, generation, desired_state):
        info = self.rpc.call("GetGatewayInfo", {})
        if info.get("gateway_version") != plan["gatewayVersion"] or [d.get("name") for d in info.get("compute_drivers", [])] != ["kubernetes"]:
            raise ContractError("gateway version or active compute driver differs from approved inputs")
        for provider_type in sorted({p["type"] for w in plan["workspaces"] for p in w["providers"]}):
            # Resolve platform scope explicitly (workspace_scope omitted). A
            # workspace administrator's same-name custom profile is not enough.
            profile = self.rpc.call("GetProviderProfile", {"id": provider_type}).get("profile", {})
            if (profile.get("id") != provider_type or profile.get("credentials")
                    or not profile.get("source", "").startswith("interceptor/")):
                raise ContractError("provider profile is not a governed credential-free platform profile")
        pending = []
        for ws in plan["workspaces"]:
            scope = {"workspace_scope": {"workspace": ws["name"]}}
            obj = self._get("GetWorkspace", {"name": ws["name"]}, "workspace")
            if obj is None:
                if ws["name"] == "default":
                    raise ContractError("gateway default workspace is missing")
                self._mutate("CreateWorkspace", {"name": ws["name"], "labels": {
                    MANAGED: "kubernetes-runtime", OWNER: plan["ownerID"]}}, plan, generation)
                pending.append(f"workspace/{ws['name']}")
                continue
            self._identity("workspace", "", ws["name"], obj, plan, state, default=ws["name"] == "default")
            if obj.get("status", {}).get("phase") != "WORKSPACE_PHASE_ACTIVE":
                pending.append(f"workspace/{ws['name']}"); continue
            members, token, tokens = [], "", set()
            while True:
                response = self.rpc.call("ListWorkspaceMembers", {**scope, "page_size": 100, "page_token": token})
                members.extend(response.get("members", []))
                token = response.get("next_page_token", "")
                if not token:
                    break
                if token in tokens or len(tokens) >= 100:
                    raise ContractError("invalid membership pagination")
                tokens.add(token)
            member = next((m for m in members if m.get("principal_subject") == plan["ownerSubject"]), None)
            if member is None:
                self._mutate("AddWorkspaceMember", {**scope, "principal_subject": plan["ownerSubject"],
                    "role": "WORKSPACE_ROLE_ADMIN"}, plan, generation)
                pending.append(f"membership/{ws['name']}"); continue
            if member.get("role") != "WORKSPACE_ROLE_ADMIN":
                raise ContractError("existing owner membership has unexpected role")
            providers_ready = True
            for provider in ws["providers"]:
                pname = provider["metadata"]["name"]
                existing = self._get("GetProvider", {**scope, "name": pname}, "provider")
                if existing is None:
                    self._mutate("CreateProvider", {**scope, "provider": provider}, plan, generation)
                    providers_ready = False; pending.append(f"provider/{ws['name']}/{pname}"); continue
                self._identity("provider", ws["name"], pname, existing, plan, state)
                if existing.get("type") != provider["type"] or existing.get("config") or existing.get("credentials") or existing.get("credential_handles"):
                    raise ContractError("provider drift or unexpected credential state requires explicit recovery")
            if not providers_ready:
                continue
            for sandbox in ws["sandboxes"]:
                sname = sandbox["name"]
                ref = f"sandbox/{ws['name']}/{sname}"
                existing = self._get("GetSandbox", {**scope, "name": sname}, "sandbox")
                if existing is None:
                    if ref in state.get("objectIDs", {}):
                        raise ContractError("managed sandbox disappeared; refuse implicit recreation")
                    if desired_state == "Stopped":
                        # A stopped new intent must never start a workload merely
                        # to stop it afterward. It remains unapplied until Running.
                        pending.append(ref); continue
                    self._mutate("CreateSandbox", {**scope, **sandbox}, plan, generation)
                    pending.append(ref); continue
                self._identity("sandbox", ws["name"], sname, existing, plan, state)
                spec = existing.get("spec", {})
                if not self._sandbox_spec_matches(spec, sandbox["spec"]):
                    raise ContractError("sandbox configuration drift; migration is not implemented")
                if existing.get("metadata", {}).get("annotations", {}).get(REVISION) != sandbox["annotations"][REVISION]:
                    raise ContractError("sandbox desired revision mismatch")
                phase = existing.get("status", {}).get("phase")
                if phase == "SANDBOX_PHASE_ERROR":
                    raise ContractError("sandbox reports an error; inspect through authorized diagnostics")
                target = "SANDBOX_PHASE_READY" if desired_state == "Running" else "SANDBOX_PHASE_STOPPED"
                if phase == target:
                    continue
                if desired_state == "Running" and phase == "SANDBOX_PHASE_STOPPED":
                    self._mutate("StartSandbox", {**scope, "name": sname}, plan, generation)
                elif desired_state == "Stopped" and phase == "SANDBOX_PHASE_READY":
                    self._mutate("StopSandbox", {**scope, "name": sname}, plan, generation)
                pending.append(ref)
        state["transientAttempts"] = 0
        self.store.save(state)
        return self._status(plan, generation, "Pending" if pending else
                            ("GenericReady" if desired_state == "Running" else "Stopped"),
                            pending=pending, retry_after_seconds=5 if pending else 0)
