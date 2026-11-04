# glmhg Kubernetes foundation qualification

Prepared site manifests; **not activated by the VM baseline root application**.
They install only the stock Agent Sandbox dependency and the retained identity
bootstrap. They do not create a gateway, reconciler, agent workspace, provider
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

After the VM/RHDH acceptance gate, activate through the existing site's
`clusterGroup.applications`, with this Kustomize path:

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
