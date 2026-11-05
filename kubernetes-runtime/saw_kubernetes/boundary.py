"""Read-only checks of the administrator-approved OpenShift installation."""
import hashlib
import json


class BoundaryError(ValueError):
    pass


def fingerprint(value):
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(data.encode()).hexdigest()


def objects(config):
    ns = config["namespace"]
    trusted = config["trustedNamespace"]
    governance = config["governanceNamespace"]
    gateway = config["gateway"]
    policy = f"saw-{ns}-runtime"
    admission = "/apis/admissionregistration.k8s.io/v1"
    apps = "/apis/apps/v1/namespaces"
    net = "/apis/networking.k8s.io/v1/namespaces"
    core = "/api/v1/namespaces"
    return {
        "validation": (f"{admission}/validatingadmissionpolicies/{policy}", "spec"),
        "binding": (f"{admission}/validatingadmissionpolicybindings/{policy}", "spec"),
        "network": (f"/apis/policy.networking.k8s.io/v1alpha1/adminnetworkpolicies/{policy}-egress", "spec"),
        "deny": (f"{net}/{ns}/networkpolicies/{gateway}-default-deny", "spec"),
        "gatewayNetwork": (f"{net}/{ns}/networkpolicies/{gateway}-gateway", "spec"),
        "gateway": (f"{apps}/{ns}/statefulsets/{gateway}-gateway", "spec"),
        "gatewayService": (f"{core}/{ns}/services/{gateway}-gateway", "spec"),
        "gatewayConfig": (f"{core}/{ns}/configmaps/{gateway}-gateway-config", "data"),
        "governance": (f"{apps}/{governance}/deployments/governance-interceptor", "spec"),
        "governanceService": (f"{core}/{governance}/services/governance-interceptor", "spec"),
        "governancePolicy": (f"{core}/{governance}/configmaps/governance-interceptor-policy", "data"),
        "governanceProfiles": (f"{core}/{governance}/configmaps/governance-interceptor-profiles", "data"),
        "proxy": (f"{apps}/{trusted}/deployments/{gateway}-credential-proxy", "spec"),
        "proxyNetwork": (f"{net}/{trusted}/networkpolicies/{gateway}-credential-proxy", "spec"),
        "proxyPolicy": (f"{core}/{trusted}/configmaps/{config['proxyPolicy']}", "data"),
        "publicCA": (f"{core}/{ns}/configmaps/{gateway}-proxy-ca", "data"),
    }


def complete_list(get, path):
    response = get(path)
    if response.get("metadata", {}).get("continue") or not isinstance(response.get("items"), list):
        raise BoundaryError("IncompleteInventory")
    return response["items"]


def verify(config, plan, get):
    if (config["namespace"], config["namespaceUID"], config["ownerID"], config["mode"]) != (
            plan["namespace"], plan["namespaceUID"], plan["ownerID"], plan["mode"]):
        raise BoundaryError("WrongInstallation")
    refs = objects(config)
    if set(config["approved"]) != set(refs):
        raise BoundaryError("IncompleteApproval")
    observed = {}
    for key, (path, field) in refs.items():
        obj = get(path)
        meta = obj["metadata"]
        expected = config["approved"][key]
        if (meta.get("deletionTimestamp") or meta["uid"] != expected["uid"]
                or fingerprint(obj[field]) != expected["sha256"]):
            raise BoundaryError("ChangedBoundary:" + key)
        observed[key] = obj
    markers = {p["credentials"]["OPENAI_API_KEY"] for w in plan.get("workspaces", [])
               for p in w["providers"] if p.get("credentials")}
    if markers:
        policy = json.loads(observed["proxyPolicy"]["data"]["config.json"])
        if (policy["markerPrefix"] != "saw-cred" or policy["profiles"].get("openai") != ["api.openai.com"]
                or "api.openai.com" not in policy["allowHosts"]):
            raise BoundaryError("OpenAIProxyPolicyMismatch")
        approved_markers = {f"saw-cred.{b['secret']}.api_key" for b in policy["bindings"]
                            if b.get("key") == "api_key" and b.get("providers") == ["openai"]}
        if not markers <= approved_markers:
            raise BoundaryError("OpenAIProxyBindingMismatch")
    vap = observed["validation"]
    status = vap.get("status", {})
    if (status.get("observedGeneration") != vap["metadata"]["generation"]
            or "typeChecking" not in status or status["typeChecking"].get("expressionWarnings")):
        raise BoundaryError("AdmissionUnavailable")
    network = observed["network"]
    priority = network["spec"]["priority"]
    policies = complete_list(get, "/apis/policy.networking.k8s.io/v1alpha1/adminnetworkpolicies")
    if any(p["metadata"]["uid"] != network["metadata"]["uid"] and p["spec"]["priority"] <= priority
           for p in policies):
        raise BoundaryError("EarlierNetworkPolicy")
    nodes = complete_list(get, "/api/v1/nodes")
    zones = {n["metadata"]["name"] for n in nodes}
    realized = {c["type"].removeprefix("Ready-In-Zone-")
                for c in network.get("status", {}).get("conditions", [])
                if c["type"].startswith("Ready-In-Zone-") and c["status"] == "True"
                and c.get("reason") == "SetupSucceeded"}
    if not zones or not zones <= realized:
        raise BoundaryError("NetworkNotRealized")
    for key in ("gateway", "governance", "proxy"):
        obj = observed[key]
        status = obj.get("status", {})
        if (status.get("observedGeneration") != obj["metadata"]["generation"]
                or status.get("readyReplicas", 0) != obj["spec"]["replicas"]
                or status.get("updatedReplicas", 0) != obj["spec"]["replicas"]):
            raise BoundaryError("RolloutIncomplete:" + key)

