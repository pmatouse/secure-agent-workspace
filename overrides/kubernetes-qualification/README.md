# glmhg Kubernetes foundation qualification

The site overlay installs the stock Agent Sandbox controller, an isolated stock
OpenShell gateway, its retained identities, a SAW credential proxy and governance
service, and a SAW reconciler for an ordinary container workspace. Argo owns the
manifests and pinned image builds. The RHDH VM deployment is separate.

The Agent Sandbox binary/CRD and the gateway certificate generator are
stock. The bootstrap retains admin identity in `saw-k8s-trusted`; runtime leaf
identities go to `saw-k8s-test`. Both namespaces bind one installation UUID and
are retained on Argo prune/application deletion. The bootstrap network policy
permits only the discovered Kubernetes API and cluster DNS destinations.

Preflight on 2026-11-04 found no existing Sandbox CRD, controller deployment or
controller ClusterRole/Binding. Repeat the inventory before activation; do not
install a second owner. API Service/backend and DNS values are cluster-specific.
The baseline VMs remain in their existing namespaces on control-plane nodes.

The existing site's `clusterGroup.applications` selects this Kustomize path:

```yaml
saw-kubernetes-foundation:
  name: saw-kubernetes-foundation
  namespace: openshell-agents
  path: overrides/kubernetes-qualification
  kustomize: true
```

Require each child Application to reach Synced/Healthy and the identity hook to
succeed. Merely syncing the parent is not a dependency-health gate. Check that
the Sandbox CRD is Established and the stock controller is Available, and record
only Secret UIDs/public certificate fingerprints for repeat-sync checks—never
Secret values. Then qualify the separate gateway/policy/reconciler integration.
This foundation alone is not evidence that container or Kata SAW works.

Activation follows successful baseline and disposable-VM inference/owner/egress
tests. It runs independently of the remaining portal dashboard cold pull and
update/delete acceptance. Those tests remain required; no container/Kata agent
is enabled by installing these dependencies. The ownership inventory was repeated
before activation and found no matching CRD, namespaces or controller RBAC.


The policy build Application pins the SAW recipe, upstream OpenShell source,
and builder/runtime image digests. `ConfigChange` starts the OpenShift build
through Argo; no manual build command is required. Output stays in the internal
registry under `saw-k8s-build/governance-interceptor:kubernetes-004b234`. This is
an unqualified candidate: no existing VM policy Deployment references it. Require
a completed build, record its output digest, then test it with the isolated
Kubernetes gateway. A synced BuildConfig alone is not a successful build.


`runtime-policies.yaml` installs native policies only for `saw-k8s-test`.
Before activation, the live ANP inventory was empty; this site allocates priority
50. Supervisor traffic may pass to exact DNS, gateway, workload-boundary and
future trusted-proxy peers; every other IPv4/IPv6 destination is denied. The
admission policy fixes container-mode placement and bootstrap identity. The
render passed 56 chart tests and a server-side dry run. These results do not
prove packet enforcement; live negative tests remain a gate before agent use.


The site also installs the stock OpenShift sandboxed containers Operator through
`clusterGroup.subscriptions` (stable, starting CSV `1.13.1`). There was no existing
OSC Subscription/OperatorGroup to adopt. This installs the operator only: no
`KataConfig` is defined and no node reboot is requested at this stage. Before
runtime activation, verify UEFI/KVM and node eligibility, select only an explicit
worker (the control-plane nodes also carry the worker label), and inventory its
workloads. Do not select all workers: that would include the preserved VM hosts.
The lab is nested; a functional test is not a vendor support certification.
See the [stock installation procedure](https://docs.redhat.com/en/documentation/openshift_sandboxed_containers/1.13/html/deploying_openshift_sandboxed_containers_on_bare-metal_servers/install-osc-overview_metal-osc).


`dependency-smoke.yaml` is a separate, credential-free **Agent Sandbox dependency**
test. Argo owns its Sandbox and retained 1Gi PVC. The stock controller starts an
unprivileged, digest-pinned UBI Python container with no service-account token,
no network access and a persistent canary. Changing `operatingMode` in Git to
`Suspended`, then `Running`, must produce a fresh Pod with the same PVC UID and
canary hash. This exercises controller/CRD/storage lifecycle only; it is not
OpenShell supervisor, governance, inference, UI or SAW parity evidence.

Both actual worker probes reported BIOS boot, `/dev/kvm` present and VMX/SVM
present. OSC 1.13's documented UEFI prerequisite is not met. Do not enable a
`KataConfig` or override eligibility to label this a supported Kata test. A
UEFI-provisioned worker is required for the documented path; no existing cluster
or workload disk is reformatted by this qualification.


Observed native-policy acceptance: CEL type checking returned no warnings;
OVN reported `SetupSucceeded`. Running `python3 test-admission.py` from this
directory with the site kubeconfig passed three server-side dry-run cases: an
ordinary restricted Pod was admitted; forged workload and supervisor roles were
rejected specifically by the runtime-identity policy. The script creates no
Pods. This does not yet prove allowed runtime creation or packet enforcement.

[Identity resync receipt](../../docs/evidence/glmhg-kubernetes-identity-resync-2026-11-04.json)
records the six unchanged Secret UIDs, immutable settings and public CA
fingerprints after a second successful Argo sync. No private keys or tokens are
included.


The candidate policy image build completed successfully through Argo/OpenShift:
`image-registry.openshift-image-registry.svc:5000/saw-k8s-build/governance-interceptor@sha256:9f9ceabf338d0265cbedd78df6c27721b1616175c64dc022556d7554caa60b97`.
This verifies full compilation and publication, not live policy behavior; the
existing VM policy Deployment remains unchanged. The container dependency probe
reached Ready under `restricted-v2`, a nonzero UID and no service-account token.
Its first canary/PVC identities were captured before the GitOps suspend phase.


`governance.yaml` deploys that exact candidate digest with the existing policy
catalog in `saw-k8s-build`. Only the test gateway selector is enabled for remote
Kubernetes ingress; its endpoint is
`http://governance-interceptor.saw-k8s-build.svc:18081`. No provider keys are
mounted. This separate service must pass stock protocol/positive/negative tests
before it qualifies the gateway; Deployment availability alone is insufficient.
The baseline VM governance service and its clients retain their original config.


[Container lifecycle receipt](../../docs/evidence/glmhg-container-dependency-2026-11-04.json):
the GitOps `Suspended` commit removed the Pod and retained its Bound claim;
the `Running` commit created a different Pod UID with the same Sandbox/PVC UIDs,
unchanged canary SHA-256 and `initialized=false`. The resumed workload retained
`restricted-v2`, a nonzero UID and no service-account token. The final desired
state is Running. This is a passed dependency/storage test, not SAW parity.

The full candidate build ran its eight driver-guard tests successfully before
release compilation. The isolated governance Deployment is now 1/1 Available at
the pinned digest. The stock OSC `sandboxed-containers-operator.v1.13.1` CSV is
Succeeded. No `KataConfig` was created because both worker firmware checks failed
the documented UEFI prerequisite.

## Trusted proxy and stock gateway

`proxy.yaml` deploys the unchanged SAW credential proxy in `saw-k8s-trusted`.
ESO projects only `api_key` from the approved existing Vault reference. The policy
binds it to OpenAI; no full key enters `saw-k8s-test`. Bootstrap retains the private
CA and projects an immutable public CA into the runtime namespace.

[Proxy receipt](../../docs/evidence/glmhg-kubernetes-proxy-2026-11-04.json): real
`gpt-4.1-mini-2025-04-14` request returned `SAW_PROXY_OK` using only the marker.
An unapproved CONNECT host and unknown marker were denied. Repeated Argo sync
preserved the CA Secret UID, public CA fingerprint and runtime ConfigMap UID.
The transport probe uses loopback-only port-forwarding; it does not prove client
CNI ingress restrictions.

`gateway.yaml` installs the pinned stock OpenShell Kubernetes gateway with
retained identity, explicit API/DNS/OIDC/governance/proxy egress, passthrough TLS
and a retained 1GiB RBD state claim. No agent workspace is activated by this file.
Pod DNS resolves the issuer to `10.10.10.101`, while bastion DNS returns
`52.118.50.101`. The first diagnostic timed out; the second reported HTTP 200 and
`issuerMatches: true` after GitOps permitted the internal VIP on TCP 443. No TLS
bypass was used. The stock gateway recovered on its normal restart, reported the
Kubernetes driver connected, initialized eight governance bindings and became
1/1 Ready under `restricted-v2`. An ordinary owner successfully ran the stock
`openshell workspace list` through the passthrough Route using OIDC and verified
TLS. [Gateway receipt](../../docs/evidence/glmhg-kubernetes-gateway-2026-11-04.json).

The gateway-to-governance HTTP service uses network isolation, not transport-level
caller authentication. This is a development qualification boundary; do not
represent it as production mTLS. No OpenShell-created workload, supervisor
lifecycle, container OpenClaw chat or portal parity has passed yet.

Native admission generation 2 reserves the gateway ServiceAccount/labels for its
controlling StatefulSet. The updated `test-admission.py` passed all six server
dry runs: ordinary Pod admitted, forged workload/supervisor rejected, forged
gateway label and forged owner rejected, approved StatefulSet controller admitted.
No test Pod was persisted. CEL type checking reported no warnings.

## OpenShell workspace lifecycle

Argo installs the trusted reconciler from `controller.yaml`. It watches the
profile and generation-numbered intent, validates live policy and storage
identities, and uses mTLS to manage the owner's workspace through OpenShell.
The stock Kubernetes driver creates the supervisor and a Sandbox CR. The stock
Agent Sandbox controller creates the workload Pod. The driver reserves
`/sandbox` and the internal volume name `workspace`. The pre-existing RBD
claim mounts as `saw-workspace` at `/sandbox/workspace` in the workload.

| Git intent | Observed result |
| --- | --- |
| 7, Running | Owner CLI wrote a unique file through OpenShell. A direct TCP connection to the cluster API was blocked. A second OIDC user was denied access. |
| 8, Stopped | Both runtime Pods disappeared and the original PVC remained Bound. |
| 9, Running | Both Pods received new UIDs on separate workers under restricted-v2. The sandbox ID and PVC/PV identity were preserved. The owner read and removed the original file. Both denial tests passed again. |

Use the controller source branch's `kubernetes-runtime/check-toolbox.sh` with the
ordinary user's verified gateway login. The Python test uses the UBI system
interpreter because this profile permits reads under `/usr` and denies the
image's default virtual environment under `/opt/app-root`.

The generic workload has no model provider. Container OpenClaw and RHDH parity
have separate acceptance gates. The original VM model test and all three VMIs
remain separate. The gateway occasionally logged a Kubernetes list transport
warning, and the workload reported an unlimited PID cgroup. Both merit production
qualification. [Lifecycle receipt](../../docs/evidence/glmhg-stock-container-lifecycle.json).
