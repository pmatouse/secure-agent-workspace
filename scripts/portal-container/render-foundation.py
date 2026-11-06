#!/usr/bin/env python3
"""Emit GitOps resources for the container demo's shared prerequisites."""
import argparse
from pathlib import Path
import re
from urllib.parse import urlsplit

import yaml

ROOT = Path(__file__).resolve().parents[2]
CONTROLLER = "a4162dfe1529541fc23ed33f63a01e186b7793d6"
POLICY_CHART = "004b2340c08d82f0a6c14c739ddc25b6731b2be1"
LABEL = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("phase", choices=("build", "serve"))
    p.add_argument("--repo", required=True, help="HTTPS Git fork containing the reviewed source commits")
    p.add_argument("--build-namespace", required=True)
    p.add_argument("--governance-namespace", required=True)
    p.add_argument("--argo-namespace", default="vp-gitops")
    p.add_argument("--project", default="default")
    p.add_argument("--controller-revision", default=CONTROLLER,
                   help="reviewed full Git commit to build; select its resulting image digest in the site inputs")
    p.add_argument("--install-agent-sandbox", action="store_true", help="build phase only, on a cluster with no existing installation")
    p.add_argument("--governance-digest", help="serve phase only; actual sha256 digest of the completed governance build")
    a = p.parse_args()
    repo = urlsplit(a.repo)
    if repo.scheme != "https" or not repo.hostname or repo.username or repo.password or repo.query or repo.fragment:
        p.error("a public HTTPS fork URL is required")
    if any(not re.fullmatch(LABEL, n) for n in (a.build_namespace,a.governance_namespace,a.argo_namespace,a.project)):
        p.error("namespaces and project must be DNS labels")
    if not re.fullmatch("[0-9a-f]{40}", a.controller_revision):
        p.error("controller revision must be a full lowercase Git commit SHA")
    if a.phase == "serve" and (a.install_agent_sandbox or not re.fullmatch("sha256:[0-9a-f]{64}", a.governance_digest or "")):
        p.error("serve requires a reviewed governance image digest")
    if a.phase == "build" and a.governance_digest:
        p.error("digest selection belongs to the serve phase")

    def source(path, revision, values):
        return {"repoURL":a.repo,"path":path,"targetRevision":revision,"helm":{"valuesObject":values}}

    def app(name, ns, *sources):
        spec = {"project":a.project,"destination":{"server":"https://kubernetes.default.svc","namespace":ns},
                "syncPolicy":{"automated":{"prune":False,"selfHeal":True},"syncOptions":["CreateNamespace=true"]}}
        if len(sources) == 1:
            spec["source"] = sources[0]
        else:
            spec["sources"] = list(sources)
        return {"apiVersion":"argoproj.io/v1alpha1","kind":"Application",
                "metadata":{"name":name,"namespace":a.argo_namespace},"spec":spec}

    build = a.build_namespace
    if a.phase == "build":
        stream = {"apiVersion":"image.openshift.io/v1","kind":"ImageStream",
                  "metadata":{"name":"saw-runtime-controller","namespace":build}}
        controller = {"apiVersion":"build.openshift.io/v1","kind":"BuildConfig",
            "metadata":{"name":"saw-runtime-controller-" + a.controller_revision[:7],"namespace":build},
            "spec":{"source":{"type":"Git","git":{"uri":a.repo,"ref":a.controller_revision}},
                    "strategy":{"type":"Docker","dockerStrategy":{"dockerfilePath":"kubernetes-runtime/Containerfile"}},
                    "output":{"to":{"kind":"ImageStreamTag","name":"saw-runtime-controller:"+a.controller_revision[:12]}},
                    "triggers":[{"type":"ConfigChange"}]}}
        policy = source("image-builder-charts/helm/governance-interceptor-image","fb158a7a0b4a1c4884bbe08d82dd7379d42f3421",
            {"source":{"git":{"uri":"https://github.com/NVIDIA/OpenShell.git","ref":"6648bd0c290efbc41ba131ee9831ee45cd431f94"}},
             "build":{"name":"governance-interceptor-fb158a7","configChangeTrigger":True,
                      "builderImage":"docker.io/library/rust@sha256:4ec71e955e6c08aeb238885083222ddff79d82eb87654a96c76e38e94da1a53b",
                      "runtimeImage":"registry.access.redhat.com/ubi9-micro@sha256:7325ffb45d8401b227033dc26c567e138c919731ed2f8119e921ddba71835f87"},
             "output":{"imageStreamTag":"governance-interceptor:kubernetes-fb158a7"}})
        notebook = source("image-builder-charts/helm/openshift-home-access","0e6912d55ac16ea1788b26b8d6c2fde8df47d0b0",
            {"images":[{"name":"saw-openclaw-home","from":"quay.io/aipcc/base-images/agentic/openclaw@sha256:896d1526ee29b53167034ba65d1c758c8da777f441ed094e19f3bcf6d7445c61","imageUser":"sandbox:sandbox"}]})
        docs = [stream,controller,app("saw-container-policy-build",build,policy),app("saw-container-notebook-build",build,notebook)]
        if a.install_agent_sandbox:
            docs.append(app("saw-agent-sandbox","agent-sandbox-system",
                        source("charts/agent-sandbox","e16968b8e37f1b4cb96597149bb3218792b34e06",{"enabled":True})))
    else:
        gov = a.governance_namespace
        image = f"image-registry.openshift-image-registry.svc:5000/{build}/governance-interceptor@{a.governance_digest}"
        policy = source("charts/governance-policy", POLICY_CHART, {})
        interceptor = source("charts/governance-interceptor", POLICY_CHART,
            {"image":image,"gatewayEndpoint":"","sawNamespaceLabel":{"key":"saw.redhat.com/unused-vm-selector","value":"no-vm-qualification"}})
        for child in (policy, interceptor):
            child["helm"]["releaseName"] = "saw-container-governance"
        profile = yaml.safe_load((ROOT/"overrides/governance-profiles/custom-inference.yaml").read_text())
        endpoint, = profile["endpoints"]
        endpoint.update(host="api.openai.com",port=443)
        docs = [{"apiVersion":"v1","kind":"ConfigMap","metadata":{"name":"governance-interceptor-extra-profiles","namespace":gov},
                 "data":{"custom-inference.yaml":yaml.safe_dump(profile,sort_keys=False)}},
                app("saw-container-governance",gov,policy,interceptor)]
        if gov != build:
            docs.append({"apiVersion":"rbac.authorization.k8s.io/v1","kind":"Role","metadata":{"name":"pull-container-governance","namespace":build},
                         "rules":[{"apiGroups":["image.openshift.io"],"resources":["imagestreams/layers"],"resourceNames":["governance-interceptor"],"verbs":["get"]}]})
            docs.append({"apiVersion":"rbac.authorization.k8s.io/v1","kind":"RoleBinding","metadata":{"name":"pull-container-governance","namespace":build},
                         "roleRef":{"apiGroup":"rbac.authorization.k8s.io","kind":"Role","name":"pull-container-governance"},
                         "subjects":[{"kind":"ServiceAccount","namespace":gov,"name":"default"}]})
    print(yaml.safe_dump_all(docs, sort_keys=False), end="")


if __name__ == "__main__":
    main()
