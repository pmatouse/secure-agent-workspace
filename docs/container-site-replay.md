# Install and qualify a container site

This recipe adds an RHDH container owner to a working Secure Agent Workspace VM
installation. Choose headless `custom-inference` or the OpenAI site variant of
`data-science` with two browser chats. Both consume the existing VM BOM through
shared profile semantics and use a dedicated stock OpenShell gateway and credential proxy for
each registration. The operator commits public inputs and generated manifests.
The owner enters their inference credential through RHDH.

| Profile | Agent access | Model configuration |
|---|---|---|
| `custom-inference` | Owner OpenShell CLI; the profile declares no browser route | Site-approved `https://api.openai.com/v1`, owner-supplied model |
| `data-science` | Owner-only browser chats for `default/notebook` and `cuda-dev/cuda-sandbox` | Official OpenAI API; separate notebook and CUDA-sandbox model selectors |

The data-science example uses external inference. Its CUDA sandbox name does
not imply a GPU resource allocation. Optional web search and harness bundles
are disabled by this renderer. Enabling either changes the BOM and requires a
matching provider capability, boundary review and separate qualification.

Each browser link follows `HTTPS Route → oauth2-proxy → stock OpenShell CLI
forward → gateway → supervisor → OpenClaw loopback :18789`. Each relay has its
own Keycloak client and membership in only its target workspace. The browser
login is restricted to the owner. The model API key stays in the trusted
credential proxy; agents send provider markers. See the
[relay contract](../charts/saw-workspace-relay/README.md).

**Verified on glmhg:** the owner chart rendered the same 43 objects using the
portable inputs and the live registration's public bindings. All 16 boundary
entries matched. Enrollment and controller fault injection, real owner chat
and teardown used the existing shared platform. The foundation manifests
passed OpenShift server dry-run. A subsequent clean SAW reinstall is recorded
below; reprovisioning OpenShift itself remains outside this test. [Recovery record](../tests/acceptance/container-recovery-2026-11-05.json)

**Clean reinstall on the same cluster:** the official uninstall and install
both exited successfully. The replacement VMs passed owner inference, then
all three container images built in a new namespace. A synthetic registration
was denied enrollment before review. RHDH completed the subsequent real
registration; the ordinary owner obtained a transcript-verified reply through
its dedicated OpenShell gateway. All 30 Argo Applications were Synced and
Healthy. [Clean install receipt](../tests/acceptance/container-clean-install-glmhg-2026-11-05.json)
· [Deployed site values](https://github.com/pmatouse/secure-agent-workspace/tree/9db73c2cca6401d76498567ad4de0c05081b04e1/overrides)

## Reusing a single test cluster

A destructive SAW replay keeps OpenShift, its login and storage infrastructure
running. Inventory all VMIs, SAW Applications, namespaces and retained claims
first. Keep the private installer inputs on the bastion. Record old Pattern,
workspace, governance and Agent Sandbox UIDs so the new installation can be
distinguished from a restart. The SAW Keycloak realm is separate from RHDP SSO.

1. Delete RHDH-created workspaces through the owner/admin portal and wait for
   their Applications to disappear. An orphaned portal `saw-users` Application
   can recreate its VM during uninstall and block HyperConverged deletion.
2. Run `./pattern.sh make pattern-uninstall` using the original checkout and
   cluster context. If the ApplicationSet has already disappeared, inspect any
   remaining portal Application's owner, destination, source and UID before
   requesting a normal Argo cascade. Allow Tekton Results to finish finalizing
   old task runs.
3. Verify the Pattern and all its Applications are absent. Check SAW's Vault,
   Keycloak, RHDH, workspace, build and control namespaces. Older Argo
   applications without cascade finalizers can leave workloads, cluster RBAC
   and policies behind. Remove only verified SAW-owned leftovers. For a fresh
   Agent Sandbox installation, verify zero Sandbox objects across **all**
   namespaces before retiring the previously SAW-installed controller and CRD.
   Retained audit namespaces can stay isolated from subsequent registrations.
4. Start from a VM-only branch with an empty GitOps user list. Mirror the pinned
   golden image into the new namespace and verify its digest. Install the
   Pattern, wait for shared services, create the new realm users, then commit the
   VM workspace definitions. Require guest install/apply completion and real
   owner inference before proceeding with container enrollment.
5. Build the three container images afresh, resolve the owner's new Keycloak
   subject, and review the new boundary. A reused login name and cluster DNS
   name do not preserve realm, Kubernetes object or image identities.

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
export CONTROLLER_REVISION=431ce749537117aab6cc2f0c8a43598c0e05123b
export OWNER=alice API_SERVER="$(oc whoami --show-server)"
dir=overrides/container-foundation
mkdir -p "$dir"
common=(--repo "$REPO" --build-namespace "$BUILD_NS" --governance-namespace "$GOV_NS"
  --controller-revision "$CONTROLLER_REVISION")
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
oc -n "$BUILD_NS" get istag "saw-runtime-controller:${CONTROLLER_REVISION:0:12}" saw-openclaw-home:traverse \
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

Choose the profile and the exact `saw-bom` chart that the site's GitOps
Applications deploy. A different checkout may contain different profile bytes.
The development repository's default data-science profile uses NVIDIA; this
OpenAI recipe requires the reviewed site variant used by its VM workspaces.
The renderer rejects a data-science BOM that routes an enabled sandbox to
another provider or endpoint.

```bash
export PROFILE=custom-inference   # or data-science for the two browser chats
export BOM_CHART="$PWD/charts/saw-bom"  # exact deployed site chart
profile_args=(--profile "$PROFILE" --controller-revision "$CONTROLLER_REVISION"
  --bom-chart "$BOM_CHART")
```

For data science, the site BOM must bind both enabled sandboxes to `openai`,
using `inference.api_key`, explicit `protocol: openai` and
`baseUrl: https://api.openai.com/v1`. The two public model inputs are
`inference.model` and `inference.cuda_model`; this demo defaults both to
`gpt-4.1-mini`. Both sandboxes declare `ui.route: true`.

The renderer computes the BOM hash from the actual Helm render, including the
notebook digest and disabled web search/harness. It pins the selected profile,
source revision and controller image separately. Set `controllerImage` to the
completed Build's digest for `CONTROLLER_REVISION`; a source SHA alone does not
change a running controller. Bearer tokens, user passwords and Vault values
stay outside Git.

## 4. Review and activate enrollment

The boundary reference contains owner-specific policy hashes and
cluster-specific governance UIDs. Each new site needs an independent review.
For an already approved owner, use its reviewed reference and skip staging.

For first review, render an approval that cannot match live objects:

```bash
inputs=overrides/container-inputs.yaml
out=overrides/container-owner.yaml
python3 scripts/portal-container/render-site.py --inputs "$inputs" "${profile_args[@]}" \
  --stage-review > "$out"
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
If the synthetic create PipelineRun is still waiting on the intentionally
blocked enrollment, cancel that exact run before submitting a new registration;
otherwise it can keep polling the same owner name. The history namespace
follows the normal retention policy.

```bash
python3 scripts/portal-container/render-site.py --inputs "$inputs" "${profile_args[@]}" \
  --reviewed-boundary overrides/container-reviewed-boundary.json > "$out"
git diff --check
```

Review, commit and push. Wait for the generator and the installed RHDH form.
Choose **Container** and the approved profile. RHDH filters choices by the
site's reviewed profile catalog; the backend also checks approval for the
individual owner. The custom-inference form asks for endpoint, model and key.
Data science asks for the key and both model selectors, then publishes its two
owner-authenticated chat links in the workspace catalog. A workspace already
registered with another profile must be deleted through RHDH before switching;
use a separate disposable owner to preserve an existing workspace.

The [registered-owner chat procedure](custom-inference.md#qualify-a-registered-owner-against-a-real-model)
checks the headless profile. Use the browser lifecycle test below for data
science. `GenericReady` is a runtime observation; require a real model reply.

## 5. Qualify data-science browser chat and lifecycle

Run from a checkout containing the current acceptance helpers after completing
the data-science review above. The chosen owner must have no registration or
runtime namespace. This test creates and deletes only that new registration;
it retains the audit namespace. Use the same cluster's operator context for
fixtures and evidence, and the ordinary owner's credentials for all RHDH and
chat requests.

```bash
export KUBECONFIG=/private/path/cluster-kubeconfig
export SSL_CERT_FILE=/private/path/public-ingress-ca.pem
export PYTHONPATH="$PWD/cli/src${PYTHONPATH:+:$PYTHONPATH}"
# Python needs PyYAML, click and requests; openssl on PATH must support Ed25519.
# On macOS with Homebrew OpenSSL 3:
# export PATH=/opt/homebrew/opt/openssl@3/bin:$PATH
python3 tests/acceptance/portal_container_lifecycle.py \
  --user "$OWNER" --profile data-science \
  --portal "$RHDH_URL" --issuer "$KEYCLOAK_REALM_URL" --domain "$CLUSTER_DOMAIN" \
  --password-file /private/path/owner-password \
  --key-file /private/path/official-openai-api-key \
  --model inference__model=gpt-4.1-mini \
  --model inference__cuda_model=gpt-4.1-mini \
  --update-model inference__model=gpt-4.1 \
  --update-model inference__cuda_model=gpt-4o-mini
```

`CLUSTER_DOMAIN` omits the `apps.` prefix. `SSL_CERT_FILE` must trust the public
SAW ingress certificate. The password/key files are private inputs, never Git
artifacts. Confirm that all chosen models are enabled for the test API account.

```mermaid
sequenceDiagram
  actor Owner
  participant RHDH
  participant GitOps as Tekton / Argo
  participant Gate as Enrollment / reconciler
  participant OS as Stock OpenShell
  participant Chat as Two OpenClaw sandboxes
  participant Proxy as Trusted credential proxy
  participant Model as OpenAI API
  Owner->>RHDH: Container + data-science + models + key
  RHDH->>GitOps: Owner-bound registration; credential to Vault/ESO
  GitOps->>Gate: Approved BOM, gateway, policies, PVCs and model files
  Gate->>OS: Create two sandboxes through the stock API
  Owner->>Chat: Keycloak login / workspace-scoped HTTPS relay
  Chat->>Proxy: Model request with nonsecret provider marker
  Proxy->>Model: Inject key only for api.openai.com
  Model-->>Owner: Response through the same chat connection
  Owner->>RHDH: Update both model selectors
  GitOps->>Gate: Publish model generation; advance runtime intent
  Gate->>OS: Stop/start recorded sandbox IDs; retain PVCs
  Owner->>RHDH: Delete workspace
  GitOps->>OS: Foreground removal; retain audit history
```

Expected acceptance evidence:

| Gate | Required result |
|---|---|
| Create | RHDH task completed, Tekton succeeded, generation 1 ready; both owner chat routes authenticate |
| Chat/tool gate | Each agent reads an unpredictable canary; owner-denied deletion leaves its file and owner-approved deletion removes only its disposable file |
| Update | Generation 2 serves the two selected models; fresh transcript evidence records matching provider response models; OpenShell IDs and PVC UIDs stay the same |
| Stop/start | Owner actions reach Stopped and Running; fresh Pods recover files and the exact original tool-test audit records |
| Delete | RHDH task completes; registry, runtime/control/UI namespaces disappear; separate restricted read-only Jobs recover the same tool-test record hashes |

The final JSON records task IDs, registration, sandbox archive UIDs and ordered
audit hashes. The audit snapshot covers the completed `read`, `deny`, and
`approve` test turns, including each record's sequence, ID and body bytes.
Subsequent model chats may append legitimate records; an append-only log need
not remain identical as new activity occurs. A successful PipelineRun alone is insufficient. On failure the
harness stops and leaves evidence; inspect before deleting or retrying. An
interrupted generation-1 create can be resumed with
`--resume-create TASK_UUID REGISTRATION`, bound to that exact registration.

**Verified 2026-11-06:** a fresh `sawdsowner` registration passed RHDH
create/update/stop/start/delete and real owner HTTPS/WSS chat in both sandboxes.
The update selected `gpt-4.1` for the notebook and `gpt-4o-mini` for CUDA
development; provider response models matched after update and restart.
Files, PVC UIDs and OpenShell identities persisted. Fresh read-only Jobs
recovered the exact five tool-test audit records per sandbox after deletion.
The profile approval remains installed; the disposable registration was deleted.
The existing `sawk8sowner` registration kept its original workload Pod.
[Full acceptance receipt](../tests/acceptance/data-science-shared-rollout-2026-11-06.json)

Controller source `431ce749537117aab6cc2f0c8a43598c0e05123b` contains shared
core extraction `349052e`. A fresh VM installation also loaded the identical
core bytes and passed both browser chats, provider inference and undeclared
egress denial. The lab retains its existing `warn`/unsigned installer policy;
this test does not qualify signature enforcement. An older VM upgrade canary
hit malformed persisted Podman state, so its disk was retained for diagnosis
and fresh installation qualified separately.
[VM evidence and retained-canary state](../tests/acceptance/vm-shared-core-2026-11-06.json)

## 6. Inject recoverable faults on a disposable registration

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

This replay qualified SAW reinstallation, new VM disks, container image builds
and first-time registration on retained OpenShift infrastructure. Reprovisioning
OpenShift, RHDP SSO or the storage backend is a different test.
