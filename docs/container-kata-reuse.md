# Kubernetes backend reuse inventory

Reviewed source: [`codex-saw-k8s` at `5fe6a3b`](https://github.com/validatedpatterns-sandbox/secure-agent-workspace/tree/5fe6a3bc22ae34aa739d0f10bfc2bd5f48252d57).
Implementation base: current SAW `c9691be3ff0a9a2dde4fee91514b5215bbcb9275`.
Implementation branch: `dev/container-kata-deployment`. Review date: 2026-11-04.

This is the B0 inventory for the [implementation plan](container-kata-implementation-plan.md).
It records candidates, not completed ports or runtime qualification. No code from
this older branch has been copied into the initial deployment-mode validation
change. Current VM manifests remain the regression reference.

## Commit decisions

The reviewed branch has ten unique commits relative to current main. Do not
cherry-pick the initial feature commit wholesale: it also changes the old VM path,
credentials and installation workflow. Each selected function/template needs
current-version tests and a new-path/evidence entry below before being called ported.

| Source commit | Change | Decision for current SAW |
| --- | --- | --- |
| `1407f7763b10a5035d5134e6494ecbb707818161` | Initial Codex VM/Kubernetes backend | Adapt gateway chart, dependency packaging and dispatch concepts; discard obsolete VM changes, privileged combined topology and direct credential copying |
| `54184acc04182a20f8d04a0222534605b7ba2275` | Keycloak identities and shell status fields | Adapt issuer/subject ownership and machine-identity separation to current auth and retained-secret lifecycle |
| `a607a2c813f518a822f9e2ff9b5ee8742e817aef` | Gateway OIDC, provisioning and forwarding auth | Adapt protocol sequence; replace 0.0.116 metadata/token handling, renewal behavior and provisioning script |
| `589127e8d6d68034e5f15dd93677128598fb05ca` | Shell API, SSH proxy and configuration | Candidate connection descriptor/transport helpers for current SAW CLI; no competing Codex-only lifecycle |
| `42cc072903b561878576da0354469917c2a0d2eb` | Desktop SSH registration | Optional later feature; not required for VM feature parity or initial container delivery |
| `ba295741be21409eadb3628a00a2e172d23381b7` | Hardcoded Codex sandbox/approval settings | Drop as a default; review each agent's supported security model explicitly |
| `7f39be4a274014607ffb31de236af400639a2832` | Shell authentication error handling | Adapt clean stderr/interactive-login separation with current CLI tests |
| `82f14a3e0bf79a7bb59cd92aed85e01766ddcd98` | Imperative Keycloak client bootstrap | Reference identity dependencies only; use current declared ownership and avoid deployment-environment credential writes |
| `b72232d8f6623d8400e203ec5ba4d8f347e9f86c` | Setup and access documentation | Rewrite for current architecture; do not copy old commands as supported workflows |
| `5fe6a3bc22ae34aa739d0f10bfc2bd5f48252d57` | Regenerate existing Keycloak client secrets | Retain the retry/recovery problem as a test case; do not rotate retained credentials on ordinary reconcile |

Commit messages describe author intent. They are not proof that the stated security,
latency or resource-use claims were tested. The implementation review found gaps
between documentation and actual lifecycle handlers.

## Candidate source-to-destination map

All source paths below are relative to the reviewed commit. Destinations remain
proposed until implementation; record the actual commit and tests when each port lands.

| Source | Proposed destination | Adaptation and required evidence | Port status |
| --- | --- | --- | --- |
| `charts/openshell-saw-kubernetes/templates/{statefulset,service-gateway,route-gateway,configmap-gateway}.yaml` | Separate `charts/openshell-saw-kubernetes` | Reimplemented for pinned current stock config, split Pods and retained identity; old templates not copied | Offline render foundation; live restart/parity pending |
| `charts/agent-sandbox` | `charts/agent-sandbox` | New locked stock v1.0.9 manifest/digest, ownership and API checks; old version not copied | Offline dependency chart; live qualification pending |
| `services/saw-codex-api/controller.py` | Shared SAW request/reconciler interfaces | Port selected ordering/dispatch helpers only; generation-aware recovery, retention and full stop/start tests | Pending |
| `services/saw-codex-api/{app.py,auth.py,k8s.py,keycloak.py}` | Current SAW auth/status/access integration | Issuer+subject+session-UID binding, current OIDC/PKI, trusted credential boundary; multi-user negative tests | Pending |
| `cli/src/codex_saw/{openshell_adapter.py,ssh.py}` | Current SAW CLI access adapters | Current protocol, isolated temporary configuration, no secret output; auth expiry/transport tests | Pending |
| `charts/openshell-saw-kubernetes/templates/job-provision.yaml` | `kubernetes-runtime/saw_kubernetes` | New stock-API adapter; no copied provisioning shell, direct key arguments or ignored failures | Generic subset offline-tested, including generated protobuf; full profiles/deployment pending |
| `charts/saw-bom/profiles/codex` and its image recipe | Optional current SAW agent profile | Published immutable image, governance/tool-gate/harness contract and real inference | Pending |
| `tests/test-access-control.sh`, `tests/test-multiuser-isolation.sh` | Backend-aware acceptance harness | Existing tests exercise the older VM path; add container and Kata coverage with safe cleanup | Pending |

## First preparatory change

The initial implementation adds `deployment.mode` validation to the direct
`openshell-saw` chart and the parent `saw-users` chart:

- Omission remains `vm`; explicit `vm` renders the same resources.
- `container`, `kata` and `confidential` fail clearly while unimplemented.
- Invalid types, unknown modes and misspelled deployment fields fail rendering.
- Parent validation checks defaults and per-user overrides before emitting child
  Applications. This prevents an unsupported request from silently becoming a VM.
- The direct chart also validates when Helm JSON-schema validation is disabled.

This is configuration groundwork, not a working Kubernetes backend. It adds no
RuntimeClass, Kubernetes gateway, controller, images or cluster resources. B1 stays
open until its complete chart and runtime interfaces exist and pass their gates.

## Offline verification receipt — 2026-11-04

With Helm and the repository's Python test dependencies installed:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  tests/charts/test_openshell_saw_chart.py \
  tests/charts/test_saw_users_chart.py
```

Result: **241 passed**. This covers existing chart behavior and new mode validation,
including malformed inputs, per-user precedence and disabled schema validation.

A separate local render comparison against pinned upstream `c9691be` found equal
parsed manifests for all four cases: default VM (28 objects), direct-credential VM
(19), VM with live inputs (28), and two-user GitOps (8). The comparison extracted
only the two baseline charts into temporary storage and removed them afterward.
No image pulls, builds, cluster discovery, mutations or runtime tests were performed.

## Subsequent offline foundations — 2026-11-04

These additions use the pinned current APIs; they do not import the older
Kubernetes backend or patch OpenShell/Kata/Agent Sandbox:

| Path | Implemented scope | Remaining gate |
|---|---|---|
| [`charts/openshell-saw-kubernetes`](../charts/openshell-saw-kubernetes/README.md) | Stock gateway configuration, retained state references, restricted RBAC, explicit network/trust inputs | Identity bootstrap, trusted namespace/proxy and reconciler integration, live runtime |
| [`charts/agent-sandbox`](container-runtime-dependencies.md) | Pinned stock core dependency and optional GitOps application | Live API/lifecycle/SCC qualification |
| [`charts/saw-runtime-policies`](../charts/saw-runtime-policies/README.md) | Native VAP runtime/identity constraints and supervisor ANP | CEL validation, policy realization and negative traffic tests |
| [`kubernetes-runtime`](../kubernetes-runtime/README.md) | Generic profile compiler, retained attachment verification, serialized/recoverable API reconciliation, generated protobuf tests | Full agent/harness/tool/UI/provider adapters and deployed controller |
| RHDH portal, templates and profile generator | Admin mode allowlist, VM default, immutable mode, reject unsupported creation before Vault writes | New backend readiness/lifecycle wiring and qualification before enabling choices |

Initial `kata` means **ordinary supervisor plus Kata workload**. The native
policies require this placement; no mutation controller is installed. The
[supervisor RuntimeClass proposal](proposals/openshell-supervisor-runtimeclass.md)
documents both a future native admission option and an illustrative upstream
enhancement, neither applied. No OpenShell derivative image is built.

Parent provisioning still refuses new modes while integration is incomplete.
Live qualification begins with the unchanged stock SAW VM baseline. An offline
render, generic Ready response or portal selector does not establish full parity.

### Foundation verification receipt

From the repository root, with Helm and the Python test dependencies available:

```sh
CI=true make lint-static PYTHON=python3
python3 -m pytest -q -p no:cacheprovider \
  tests/charts/test_openshell_saw_chart.py tests/charts/test_saw_users_chart.py \
  tests/charts/test_agent_sandbox_chart.py tests/charts/test_saw_runtime_policies.py \
  tests/charts/test_saw_kubernetes_chart.py tests/kubernetes_runtime \
  tests/scripts/test_profile_catalog_automation.py
python3 -m pytest -q -p no:cacheprovider tests/portal/test_portal.py \
  tests/charts/test_openshell_rhdh_chart.py tests/scripts/test_profile_catalog_automation.py
```

Results on 2026-11-04: static lint passed; first suite **425 passed**, with the
optional generated-SDK module skipped; portal/RHDH/catalog suite **201 passed**.
The [explicit stock SDK runner](../kubernetes-runtime/README.md#stock-protobuf-and-generated-stub-test)
separately passed **75 tests**, including nine wire/stub tests. These suites overlap;
their counts are not an aggregate unique-test count. Gateway and policy review
also checked the pinned stock source; no upstream checkout modifications occurred.

The changed Make entry-point tests passed. Fourteen unrelated Make-interface
cases fail identically on the workstation and a minimal `c9691be` baseline:
nine require newer GNU Make `--eval`; three require Bash `mapfile`; two hit
Bash 3.2's empty-array behavior under `set -u` in the existing image-mirror script.
Use the repository's Linux CI for the complete interface suite; these are not
live OpenShift failures or evidence of a passing baseline installation.

No cluster calls, image pulls or guest builds were made for these foundations.
Temporary protobuf/compiler and test artifacts are disposable; keep source and
sanitized test receipts. Cluster admission, networking, runtime and full SAW E2E
remain pending.
