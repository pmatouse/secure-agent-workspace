# glmhg Kubernetes foundation qualification

Site foundation manifests, activated by `values-cluster-glmhg.yaml`.
They install the stock Agent Sandbox dependency, retained identity bootstrap,
and an isolated build of the SAW governance policy service. They do not create a gateway, reconciler, agent workspace, provider
credential, KataConfig or RuntimeClass, and do not enable portal backend choices.

The two child Applications pin the reviewed integration commit rather than a
moving branch. The Agent Sandbox binary/CRD and gateway certificate generator are
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
