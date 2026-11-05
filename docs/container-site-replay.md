# Install and qualify a container site

This recipe adds one RHDH owner and the shipped, headless `custom-inference`
profile on a working Secure Agent Workspace VM installation. It selects
`https://api.openai.com/v1`, reads the VM BOM through the shared compiler, and
uses a dedicated stock OpenShell gateway and credential proxy for each
registration. The operator commits public inputs and generated manifests.
The owner enters their inference credential through RHDH.

**Verified on glmhg:** the owner chart rendered the same 43 objects using the
portable inputs and the live registration's public bindings. All 16 boundary
entries matched. Enrollment and controller fault injection, real owner chat
and teardown used the existing shared platform. The foundation manifests
passed OpenShift server dry-run. First installation on an empty cluster is
still an outstanding qualification. [Recovery record](../tests/acceptance/container-recovery-2026-11-05.json)

## 1. Establish the VM baseline

On a new OpenShift 4.22+ cluster with functioning CNV/KVM, follow the
[Validated Pattern installation](../README.md#option-a-validated-pattern-automated-gitops)
in order, including prerequisites, image mirroring, secret loading, a first
VM, owner OIDC login and a real chat. Use a fork/branch containing the
container implementation and its pinned Git objects. Record the branch,
cluster version, VMI UID and successful reply. On an existing installation
verify the VM is running and the shared RHDH, Vault, ESO, Keycloak, Tekton and
Argo services are healthy before adding the container path.

## 2. Declare shared dependencies

Run from the repository root with Python 3 and PyYAML, Helm and `oc`. Choose
dedicated build and governance namespaces. Add them to
`clusterGroup.namespaces` in the site's `values-prod.yaml` before syncing.
Use one owner per shared installation of Agent Sandbox. Check the CRD and
controller first. [Agent Sandbox ownership and prerequisites](container-runtime-dependencies.md)

```bash
export REPO=https://github.com/YOUR_ORG/secure-agent-workspace.git
export BUILD_NS=saw-container-build GOV_NS=saw-container-policy
export OWNER=alice API_SERVER="$(oc whoami --show-server)"
dir=overrides/container-foundation
mkdir -p "$dir"
common=(--repo "$REPO" --build-namespace "$BUILD_NS" --governance-namespace "$GOV_NS")
oc get crd sandboxes.agents.x-k8s.io --ignore-not-found
oc get deploy -A -l app=agent-sandbox-controller
python3 scripts/portal-container/render-foundation.py build "${common[@]}" > "$dir/build.yaml"
# On a site requiring its first Agent Sandbox installation, add --install-agent-sandbox above.
printf '%s\n' 'apiVersion: kustomize.config.k8s.io/v1beta1' 'kind: Kustomization' \
  'resources:' '  - build.yaml' > "$dir/kustomization.yaml"
```

Add this entry to `clusterGroup.applications` in the deployed values file,
set `namespace` to the chosen build namespace, then commit and push. The
parent Argo project needs permission to create the listed resources and the
child Applications. On sites with existing build/governance apps, retain
their current Argo owner and verify their outputs before reusing them.

```yaml
saw-container-foundation:
  name: saw-container-foundation
  namespace: saw-container-build
  path: overrides/container-foundation
  kustomize: true
```

The build stage compiles the controller at the pinned source revision,
builds the governance interceptor, and creates the OpenShift-compatible
notebook image. Wait for successful Builds and three populated ImageStreamTags.
Image digests are cluster outputs; record the ones your registry reports.

```bash
oc -n "$BUILD_NS" get builds
oc -n "$BUILD_NS" get istag saw-runtime-controller:a4162dfe1529 saw-openclaw-home:traverse \
  governance-interceptor:kubernetes-fb158a7 -o custom-columns=TAG:.metadata.name,DIGEST:.image.metadata.name
gov_digest=$(oc -n "$BUILD_NS" get istag governance-interceptor:kubernetes-fb158a7 -o jsonpath='{.image.metadata.name}')
python3 scripts/portal-container/render-foundation.py serve "${common[@]}" \
  --governance-digest "$gov_digest" > "$dir/serve.yaml"
printf '  - serve.yaml\n' >> "$dir/kustomization.yaml"   # add once
oc kustomize "$dir" >/dev/null
```

Commit and push. Wait for the dedicated governance Deployment to become
Available. Its extra provider profile fixes the credential destination at
`api.openai.com:443`. Each owner chart grants its gateway access to the
interceptor. A distinct governance namespace gets a scoped pull grant for
the governance image.

## 3. Prepare public site inputs

Copy [the complete input YAML](../examples/portal-container/glmhg-custom-inputs.yaml)
to `overrides/container-inputs.yaml`. Replace the example values:

| Input | Source |
|---|---|
| `owner`, `subject`, `issuer` | Keycloak owner login, its immutable user UUID and the HTTPS realm issuer used by SAW |
| `keycloakNamespace`, `keycloakAdminSecret` | Existing SAW Keycloak installation and Secret **name** |
| `buildNamespace`, `governanceNamespace`, both image references | Namespaces above and completed controller/notebook digests, formatted as internal registry pullspecs |
| `apiAddresses`, `apiPorts`, `clusterCIDRs` | Kubernetes Service IP and ready API endpoint IPs/ports, Pod and Service CIDRs. Run `python3 scripts/network-topology.py print-json`. Review allowed address/port combinations. This recipe is IPv4. |
| `issuerAddresses`, `networkPriority` | Site-approved ingress addresses for issuer HTTPS and an available AdminNetworkPolicy priority. Inspect existing policies with `oc get adminnetworkpolicies`. |
| `gatewayStorage`, `historyStorage`, `exchangeStorage` | Filesystem storage classes for the gateway, immediate RWO history/workspace, and RWX gate/audit exchange. Verify CSI capabilities and `oc get sc`. |

The renderer computes the BOM hash from the actual Helm render, including the
notebook digest and disabled web search. The owner supplies the model and
provider key. Bearer tokens, user passwords and Vault values stay outside Git.

## 4. Review and activate enrollment

The boundary reference contains owner-specific policy hashes and
cluster-specific governance UIDs. Each new site needs an independent review.
For an already approved owner, use its reviewed reference and skip staging.

For first review, render an approval that cannot match live objects:

```bash
inputs=overrides/container-inputs.yaml
out=overrides/container-owner.yaml
python3 scripts/portal-container/render-site.py --inputs "$inputs" --stage-review > "$out"
```

Append `/overrides/container-owner.yaml` to the existing
`clusterGroup.applications.openshell-rhdh.extraValueFiles`, preserving the
existing files. This is a one-owner example. Use each owner's own file/entry
when assembling a multi-owner site. Commit and push. In RHDH create a
disposable container registration for this owner with a **synthetic
noncredential** in the key field. The staged enrollment deliberately blocks
before publishing an intent. Once the infrastructure is ready:

```bash
REGISTRATION=$(oc -n saw-portal get cm "saw-ws-$OWNER" -o json |
  jq -er '.data["user.json"] | fromjson | .vaultPrefix | split("/") | last')
review=(--api-server "$API_SERVER" --owner "$OWNER" --registration "$REGISTRATION" --governance-namespace "$GOV_NS")
python3 scripts/portal-container/inspect-boundary.py "${review[@]}" --show-objects > /tmp/saw-public-objects.json
python3 scripts/portal-container/inspect-boundary.py "${review[@]}" > /tmp/saw-candidate-boundary.json
```

Compare the public specs with the pinned chart renders, site egress rules,
gateway image/identity, governance Deployment/Service/config, proxy policy,
admission binding and public CA. Confirm that the extra governance profile
has the expected host, port and bearer slot. The inspector checks the same
live network/admission conditions as enrollment; its output is a candidate
until an administrator reviews it. Record the approved JSON in
`overrides/container-reviewed-boundary.json`. Delete the staging registration
through RHDH and wait for foreground cleanup before submitting a real key.
The history namespace follows the normal retention policy.

```bash
python3 scripts/portal-container/render-site.py --inputs "$inputs" \
  --reviewed-boundary overrides/container-reviewed-boundary.json > "$out"
git diff --check
```

Review, commit and push. Wait for the generator and the installed RHDH form.
Choose **Container → custom-inference**. The form asks for endpoint, model
and inference key. The [registered-owner chat procedure](custom-inference.md#qualify-a-registered-owner-against-a-real-model)
checks a fresh completion, the selected response model, broker denial and
owner deletion. Allow time for OpenClaw to start after `GenericReady`.

## 5. Inject recoverable faults on a disposable registration

Submit the owner's create request **once**. Obtain `REGISTRATION` immediately
from the owner ConfigMap as above. Start the enrollment probe while the Job
is active. Both commands verify cluster identity, owner, registration,
generation and Kubernetes controller ownership before deleting one Pod with
a UID precondition. They leave declared resources under Argo control.

```bash
scope=(--api-server "$API_SERVER" --owner "$OWNER" --registration "$REGISTRATION")
python3 tests/acceptance/portal_recovery.py enrollment "${scope[@]}"
# After saw-runtime-status reports GenericReady:
python3 tests/acceptance/portal_recovery.py controller "${scope[@]}"
```

Expected results:

1. A replacement Pod completes the **same enrollment Job** and publishes the immutable binding.
2. The replacement reconciler writes the retained core ledger again. The probe checks its recorded OpenShell IDs, notebook and gateway Pod UIDs, enrollment UID and PVC UIDs before and after recovery.
3. The ordinary owner reaches the running OpenClaw gateway and obtains a verified model response. Complete the RHDH create and delete tasks. Verify the runtime/control namespaces disappear and the expected history PVC remains Bound.

A separate clean-cluster run is required to qualify operator installation,
VM baseline creation and first-time activation of the shared dependencies.
