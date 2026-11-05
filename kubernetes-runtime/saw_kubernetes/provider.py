"""Verify Kubernetes proxy bindings against the same shipped governance profiles as the VM."""
import re
from functools import lru_cache
from pathlib import Path

import yaml

from .core import shared

PROFILES = Path(shared.__file__).resolve().parents[1] / "provider-profiles"
SUPPORTED = {"openai", "nvidia", "slack", "gmail"}


@lru_cache(maxsize=4)
def document(kind):
    if kind not in SUPPORTED:
        raise ValueError("unsupported governed provider")
    return yaml.safe_load((PROFILES / (kind + ".yaml")).read_text())


def requirements(kind):
    doc = document(kind)
    slot, = doc["credentials"]
    hosts = sorted({e["host"] for e in doc["endpoints"]})
    return slot, hosts


def checked_marker(provider, bindings):
    """The plan carries only the public routing marker; keys remain in the proxy."""
    slot, _ = requirements(provider.type)
    expected = {"secret": provider.credential_secret, "key": provider.credential_secret_key,
                "type": provider.type, "refresh": bool(provider.refresh_strategy)}
    if (expected not in bindings or provider.credentials_spec or provider.base_url or provider.base_url_secret_key
            or provider.refresh_strategy not in ("", "oauth2_refresh_token") or provider.inference_timeout
            or (provider.type != "nvidia" and (provider.model or provider.nemoclaw_provider))
            or provider.model_secret_key):
        raise ValueError("provider configuration differs from enrolled proxy binding")
    if expected["refresh"] and (slot.get("refresh") or {}).get("strategy") != provider.refresh_strategy:
        raise ValueError("provider refresh is not supported by its governance profile")
    if not re.fullmatch(r"[a-z0-9-]+", expected["secret"]) or not re.fullmatch(r"[a-zA-Z0-9_-]+", expected["key"]):
        raise ValueError("invalid proxy marker reference")
    return {slot["env_vars"][0]: shared.credential_marker("saw-cred", expected["secret"], expected["key"])}


def check_policy(kind, credentials, policy):
    slot, hosts = requirements(kind)
    if (policy.get("markerPrefix") != "saw-cred" or sorted(policy["profiles"].get(kind, [])) != hosts or
            not set(hosts) <= set(policy["allowHosts"])):
        return False
    for binding in policy["bindings"]:
        if kind not in binding["providers"]:
            continue
        if set(binding["providers"]) - ({kind, "build"} if kind=="nvidia" else {kind}):
            continue
        marker = shared.credential_marker("saw-cred", binding["secret"], binding["key"])
        if credentials != {slot["env_vars"][0]: marker}:
            continue
        refresh = binding.get("refresh")
        if refresh:
            contract = slot.get("refresh", {})
            if (refresh.get("strategy") != contract.get("strategy") or
                    refresh.get("tokenURL") != contract.get("token_url") or
                    refresh.get("material") != {"clientID":"client_id", "clientSecret":"client_secret", "refreshToken":"refresh_token"}):
                return False
        return True
    return False
