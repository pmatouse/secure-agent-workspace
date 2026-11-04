"""Shared SAW profile models, validation and workspace dependency ordering.

This is the canonical source for VM and Kubernetes integrations. It owns no
subprocess, cluster, credential-resolution or installation operations; effectful
ordering callbacks belong to backend adapters. Runtime
credential fields on legacy dataclasses remain for compatibility; parsing only
populates declarative references, never credential material. Backend capability
checks and mutation adapters are separate from this common profile language.

The VM chart embeds these exact bytes into its signed installer at render time.
Do not maintain a second copy or import this module from untrusted input paths.
"""

import base64
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

API_VERSION = "saw.redhat.com/v1alpha1"


NAME_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")


SECRET_NAME_RE = re.compile(r"^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$")


SECRET_KEY_RE = re.compile(r"^[-._a-zA-Z0-9]+$")


OPENSHELL_NAME_LIMIT = 19


PROVIDER_CRED_MAP = {
    "gemini": "GEMINI_API_KEY",
    "google-vertex-ai": "GOOGLE_API_KEY",
    "claude-code": "ANTHROPIC_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "codex": "OPENAI_API_KEY",
    "openai": "OPENAI_API_KEY",
    "nvidia": "NVIDIA_API_KEY",
    "build": "NVIDIA_INFERENCE_API_KEY",
    "brave": "BRAVE_API_KEY",
    "tavily": "TAVILY_API_KEY",
}


# NemoClaw calls the NVIDIA API Catalog "build"; OpenShell calls it "nvidia".
NEMOCLAW_PROVIDER_MAP = {
    "nvidia": "build",
}


def nemoclaw_provider(provider):
    return provider.nemoclaw_provider or NEMOCLAW_PROVIDER_MAP.get(provider.type, provider.type)


def profile_credential_envs(profile_text):
    """The first env var of each credential a provider profile declares, in
    order (credentials[i].env_vars[0]); "" for a credential without one."""
    try:
        doc = yaml.safe_load(profile_text) if profile_text else None
    except yaml.YAMLError:
        return []
    out = []
    for cred in (doc or {}).get("credentials") or []:
        envs = (cred.get("env_vars") or []) if isinstance(cred, dict) else []
        out.append(envs[0] if envs else "")
    return out


def profile_credentials(profile_text):
    """A provider profile's credentials: [(name, [env vars])], in order."""
    try:
        doc = yaml.safe_load(profile_text) if profile_text else None
    except yaml.YAMLError:
        return []
    out = []
    for cred in (doc or {}).get("credentials") or []:
        if isinstance(cred, dict) and cred.get("name"):
            out.append((str(cred["name"]), [str(e) for e in cred.get("env_vars") or []]))
    return out


def profile_all_credential_envs(profile_text):
    """Every env var any credential of a provider profile is exposed under
    (all of credentials[].env_vars, e.g. GITHUB_TOKEN and GH_TOKEN)."""
    try:
        doc = yaml.safe_load(profile_text) if profile_text else None
    except yaml.YAMLError:
        return set()
    return {env for cred in (doc or {}).get("credentials") or [] if isinstance(cred, dict)
            for env in (cred.get("env_vars") or [])}


def profile_credential_env(profile_text):
    """The primary credential env var a provider profile declares
    (credentials[0].env_vars[0]), or "" when it declares none."""
    envs = profile_credential_envs(profile_text)
    return envs[0] if envs else ""


def credential_env_name(provider_type, profiles):
    """Env var the installer passes a provider's credential through: the one
    the provider's own profile declares, else the built-in default. This lets
    a profile-backed type (github, slack, gmail, ...) work as a provider with
    no PROVIDER_CRED_MAP edit; for the shipped built-ins the two agree."""
    return (profile_credential_env((profiles or {}).get(provider_type, ""))
            or PROVIDER_CRED_MAP.get(provider_type, ""))


SANDBOX_TYPES = {"generic", "openclaw", "nemoclaw"}


BASE_URL_CONFIG_KEYS = {
    "openai": "OPENAI_BASE_URL",
    "anthropic": "ANTHROPIC_BASE_URL",
    "nvidia": "NVIDIA_BASE_URL",
}


class InstallerError(Exception):
    """A failure with a message that is safe to log and show in status."""


@dataclass
class Provider:
    name: str
    type: str
    enabled: bool = True
    nemoclaw_provider: str = ""
    credential_secret: str = ""
    credential_secret_key: str = "api_key"
    model: str = ""
    # Secret keys the base URL and the model are read from (optional).
    base_url_secret_key: str = ""
    model_secret_key: str = ""
    inference_timeout: int = 0
    base_url: str = ""
    credential_free: bool = False
    # Optional `credentials:` mapping, keyed by the profile's credential name
    # ({api_key: {secretKey: ...}, app_secret: {secretKey: ...}}): one value
    # per credential, from the same Secret, each passed as its own
    # `--credential ENV` with the env var that credential declares. The
    # single-credential shorthand credentialSecretKey is one entry for the
    # profile's first credential.
    refresh_strategy: str = ""
    refresh_material: dict = field(default_factory=dict)
    credentials_spec: dict = field(default_factory=dict)
    credential_values: dict = field(default_factory=dict)   # credential name -> value


@dataclass
class Sandbox:
    name: str
    type: str = "generic"
    enabled: bool = True
    agent: str = "openclaw"
    image: str = ""
    providers: list = field(default_factory=list)
    model: str = ""
    harness_ref: dict = field(default_factory=dict)
    # `env:` -- the workload's environment (`sandbox create --env`; changing
    # it recreates the sandbox). {NAME: {value, title?}}: literals only, so
    # env_values (below) is derived, never a resolved copy that could go
    # stale (found in CI: freshly parsed profiles compared an empty copy
    # with the sandbox's env label and recreated it). Never for credentials
    # (the agent, and argv, can read these): those stay on providers.
    env: dict = field(default_factory=dict)
    # `inference:` -- how the agent reaches its model: {providerRef, protocol,
    # baseUrl?, model, models?, timeoutSeconds?}. models maps optional native
    # provider names to additional chat model inputs. baseUrl/model/timeoutSeconds
    # is a literal or an input ({secretKeyRef: {name, key}, default?,
    # required?, title?}); inference_values is it resolved. The installer onboards the
    # agent from it (by protocol, so any profile-backed provider type works).
    inference: dict = field(default_factory=dict)
    inference_values: dict = field(default_factory=dict)

    @property
    def env_values(self):
        """NAME -> value for the sandbox's env (literal entries; anything
        else is refused by validation)."""
        if not isinstance(self.env, dict):
            return {}
        return {str(name): str(src["value"]) for name, src in sorted(self.env.items())
                if isinstance(src, dict) and "value" in src}


@dataclass
class Workspace:
    name: str
    enabled: bool = True
    description: str = ""
    providers: list = field(default_factory=list)
    sandboxes: list = field(default_factory=list)


@dataclass
class Profile:
    name: str
    workspaces: list = field(default_factory=list)


@dataclass
class HarnessBundle:
    name: str
    agent: str = "openclaw"
    digest: str = ""
    files: dict = field(default_factory=dict)   # relpath -> base64 text


def read_profile_files(directory):
    """Read the flattened saw-bom ConfigMap.

    Returns (profile files as text, harness files as bytes, harness index).
    Profile keys are profiles__<profile>__<ws>__<file>.yaml; harness keys are
    harness__<bundle>__<hash-or-"map"> and hold base64 (see the digest
    contract in templates/configmap-bom.yaml and parse_harness_files).
    """
    directory = Path(directory)
    if not directory.is_dir():
        return {}, {}, {}
    files, harness, index = {}, {}, {}
    for entry in sorted(directory.iterdir()):
        if entry.name.startswith(".") or not entry.is_file():
            continue  # kubelet/ISO housekeeping entries
        if entry.name.startswith("profiles__") and entry.name.endswith(".yaml"):
            files[entry.name] = entry.read_text(encoding="utf-8")
        elif entry.name.startswith("harness__"):
            try:
                harness[entry.name] = base64.b64decode(
                    entry.read_text(encoding="utf-8"), validate=True)
            except (ValueError, UnicodeDecodeError) as exc:
                raise InstallerError(
                    f"harness file {entry.name} is not valid base64 ({exc}); "
                    "the chart must b64enc every harness key") from None
        elif entry.name == "harness-index.yaml":
            index = _yaml(entry.read_text(encoding="utf-8"), entry.name)
        else:
            # A wrong key layout must not look like "no profiles".
            raise InstallerError(f"unexpected file in the profiles ConfigMap: {entry.name}")
    return files, harness, index


def _yaml(text, where):
    try:
        return yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        raise InstallerError(f"{where}: invalid YAML ({exc})") from None


PROFILE_DOCUMENT_KINDS = {
    "workspace.yaml": "Workspace", "providers.yaml": "Providers", "sandbox.yaml": "Sandboxes",
}
PROFILE_PROVIDER_FIELDS = {
    "name", "type", "enabled", "credentialFree", "nemoclawProvider", "credentialSecret",
    "credentialSecretKey", "model", "baseUrlSecretKey", "modelSecretKey", "inferenceTimeout",
    "refresh", "credentials",
}
PROFILE_SANDBOX_FIELDS = {
    "name", "type", "enabled", "agent", "image", "providers", "model", "harnessRef", "env", "inference",
    "harnessRequired", "ui",
}


def _profile_mapping(value, allowed, required, where):
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise InstallerError(f"{where}: expected a mapping with string keys")
    missing, unknown = set(required) - set(value), set(value) - set(allowed)
    if missing or unknown:
        raise InstallerError(f"{where}: unknown or missing profile fields")
    return value


def _profile_input(value, kinds, where):
    if isinstance(value, dict):
        _profile_mapping(value, INPUT_KEYS, {"secretKeyRef"}, where)
        reference = _profile_mapping(value["secretKeyRef"], {"name", "key"}, {"name", "key"}, where)
        if any(not isinstance(item, str) for item in reference.values()):
            raise InstallerError(f"{where}: input references must be strings")
        if "title" in value and not isinstance(value["title"], str):
            raise InstallerError(f"{where}: input title must be a string")
    if input_problems(value, kinds):
        raise InstallerError(f"{where}: invalid inference input")


def validate_profile_document(doc, kind, where="profile"):
    """Strict common document schema, independent of backend capabilities.

    Legacy VM parsing remains compatible by default; new adapters call
    ``parse_profiles(..., strict=True)`` before capability checks so unknown
    fields cannot be silently discarded while constructing dataclasses.
    ``validate_profiles`` still validates cross-object semantics afterward.
    """
    _profile_mapping(doc, {"apiVersion", "kind", "metadata", "spec"}, {"apiVersion", "kind"}, where)
    if kind not in PROFILE_DOCUMENT_KINDS.values() or doc["apiVersion"] != API_VERSION or doc["kind"] != kind:
        raise InstallerError(f"{where}: unsupported profile apiVersion or kind")
    metadata = _profile_mapping(doc.get("metadata", {}), {"name", "description", "profile"}, set(), where)
    if any(not isinstance(value, str) for value in metadata.values()):
        raise InstallerError(f"{where}: metadata fields must be strings")
    fields = {"Workspace": {"enabled"}, "Providers": {"providers"}, "Sandboxes": {"sandboxes"}}[kind]
    spec = _profile_mapping(doc.get("spec", {}), fields, set(), where)
    if kind == "Workspace":
        if "enabled" in spec and type(spec["enabled"]) is not bool:
            raise InstallerError(f"{where}: enabled must be boolean")
        return doc
    list_key = "providers" if kind == "Providers" else "sandboxes"
    entries = spec.get(list_key, [])
    if not isinstance(entries, list):
        raise InstallerError(f"{where}: {list_key} must be a list")
    allowed = PROFILE_PROVIDER_FIELDS if kind == "Providers" else PROFILE_SANDBOX_FIELDS
    required = {"name", "type"} if kind == "Providers" else {"name"}
    for entry in entries:
        _profile_mapping(entry, allowed, required, where)
        booleans = {"enabled", "credentialFree"} if kind == "Providers" else {"enabled", "harnessRequired"}
        objects = {"refresh", "credentials"} if kind == "Providers" else {"harnessRef", "env", "inference", "ui"}
        for field_name, value in entry.items():
            if field_name in booleans:
                if type(value) is not bool:
                    raise InstallerError(f"{where}: {field_name} must be boolean")
            elif field_name in objects:
                if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
                    raise InstallerError(f"{where}: {field_name} must be a mapping with string keys")
            elif field_name == "inferenceTimeout":
                if type(value) is not int or value < 0:
                    raise InstallerError(f"{where}: inferenceTimeout must be a nonnegative integer")
            elif field_name == "providers":
                if not isinstance(value, list) or any(not isinstance(ref, str) for ref in value):
                    raise InstallerError(f"{where}: providers must be a list of names")
            elif not isinstance(value, str):
                raise InstallerError(f"{where}: {field_name} must be a string")
        if kind == "Providers":
            if "refresh" in entry:
                refresh = _profile_mapping(entry["refresh"], {"strategy"}, {"strategy"}, where)
                if not isinstance(refresh["strategy"], str):
                    raise InstallerError(f"{where}: refresh.strategy must be a string")
            if "credentials" in entry:
                for credential in entry["credentials"].values():
                    _profile_mapping(credential, {"secretKey", "title"}, {"secretKey"}, where)
                    if any(not isinstance(value, str) for value in credential.values()):
                        raise InstallerError(f"{where}: credential references must be strings")
        else:
            if "ui" in entry:
                ui = _profile_mapping(entry["ui"], {"route"}, set(), where)
                if "route" in ui and type(ui["route"]) is not bool:
                    raise InstallerError(f"{where}: ui.route must be boolean")
            if "harnessRef" in entry:
                harness = _profile_mapping(entry["harnessRef"], {"name", "image", "digest"}, set(), where)
                if any(not isinstance(value, str) for value in harness.values()):
                    raise InstallerError(f"{where}: harness references must be strings")
            for name, value in entry.get("env", {}).items():
                _profile_mapping(value, SANDBOX_ENV_KEYS, {"value"}, where)
                if "title" in value and not isinstance(value["title"], str):
                    raise InstallerError(f"{where}: environment title must be a string")
                if sandbox_env_problems(name, value):
                    raise InstallerError(f"{where}: invalid sandbox environment entry")
            inference = entry.get("inference", {})
            _profile_mapping(inference, INFERENCE_KEYS, set(), where)
            if "providerRef" in inference and not isinstance(inference["providerRef"], str):
                raise InstallerError(f"{where}: inference.providerRef must be a string")
            if "protocol" in inference and not isinstance(inference["protocol"], str):
                raise InstallerError(f"{where}: inference.protocol must be a string")
            for field_name in ("model", "baseUrl", "timeoutSeconds"):
                kinds = (str, int) if field_name == "timeoutSeconds" else (str,)
                if field_name in inference:
                    _profile_input(inference[field_name], kinds, where)
            if "models" in inference:
                models = inference["models"]
                if not isinstance(models, dict) or any(not isinstance(key, str) for key in models):
                    raise InstallerError(f"{where}: inference.models must be a mapping of names to inputs")
                for value in models.values():
                    _profile_input(value, (str,), where)
    return doc


def parse_profiles(files, *, strict=False, document_check=None):
    """Build profiles from {flat key: yaml text}.

    Only keys of the form profiles__<profile>__<workspace>__<file>.yaml are
    used, where <file> is workspace, providers or sandbox. Strict mode validates
    the common document shape before normalization; backend capabilities remain
    a separate check, so all backends use the same profile language. An optional
    ``document_check(doc, kind)`` can reject backend-unsupported chart directives
    before normalization (for example UI routes managed outside the VM parser).
    It receives a schema-validated document whenever strict mode is enabled.
    """
    grouped = {}
    for key, text in files.items():
        parts = key.split("__")
        if len(parts) != 4 or parts[0] != "profiles":
            raise InstallerError(f"unexpected profile file name: {key}")
        _, profile, ws_dir, filename = parts
        if filename not in ("workspace.yaml", "providers.yaml", "sandbox.yaml"):
            raise InstallerError(f"unexpected profile file: {key}")
        if strict or document_check is not None:
            doc, kind = _yaml(text, key), PROFILE_DOCUMENT_KINDS[filename]
            if strict:
                validate_profile_document(doc, kind, key)
            if document_check is not None:
                document_check(doc, kind)
        grouped.setdefault(profile, {}).setdefault(ws_dir, {})[filename] = (key, text)

    profiles = []
    for profile_name in sorted(grouped):
        profile = Profile(name=profile_name)
        for ws_dir in sorted(grouped[profile_name]):
            docs = grouped[profile_name][ws_dir]
            if "workspace.yaml" not in docs:
                raise InstallerError(f"profile {profile_name}/{ws_dir} has no workspace.yaml")
            key, text = docs["workspace.yaml"]
            ws_doc = _yaml(text, key)
            meta = ws_doc.get("metadata") or {}
            spec = ws_doc.get("spec") or {}
            ws = Workspace(name=meta.get("name", ws_dir),
                           enabled=spec.get("enabled", True),
                           description=meta.get("description", ""))
            if "providers.yaml" in docs:
                key, text = docs["providers.yaml"]
                for p in (_yaml(text, key).get("spec") or {}).get("providers") or []:
                    if "name" not in p or "type" not in p:
                        raise InstallerError(f"{key}: every provider needs name and type")
                    cred_spec = p.get("credentials")
                    if cred_spec is not None and "credentialSecretKey" in p:
                        raise InstallerError(f"{key}: provider '{p['name']}' sets both "
                                             "credentials and credentialSecretKey; use one")
                    primary_key = p.get("credentialSecretKey", "api_key")
                    ws.providers.append(Provider(
                        name=p["name"], type=p["type"],
                        enabled=p.get("enabled", True),
                        credential_free=p.get("credentialFree", False),
                        nemoclaw_provider=p.get("nemoclawProvider", ""),
                        credential_secret=p.get("credentialSecret", ""),
                        credential_secret_key=primary_key,
                        model=p.get("model", ""),
                        base_url_secret_key=p.get("baseUrlSecretKey", ""),
                        model_secret_key=p.get("modelSecretKey", ""),
                        inference_timeout=int(p.get("inferenceTimeout", 0) or 0),
                        refresh_strategy=str((p.get("refresh") or {}).get("strategy", "")),
                        credentials_spec=cred_spec if cred_spec is not None else {}))
            if "sandbox.yaml" in docs:
                key, text = docs["sandbox.yaml"]
                for s in (_yaml(text, key).get("spec") or {}).get("sandboxes") or []:
                    if "name" not in s:
                        raise InstallerError(f"{key}: every sandbox needs a name")
                    ws.sandboxes.append(Sandbox(
                        name=s["name"], type=s.get("type", "generic"),
                        enabled=s.get("enabled", True),
                        agent=s.get("agent", "openclaw"),
                        image=s.get("image", ""),
                        providers=list(s.get("providers") or []),
                        model=s.get("model", ""),
                        harness_ref=dict(s.get("harnessRef") or {}),
                        env=s.get("env") if s.get("env") is not None else {},
                        inference=s.get("inference") if s.get("inference") is not None else {}))
            profile.workspaces.append(ws)
        profiles.append(profile)
    return profiles


def enabled_workspaces(profiles):
    for profile in profiles:
        for ws in profile.workspaces:
            if ws.enabled:
                yield profile, ws


def apply_workspace_sequence(workspace, providers, sandboxes, adapter):
    """Shared dependency ordering for one bounded workspace apply pass.

    The backend supplies ``prepare_workspace``, ``apply_provider`` and
    ``apply_sandbox`` methods returning readiness booleans. Observe/apply all
    providers before the barrier; a pending workspace or provider prevents
    sandbox creation. Backends retain authentication, ownership, capability
    validation, retry/deletion policy and error handling. No backend exception
    is swallowed here, and this function does not turn readiness into agent
    health. Callers select enabled entries or implement explicit skip behavior.
    """
    if not adapter.prepare_workspace(workspace):
        return False
    providers_ready = True
    for provider in providers:
        if not adapter.apply_provider(workspace, provider):
            providers_ready = False
    if not providers_ready:
        return False
    sandboxes_ready = True
    for sandbox in sandboxes:
        if not adapter.apply_sandbox(workspace, sandbox):
            sandboxes_ready = False
    return sandboxes_ready


def validate_profiles(profiles, known_profiles=(), governed=False):
    """Catch mistakes before anything touches the gateway.

    governed: the gateway takes its provider profiles from the governance
    interceptor, which may serve profiles the installer does not ship
    (overrides/governance-profiles). A type that is neither built-in nor
    shipped is then checked against the live catalog at apply time
    (ProfileApplier.adopt_governed_profiles) instead of refused here."""
    errors = []
    seen = {}
    for profile, ws in enabled_workspaces(profiles):
        where = f"{profile.name}/{ws.name}"
        if not NAME_RE.match(ws.name) or len(ws.name) > OPENSHELL_NAME_LIMIT:
            errors.append(f"{where}: workspace name must be a DNS label of at most {OPENSHELL_NAME_LIMIT} characters")
        if ws.name in seen:
            errors.append(f"{where}: workspace '{ws.name}' is also defined by profile {seen[ws.name]}")
        seen[ws.name] = profile.name
        provider_names = [p.name for p in ws.providers if p.enabled]
        provider_types = {p.name: p.type for p in ws.providers if p.enabled}
        if len(provider_names) != len(set(provider_names)):
            errors.append(f"{where}: duplicate provider names")
        for p in ws.providers:
            if not p.enabled:
                continue
            if not isinstance(p.credential_free, bool):
                errors.append(f"{where}: provider '{p.name}' credentialFree must be a boolean")
            elif p.credential_free:
                # A keyless provider is an attachment to a governed service
                # (an in-cluster MCP Service): no key, no model, and a type
                # that is a live governance profile, not a built-in type.
                for label, value in (("name", p.name), ("type", p.type)):
                    if not NAME_RE.match(value or "") or len(value) > OPENSHELL_NAME_LIMIT:
                        errors.append(f"{where}: keyless provider {label} must be a "
                                      f"DNS label of at most {OPENSHELL_NAME_LIMIT} characters")
                if p.type in PROVIDER_CRED_MAP:
                    errors.append(f"{where}: provider '{p.name}' credentialFree cannot disable "
                                  f"the credential requirement of built-in type '{p.type}'")
                if p.credential_secret:
                    errors.append(f"{where}: provider '{p.name}' credentialFree cannot be "
                                  "combined with credentialSecret")
                if (p.model or p.nemoclaw_provider or p.model_secret_key or p.base_url_secret_key
                        or p.base_url or p.inference_timeout):
                    errors.append(f"{where}: keyless provider '{p.name}' cannot be combined "
                                  "with model/inference settings")
            if governed and p.name != p.type:
                # OpenShell 0.1.2's governance interceptor validates a new
                # sandbox's providers by comparing each provider *name* with
                # the vended profile ids (examples/governance-interceptor,
                # providers_are_managed): a provider named differently from
                # its type is refused at sandbox create with "sandbox
                # providers may only use vended provider profiles". Found
                # live; refuse it here, with the reason, instead.
                errors.append(f"{where}: provider '{p.name}' must be named after its type "
                              f"'{p.type}' (the governance interceptor checks sandbox providers "
                              "by profile id, so name and type must match)")
            if (not p.credential_free and p.type not in PROVIDER_CRED_MAP
                    and p.type not in known_profiles):
                if not governed:
                    errors.append(f"{where}: provider '{p.name}' has unsupported type '{p.type}' "
                                  "(no built-in type and no shipped provider profile)")
                elif not NAME_RE.match(p.type or "") or len(p.type) > OPENSHELL_NAME_LIMIT:
                    errors.append(f"{where}: provider '{p.name}' type must be a DNS label of at "
                                  f"most {OPENSHELL_NAME_LIMIT} characters (a governance profile id)")
            if not p.credential_secret and not p.credential_free:
                errors.append(f"{where}: provider '{p.name}' has no credentialSecret")
            elif p.credential_secret and not SECRET_NAME_RE.match(p.credential_secret):
                errors.append(f"{where}: provider '{p.name}' has an invalid credentialSecret name")
            if not SECRET_KEY_RE.match(p.credential_secret_key or ""):
                errors.append(f"{where}: provider '{p.name}' has an invalid credentialSecretKey")
            for field_name, value in (("baseUrlSecretKey", p.base_url_secret_key),
                                      ("modelSecretKey", p.model_secret_key)):
                if value and not SECRET_KEY_RE.match(value):
                    errors.append(f"{where}: provider '{p.name}' has an invalid {field_name}")
            if p.base_url_secret_key and p.type not in BASE_URL_CONFIG_KEYS:
                errors.append(f"{where}: provider '{p.name}' of type '{p.type}' does not take a base URL "
                              f"(supported: {', '.join(sorted(BASE_URL_CONFIG_KEYS))})")
            if p.inference_timeout < 0:
                errors.append(f"{where}: provider '{p.name}' has a negative inferenceTimeout")
            if p.refresh_strategy and p.refresh_strategy != "oauth2_refresh_token":
                errors.append(f"{where}: provider '{p.name}' has unsupported refresh strategy '{p.refresh_strategy}'")
            if p.credentials_spec:
                if not isinstance(p.credentials_spec, dict):
                    errors.append(f"{where}: provider '{p.name}' credentials must be a mapping of "
                                  "the profile's credential name to {secretKey[, title]}")
                elif p.credential_free:
                    errors.append(f"{where}: keyless provider '{p.name}' cannot have credentials")
                else:
                    for cname, entry in p.credentials_spec.items():
                        if not CREDENTIAL_NAME_RE.match(str(cname)):
                            errors.append(f"{where}: provider '{p.name}' credential '{cname}' is "
                                          "not a valid credential name")
                        if not isinstance(entry, dict) or not SECRET_KEY_RE.match(
                                str(entry.get("secretKey", ""))):
                            errors.append(f"{where}: provider '{p.name}' credential '{cname}' "
                                          "needs a valid secretKey")
                        elif set(entry) - {"secretKey", "title"}:
                            errors.append(f"{where}: provider '{p.name}' credential '{cname}' has "
                                          "unknown keys "
                                          f"{', '.join(sorted(set(entry) - {'secretKey', 'title'}))}")
        sandbox_names = set()
        for s in ws.sandboxes:
            if not s.enabled:
                continue
            if s.name in sandbox_names:
                errors.append(f"{where}: duplicate sandbox '{s.name}'")
            sandbox_names.add(s.name)
            if len(s.name) > OPENSHELL_NAME_LIMIT or not NAME_RE.match(s.name):
                errors.append(f"{where}: sandbox name '{s.name}' must be a DNS label of at most {OPENSHELL_NAME_LIMIT} characters")
            if s.type not in SANDBOX_TYPES:
                errors.append(f"{where}: sandbox '{s.name}' has unsupported type '{s.type}'")
            for ref in s.providers:
                if ref not in provider_names:
                    errors.append(f"{where}: sandbox '{s.name}' uses provider '{ref}' which is not an enabled provider in this workspace")
            if s.type in ("openclaw", "nemoclaw") and not provider_names:
                errors.append(f"{where}: {s.type} sandbox '{s.name}' needs at least one provider")
            if s.inference:
                errors += [f"{where}: sandbox '{s.name}' {p}"
                           for p in sandbox_inference_problems(
                               s, provider_types, {p.name: p.type for p in ws.providers})]
            if not isinstance(s.env, dict):
                errors.append(f"{where}: sandbox '{s.name}' env must be a mapping of NAME to "
                              "{value} or {secret, secretKey}")
            else:
                for name, src in s.env.items():
                    errors += [f"{where}: sandbox '{s.name}' env '{name}' {problem}"
                               for problem in sandbox_env_problems(name, src)]
    if errors:
        raise InstallerError("invalid profiles:\n  - " + "\n  - ".join(errors))


# Match OpenShell's environment-name and per-value size constraints.
ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


CREDENTIAL_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]*$")


ENV_VALUE_LIMIT = 8192


SANDBOX_ENV_KEYS = {"value", "title"}


INPUT_KEYS = {"secretKeyRef", "default", "required", "title"}


def secret_ref(src):
    """(name, key) of a {secretKeyRef: {name, key}} input, or None."""
    ref = src.get("secretKeyRef") if isinstance(src, dict) else None
    if not isinstance(ref, dict):
        return None
    return str(ref.get("name", "")), str(ref.get("key", ""))


def secret_ref_problems(src):
    ref = secret_ref(src)
    if ref is None:
        return ["needs secretKeyRef: {name, key}"]
    out = []
    if not SECRET_NAME_RE.match(ref[0]):
        out.append("secretKeyRef.name must be a valid Secret name")
    if not SECRET_KEY_RE.match(ref[1]):
        out.append("secretKeyRef.key must be a valid Secret key")
    if set(src["secretKeyRef"]) - {"name", "key"}:
        out.append("secretKeyRef takes only name and key")
    return out


INFERENCE_KEYS = {"providerRef", "protocol", "baseUrl", "model", "models", "timeoutSeconds"}


# A profile controls allowed credential destinations; the protocol controls
# agent onboarding independently of a governed provider's custom profile name.
INFERENCE_PROTOCOLS = {"openai", "anthropic"}


PROVIDER_PROTOCOLS = {"openai": "openai", "codex": "openai", "nvidia": "openai",
                      "build": "openai", "anthropic": "anthropic", "claude-code": "anthropic"}


def check_env_value(value):
    """A value OpenShell accepts for `--env`: one line, at most 8 KiB. The
    value is not echoed (it may come from a Secret)."""
    if "\n" in value or "\r" in value or "\0" in value:
        raise ValueError("value must be a single line")
    if len(value.encode()) > ENV_VALUE_LIMIT:
        raise ValueError(f"value is longer than {ENV_VALUE_LIMIT} bytes")
    return value


def sandbox_env_problems(name, src):
    """What is wrong with one `env:` entry of a sandbox ([] when fine)."""
    out = []
    if not ENV_NAME_RE.match(str(name)):
        out.append("is not a valid variable name ([A-Za-z_][A-Za-z0-9_]*)")
    elif str(name).startswith("OPENSHELL_"):
        out.append("is reserved by OpenShell (OPENSHELL_*)")
    elif name in set(PROVIDER_CRED_MAP.values()):
        out.append("is a provider credential variable; credentials go on a provider, "
                   "the agent can read sandbox env")
    elif name in set(BASE_URL_CONFIG_KEYS.values()) or name in ("MODEL", "OPENCLAW_MODEL",
                                                               "NEMOCLAW_MODEL"):
        out.append("is an inference setting; set it in the sandbox's inference: block")
    if isinstance(src, dict) and ("secretKeyRef" in src or "default" in src):
        # A value from a Secret would travel in `sandbox create --env`'s argv
        # and be readable by every process in the sandbox (review, P1):
        # secrets go on a provider, whose profile the gateway injects.
        return out + ["must be a literal ({value: ...}); a value from a Secret belongs on a "
                      "provider, not in sandbox env (the agent and argv could read it)"]
    if not isinstance(src, dict) or "value" not in src:
        return out + ["needs {value: ...}"]
    unknown = sorted(set(src) - SANDBOX_ENV_KEYS)
    if unknown:
        out.append(f"has unknown keys {', '.join(unknown)}")
    if isinstance(src["value"], bool) or not isinstance(src["value"], (str, int, float)):
        out.append("value must be a string (quote it)")
    else:
        try:
            check_env_value(str(src["value"]))
        except ValueError as exc:
            out.append(f"value: {exc}")
    return out


def input_problems(src, kinds=(str,)):
    """What is wrong with one typed input (a literal or {secret, secretKey,
    default?, required?, title?}); [] when fine."""
    if not isinstance(src, dict):
        return [] if isinstance(src, kinds) and not isinstance(src, bool) else [
            "must be a string or {secretKeyRef: {name, key}, ...}"]
    out = []
    unknown = sorted(set(src) - INPUT_KEYS)
    if unknown:
        out.append(f"has unknown keys {', '.join(unknown)}")
    out += secret_ref_problems(src)
    if "required" in src and not isinstance(src["required"], bool):
        out.append("required must be true or false")
    if "default" in src and (isinstance(src["default"], bool)
                             or not isinstance(src["default"], kinds)):
        out.append("default must be a string")
    return out


def inference_protocol(spec, provider_type):
    """The protocol an `inference:` block uses: its own `protocol`, else the
    one the provider's type implies ("" when neither says)."""
    return spec.get("protocol") or PROVIDER_PROTOCOLS.get(provider_type or "", "")


def sandbox_inference_problems(sb, provider_types, declared_provider_types=None):
    """What is wrong with a sandbox's `inference:` block ([] when fine).
    `provider_types` maps the workspace's enabled provider names to their
    types."""
    spec = sb.inference
    provider_names = provider_types
    if not isinstance(spec, dict):
        return ["inference must be a mapping"]
    out = []
    unknown = sorted(set(spec) - INFERENCE_KEYS)
    if unknown:
        out.append(f"inference has unknown keys {', '.join(unknown)}")
    ref = spec.get("providerRef")
    if not ref:
        out.append("inference needs providerRef (the provider whose credential it uses)")
    elif ref not in provider_names:
        out.append(f"inference providerRef '{ref}' is not an enabled provider in this workspace")
    elif ref not in sb.providers:
        out.append(f"inference providerRef '{ref}' is not in the sandbox's providers")
    protocol = inference_protocol(spec, provider_types.get(ref or ""))
    if "protocol" in spec and spec["protocol"] not in INFERENCE_PROTOCOLS:
        out.append(f"inference protocol must be one of {', '.join(sorted(INFERENCE_PROTOCOLS))}")
    elif not protocol and ref in provider_names:
        out.append(f"inference needs protocol ({' | '.join(sorted(INFERENCE_PROTOCOLS))}): "
                   f"provider type '{provider_types[ref]}' does not imply one")
    if "model" not in spec:
        out.append("inference needs model")
    model = spec.get("model")
    if model == "" or (isinstance(model, dict) and not model.get("default")
                       and not model.get("required", "default" not in model)):
        out.append("inference model must be non-empty: use a non-empty default or required: true")
    for key in ("baseUrl", "model"):
        if key in spec:
            out += [f"inference {key} {p}" for p in input_problems(spec[key])]
    models = spec.get("models", {})
    if not isinstance(models, dict):
        out.append("inference models must be a mapping of provider names to model inputs")
    else:
        declared = declared_provider_types if declared_provider_types is not None else provider_types
        if models and sb.type != "openclaw":
            out.append("inference models is supported only for openclaw sandboxes")
        for name, model in models.items():
            if name not in declared:
                out.append(f"inference models names unknown provider '{name}'")
            elif declared[name] not in ("openai", "anthropic"):
                out.append(f"inference models '{name}' needs a native OpenAI or Anthropic provider")
            out += [f"inference models '{name}' {p}" for p in input_problems(model)]
            if model == "" or (isinstance(model, dict) and not model.get("default")
                              and not model.get("required", "default" not in model)):
                out.append(f"inference models '{name}' must be non-empty")
    if "timeoutSeconds" in spec:
        out += [f"inference timeoutSeconds {p}"
                for p in input_problems(spec["timeoutSeconds"], (str, int))]
    return out


def harness_from_plan(data):
    raw = data.get("harness") or {}
    bundles = {}
    for name, b in (raw.get("bundles") or {}).items():
        bundles[name] = HarnessBundle(
            name=b["name"], agent=b["agent"], digest=b["digest"], files=b["files"])
    return {"bundles": bundles}


def profiles_from_plan(data):
    profiles = []
    for p in data["profiles"]:
        workspaces = []
        for w in p["workspaces"]:
            workspaces.append(Workspace(
                name=w["name"], enabled=w["enabled"], description=w["description"],
                providers=[Provider(**x) for x in w["providers"]],
                sandboxes=[Sandbox(**x) for x in w["sandboxes"]]))
        profiles.append(Profile(name=p["name"], workspaces=workspaces))
    return profiles


__all__ = (
    'API_VERSION', 'NAME_RE', 'SECRET_NAME_RE', 'SECRET_KEY_RE', 'OPENSHELL_NAME_LIMIT',
    'PROVIDER_CRED_MAP', 'NEMOCLAW_PROVIDER_MAP', 'nemoclaw_provider', 'profile_credential_envs',
    'profile_credentials', 'profile_all_credential_envs', 'profile_credential_env', 'credential_env_name',
    'SANDBOX_TYPES', 'BASE_URL_CONFIG_KEYS', 'InstallerError', 'Provider', 'Sandbox', 'Workspace',
    'Profile', 'HarnessBundle', 'read_profile_files', '_yaml', 'parse_profiles', 'enabled_workspaces',
    'validate_profiles', 'ENV_NAME_RE', 'CREDENTIAL_NAME_RE', 'ENV_VALUE_LIMIT', 'SANDBOX_ENV_KEYS',
    'INPUT_KEYS', 'secret_ref', 'secret_ref_problems', 'INFERENCE_KEYS', 'INFERENCE_PROTOCOLS',
    'PROVIDER_PROTOCOLS', 'check_env_value', 'sandbox_env_problems', 'input_problems',
    'inference_protocol', 'sandbox_inference_problems', 'harness_from_plan', 'profiles_from_plan',
    'validate_profile_document', 'apply_workspace_sequence',
)
