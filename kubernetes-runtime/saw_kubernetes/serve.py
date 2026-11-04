"""Run one retained controller for an administrator-defined workspace."""
import json
import os
from pathlib import Path
import signal

from .adapters import GrpcGateway, KubernetesResourceVerifier
from .boundary import verify
from .compiler import compile_profile_files, ContractError
from .controller import ConfigMapClient, Controller, Scope, NAME
from .reconcile import Reconciler


def main():
    os.umask(0o077)
    config = json.loads(Path("/config/controller.json").read_text())
    scope = Scope(config["namespace"], config["profile"], config["intent"], config["status"], config["ownerID"])
    service_account = Path("/var/run/secrets/kubernetes.io/serviceaccount")
    api = ConfigMapClient("https://kubernetes.default.svc", scope, service_account / "ca.crt", service_account / "token")
    def get(path):
        with api._open("GET", path) as response:
            return api._json(response)

    def read(kind, name, namespace=None):
        if not NAME.fullmatch(name):
            raise ContractError("invalid resource name")
        if kind == "namespace" and name == scope.namespace:
            return get("/api/v1/namespaces/" + name)
        if kind == "persistentvolumeclaim" and namespace == scope.namespace:
            return get(f"/api/v1/namespaces/{namespace}/persistentvolumeclaims/{name}")
        if kind == "runtimeclass" and config["mode"] == "kata":
            return get("/apis/node.k8s.io/v1/runtimeclasses/" + name)
        raise ContractError("resource outside controller scope")

    def boundary(plan):
        verify(config, plan, get)
    resources = KubernetesResourceVerifier(read, boundary)
    endpoint = f"https://{config['gateway']}-gateway.{scope.namespace}.svc:17670"
    gateway = GrpcGateway(endpoint, "/identity/ca.crt", "/identity/tls.crt", "/identity/tls.key")
    state = Path("/state")
    core = Reconciler(gateway, state / "core", resources)
    frontend = Controller(api, scope, state, compile_profile_files, core.reconcile, boundary)
    stopped = False
    def stop(signum, frame):
        nonlocal stopped
        stopped = True
    signal.signal(signal.SIGTERM, stop)
    try:
        frontend.run(stop=lambda: stopped)
    finally:
        gateway.close()


if __name__ == "__main__":
    main()

