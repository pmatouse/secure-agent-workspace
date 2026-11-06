#!/usr/bin/env python3
"""Render one OpenAI container owner from public site inputs and a reviewed boundary."""
import argparse
from ipaddress import IPv4Address, IPv4Network
import json
from pathlib import Path
import re
import subprocess
import sys
from uuid import UUID

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "kubernetes-runtime"))
from saw_kubernetes.boundary import fingerprint, objects

DNS_LABEL = r"[a-z0-9](?:[-a-z0-9]*[a-z0-9])?"
DIGEST = r"[0-9a-f]{64}"
CONTROLLER = "a4162dfe1529541fc23ed33f63a01e186b7793d6"
PROFILES = ("custom-inference", "data-science")
PRIVATE = ["0.0.0.0/8", "10.0.0.0/8", "100.64.0.0/10", "127.0.0.0/8",
           "169.254.0.0/16", "172.16.0.0/12", "192.168.0.0/16", "224.0.0.0/4", "240.0.0.0/4"]
FIELDS = set("owner subject issuer buildNamespace governanceNamespace networkPriority apiAddresses apiPorts issuerAddresses clusterCIDRs gatewayStorage historyStorage exchangeStorage controllerImage notebookImage keycloakNamespace keycloakAdminSecret".split())


def boundary_keys():
    return objects(dict(namespace="", trustedNamespace="", governanceNamespace="", gateway="", proxyPolicy=""))


def validate(inputs):
    if set(inputs) != FIELDS:
        raise ValueError("unexpected or missing site input fields: " + ", ".join(sorted(set(inputs) ^ FIELDS)))
    for name in ("owner", "buildNamespace", "governanceNamespace", "keycloakNamespace", "keycloakAdminSecret"):
        if not re.fullmatch(DNS_LABEL, inputs[name]) or len(inputs[name]) > (19 if name == "owner" else 63):
            raise ValueError("invalid " + name)
    for name in ("gatewayStorage", "historyStorage", "exchangeStorage"):
        if not re.fullmatch(DNS_LABEL + r"(?:\." + DNS_LABEL + ")*", inputs[name]):
            raise ValueError("invalid " + name)
    if not re.fullmatch(r"https://" + DNS_LABEL + r"(?:\." + DNS_LABEL + r")+/realms/[A-Za-z0-9_-]+", inputs["issuer"]):
        raise ValueError("expected a Keycloak HTTPS realm issuer")
    if str(UUID(inputs["subject"])) != inputs["subject"]:
        raise ValueError("expected a canonical lowercase owner UUID")
    if type(inputs["networkPriority"]) is not int or not 0 <= inputs["networkPriority"] <= 1000:
        raise ValueError("expected an AdminNetworkPolicy priority between 0 and 1000")
    for name, stream in (("controllerImage", "saw-runtime-controller"), ("notebookImage", "saw-openclaw-home")):
        repo = "image-registry.openshift-image-registry.svc:5000/" + inputs["buildNamespace"] + "/" + stream
        if not re.fullmatch(re.escape(repo) + "@sha256:" + DIGEST, inputs[name]):
            raise ValueError("expected a pinned " + stream + " digest in the declared build namespace")
    if any(not isinstance(inputs[k], list) or not inputs[k] for k in
           ("apiAddresses", "issuerAddresses", "clusterCIDRs", "apiPorts")):
        raise ValueError("explicit nonempty IPv4 topology required")
    if any(type(p) is not int or not 1 <= p <= 65535 for p in inputs["apiPorts"]):
        raise ValueError("invalid API port")


def validate_reference(reference):
    if set(reference) != set(boundary_keys()):
        raise ValueError("incomplete or unexpected boundary fields")
    for key, value in reference.items():
        if key == "publicCA":
            if value != "equals independent trusted proxy public CA":
                raise ValueError("invalid CA equality requirement")
        elif key.startswith("governance"):
            if not isinstance(value, dict) or set(value) != {"uid", "sha256"} or not re.fullmatch(DIGEST, value["sha256"]):
                raise ValueError("invalid governance approval: " + key)
            UUID(value["uid"])
        elif not re.fullmatch(DIGEST, value):
            raise ValueError("invalid boundary digest: " + key)


def host_rule(addresses, ports):
    return {"to": [{"ipBlock": {"cidr": str(IPv4Address(ip)) + "/32"}} for ip in addresses],
            "ports": [{"protocol": "TCP", "port": port} for port in ports]}


def validate_openai_data_science(data):
    """This demo boundary admits official OpenAI only; never approve a different BOM by accident."""
    workspaces = {}
    for name, content in data.items():
        if not name.startswith("profiles__data-science__"):
            raise ValueError("expected only the selected data-science profile in the rendered BOM")
        workspace, filename = name.rsplit("__", 1)
        workspaces.setdefault(workspace, {})[filename] = yaml.safe_load(content)
    found = False
    for workspace in workspaces.values():
        providers = {p["name"]: p for p in workspace.get("providers.yaml", {}).get("spec", {}).get("providers", [])
                     if p.get("enabled", True)}
        if any(p.get("type") != "openai" or p.get("credentialSecret") != "inference"
               or p.get("credentialSecretKey") != "api_key" for p in providers.values()):
            raise ValueError("data-science demo requires only enabled OpenAI providers using inference.api_key")
        for sandbox in workspace.get("sandbox.yaml", {}).get("spec", {}).get("sandboxes", []):
            if not sandbox.get("enabled", True):
                continue
            inference = sandbox.get("inference", {})
            attached = sandbox.get("providers", [])
            if (not attached or any(p not in providers for p in attached)
                    or inference.get("providerRef") not in attached
                    or inference.get("protocol") != "openai"
                    or inference.get("baseUrl") != "https://api.openai.com/v1"):
                raise ValueError("data-science demo requires explicit official OpenAI inference in every enabled sandbox")
            found = True
    if not found:
        raise ValueError("data-science BOM has no enabled sandboxes")


def render(inputs, reference, *, profile="custom-inference", controller_revision=CONTROLLER, bom_chart=None):
    validate(inputs)
    if profile not in PROFILES:
        raise ValueError("unsupported demo profile")
    if not re.fullmatch(r"[0-9a-f]{40}", controller_revision):
        raise ValueError("controller revision must be a full lowercase Git commit SHA")
    if reference is None:
        # Impossible comparison, including for the typed governance records.
        reference = dict.fromkeys(boundary_keys(), "awaiting independent review")
    else:
        validate_reference(reference)
    bom = subprocess.check_output(["helm", "template", "preflight", str(bom_chart or ROOT / "charts/saw-bom"),
        "--set", "profiles[0]=" + profile, "--set", "webSearch.enabled=false",
        "--set", "harnessEnabled=false",
        "--set-string", "imageOverrides.notebook=" + inputs["notebookImage"]], text=True)
    data = yaml.safe_load(bom)["data"]
    if profile == "data-science":
        validate_openai_data_science(data)
    digest = fingerprint(data)
    boundary = {"allowHosts": ["api.openai.com"], "reference": reference}
    if profile == "custom-inference":
        boundary["inferenceBaseURL"] = "https://api.openai.com/v1"
    excluded = [IPv4Network(c) for c in PRIVATE]
    for cidr in inputs["clusterCIDRs"]:
        network = IPv4Network(cidr)
        if not any(network.subnet_of(other) for other in excluded):
            excluded.append(network)
    fields = dict(inputs, reference=reference, bomDigest=digest, controllerRevision=controller_revision,
                  approvedProfiles={profile: digest},
                  profileImageOverrides={profile: {"notebook": inputs["notebookImage"]}},
                  profileBoundaries={profile: boundary},
                  governanceEndpoint="http://governance-interceptor." + inputs["governanceNamespace"] + ".svc:18081",
                  apiRule=host_rule(inputs["apiAddresses"], inputs["apiPorts"]),
                  issuerRule=host_rule(inputs["issuerAddresses"], [443]),
                  internetRule={"to": [{"ipBlock": {"cidr": "0.0.0.0/0", "except": list(map(str, excluded))}}],
                                "ports": [{"protocol": "TCP", "port": 443}]})

    def substitute(node):
        if isinstance(node, list):
            return [substitute(item) for item in node]
        if isinstance(node, dict):
            if set(node) == {"$input"}:
                return fields[node["$input"]]
            return {k: substitute(v) for k, v in node.items()}
        return node

    site = substitute(yaml.safe_load((HERE / "custom-site-defaults.yaml").read_text()))
    return {"portal": {"deploymentModes": ["vm", "container"], "containerSites": {inputs["owner"]: site}}}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--profile", choices=PROFILES, default="custom-inference")
    parser.add_argument("--controller-revision", default=CONTROLLER,
                        help="full Git commit matching the reviewed controller image build")
    parser.add_argument("--bom-chart", type=Path, default=ROOT / "charts/saw-bom",
                        help="exact site BOM chart deployed by GitOps; data-science must use the OpenAI site variant")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--reviewed-boundary", type=Path)
    mode.add_argument("--stage-review", action="store_true", help="render nonmatching approvals for initial inspection")
    args = parser.parse_args()
    try:
        result = render(yaml.safe_load(args.inputs.read_text()), json.loads(args.reviewed_boundary.read_text()) if args.reviewed_boundary else None,
                        profile=args.profile, controller_revision=args.controller_revision, bom_chart=args.bom_chart)
    except (KeyError, TypeError, ValueError, OSError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"site render failed: {exc}\n")
    print(yaml.safe_dump(result, sort_keys=False), end="")
