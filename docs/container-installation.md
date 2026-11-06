# Installing container workspaces

Container mode adds a backend to the existing SAW installation and profile
model. VM remains the default. The [architecture](container-workspaces.md)
describes components, trust boundaries and data paths; this page describes
operator inputs and installation. There is no additional SAW workspace CRD.

## Choose the installation owner

| Entry point | Desired configuration | Component lifecycle |
|---|---|---|
| Validated Pattern | Static entries in `overrides/saw-users.yaml`, with `projection.enabled: true` | Pattern owns the root chart; its ApplicationSet and Argo own container component applications. |
| Standalone Make | Operator-owned values file; `DEPLOYMENT_MODE=container` | Helm owns one root `saw-users` release; ApplicationSet and Argo own component applications. Developer Hub is not required. |
| RHDH self-service | Authenticated create/update/delete request plus operator-provided `portal.containerSites` | Existing portal pipelines and generator own the registration; Argo uses the same component charts. |

Use one entry point per registration. Do not Helm-install a workspace already
owned by the pattern or RHDH. Both VM and container users can coexist in a
`saw-users` installation. Each registration has one backend; it is not an
in-place VM-to-container migration setting.

## Shared platform prerequisites

Start with the SAW platform services: Keycloak/owner accounts, governance,
Vault and External Secrets, image availability and OpenShift GitOps. The
container Make path uses GitOps even when the root chart is installed manually.
It does not require KubeVirt for its workload. Keep KubeVirt installed when also
hosting VM workspaces.

Additional requirements:

- OpenShift with enforced `AdminNetworkPolicy` and native
  `ValidatingAdmissionPolicy`; the baseline is OpenShift 4.22+ with OVN-Kubernetes.
- The pinned stock Agent Sandbox controller and `agents.x-k8s.io/v1beta1` API.
  Install [charts/agent-sandbox](../charts/agent-sandbox) once per cluster, or
  reuse a compatible platform-owned installation. Do not adopt an existing
  release or replace its CRDs from a per-workspace install.
- Argo CD ApplicationSet plugin generators, a project permitting the configured
  destinations/resource kinds, and permission for Argo to manage the workload,
  control, UI and history namespaces. The standalone projector's namespace is
  separate from Argo CD and labelled `argocd.argoproj.io/managed-by`.
- RWO storage for gateway state, workspace data, controller ledger and audit
  history; a shared filesystem class for the preparation/audit exchange PVCs.
- Reachable DNS, Kubernetes API, trusted OIDC issuer, governance, registry and
  approved provider endpoints. Supply explicit network rules and allocate a
  distinct AdminNetworkPolicy priority for each workspace.
- `oc`, Helm 3 and `uv` on the installation machine. Provider credentials stay
  in Vault; local files and Git contain references and public configuration.

For a platform that does not already own Agent Sandbox, its manual installation
is:

```sh
helm upgrade --install agent-sandbox charts/agent-sandbox \
  --namespace agent-sandbox-system --create-namespace \
  --set enabled=true --wait
```

For a GitOps platform, declare the same chart as a platform Application. Its
source lock pins the upstream manifest and controller digest. Removing an
individual workspace must not uninstall this cluster-wide dependency.

## Public inputs and credential references

The same site object is used as `containerSites.<owner>` for static installs or
`portal.containerSites.<owner>` for RHDH. It is administrator-owned, not a form
field. Start from the component charts' values and schemas:

| Site input | Contents / source |
|---|---|
| `subject` | Resolved Keycloak subject UUID matching the owner. Static inputs supply it explicitly; RHDH resolves the authenticated owner and requires a matching site. |
| `stack.identity` | Pinned revision and [identity chart values](../charts/saw-kubernetes-identity/values.yaml): installation identity, gateway SANs and stock generator/helper images. Administrator sessions use the VM's shared temporary-identity mechanism; no administrator certificate or renewal input is supplied. |
| `stack.policy` | Pinned revision and [admission/network values](../charts/saw-runtime-policies/values.yaml): runtime namespace, service accounts, explicit egress and unique priority. |
| `stack.proxy` | Pinned revision and [credential-proxy values](../charts/saw-kubernetes-proxy/values.yaml): trusted namespace and egress. Provider bindings/digest derive from the shared catalog. |
| `stack.gateway` | Pinned revision and [gateway values](../charts/openshell-saw-kubernetes/values.yaml): stock gateway/driver images, storage, OIDC and network configuration. |
| `stack.audit` | Pinned revision and [audit values](../charts/saw-audit-writer/values.yaml): history/exchange storage classes, image and owner identity. Targets derive from the BOM. |
| `governanceNamespace`, `providerAllowHosts` | Shared governance location and permitted provider destinations. |
| `automaticEnrollment` | `enabled`, pinned helper image/revision, build namespace, resource limits, approved profile digests and reviewed boundary reference. |
| `automaticEnrollment.relay` | Pinned relay chart revision, issuer, Keycloak namespace/admin Secret **name**, and explicit egress. See [relay values](../charts/saw-workspace-relay/values.yaml). |
| `profileImageOverrides`, `profileBoundaries` | Optional per-profile pinned image overrides and explicit provider/boundary approval. Changing the profile requires its own approval. |
| `imagePull` | Optional namespace and ImageStream names for access to an OpenShift internal registry. |

Component `values` accept the composition placeholders `@OWNER@`, `@SUBJECT@`,
`@INSTALLATION@`, `@RUNTIME@`, `@TRUSTED@`, `@ARCHIVE@`, `@UI@` and `@DOMAIN@`.
The composition substitutes these as data; it does not evaluate user input as
Helm templates. Do not author `targets`, `enrollment`, `providerPolicy` or relay
subjects manually; the common projector and trusted bootstrap derive them.

Static registration shape, to merge with the complete operator site values:

```yaml
global:
  repoURL: https://github.com/your-org/secure-agent-workspace.git
  targetRevision: <reviewed-commit>
  vpArgoNamespace: vp-gitops
  clusterDomain: cluster.example.com # ingress is apps.cluster.example.com
projection:
  enabled: true
  applicationSetControllerLabels:
    app.kubernetes.io/name: <actual-applicationset-controller-pod-label>
  egress: # explicit Kubernetes API and DNS NetworkPolicy rules
    - to:
        - ipBlock: {cidr: <api-address>/32}
      ports: [{protocol: TCP, port: 6443}]
    # Add the cluster's API Service and DNS paths as required by its networking.
users:
  - name: alice
    ownerSubject: <keycloak-subject-uuid>
    registration: <16-lowercase-hex-characters>
    installationID: <installation-uuid>
    vaultPrefix: secret/data/hub/saw-alice/<same-registration>
    profiles: [data-science]
    pruneOnRemove: true
    intentGeneration: 1
    lifecycleVersion: 1
    desiredState: Running
    restartGeneration: 1
    initialModelInputs: # public selectors from the selected BOM's catalog
      inference.model: <approved-model>
      inference.cuda_model: <approved-model>
    modelInputs: # initially equal to initialModelInputs
      inference.model: <approved-model>
      inference.cuda_model: <approved-model>
    values:
      deployment: {mode: container}
containerSites:
  alice:
    subject: <same-keycloak-subject-uuid>
    # Complete stack, network, storage, provider and relay inputs from the table.
    automaticEnrollment:
      enabled: false # foundation review; enable after approval
      # Complete pinned helper, resources and relay inputs from the table.
```

This shows the input contract, not a runnable site with omitted fields. Generate
unique registration/installation IDs and keep them stable for the installation.
Never reuse an old registration to adopt retained storage or credentials.

For an internal-registry runtime image, `automaticEnrollment.buildNamespace`
identifies its build namespace. The enrollment and preparation pull grants are
restricted to the image stream named by the configured digest-pinned image.

The selected BOM determines provider Secret names and fields. For example, with
the default NVIDIA-backed `data-science` profile, store its key in
`secret/data/hub/saw-alice/<registration>/inference` as `api_key`. Configure any
additional enabled provider inputs in the same registration prefix. RHDH uses
the existing request-to-Vault pipeline; standalone operators use their normal
Vault provisioning. Neither the Make helper nor projector loads raw keys.

Native OpenAI, Anthropic and NVIDIA inference use the same provider profiles as
VMs. Anthropic uses its Messages protocol; NVIDIA model selectors preserve the
vendor/model slash. Select the provider in the approved BOM, then reapprove its
destination and profile inputs through the normal enrollment path. See
[provider qualification](provider-driver-qualification.md) for the BOM shape,
probe commands and current live-test limits.

## Standalone installation and first-site approval

Save the complete public configuration as `container-users.yaml`, then:

```sh
export DEPLOYMENT_MODE=container
export OPENSHELL_SAW_NAME=alice
export SAW_USERS_VALUES_FILE="$PWD/container-users.yaml"
export SAW_INSTALL_NAMESPACE=saw-workspaces
make saw-create
```

The helper renders the chart before making changes, checks the target ingress
domain and required APIs, rejects a foreign installation identity and installs
`workspace-alice`. It creates an Argo-managed installation namespace if absent;
it does not relabel an existing namespace. With enrollment disabled the result
is `AwaitingApproval`, **not** a running-workspace claim. Argo reconciles the
foundation while the application sandbox remains absent.

Wait for foundation Applications to be Synced/Healthy. Inspect the exact public
objects and normalized boundary separately:

```sh
oc get applications -n vp-gitops -l openshell.pattern/owner=alice
uv run --locked python scripts/portal-container/inspect-boundary.py \
  --owner alice --registration "$REGISTRATION" \
  --installation-id "$INSTALLATION_ID" \
  --governance-namespace "$GOVERNANCE_NAMESPACE" \
  --api-server "$EXPECTED_API_SERVER" --show-objects > boundary-objects.json
uv run --locked python scripts/portal-container/inspect-boundary.py \
  --owner alice --registration "$REGISTRATION" \
  --installation-id "$INSTALLATION_ID" \
  --governance-namespace "$GOVERNANCE_NAMESPACE" \
  --api-server "$EXPECTED_API_SERVER" > boundary-reference.json
uv run --locked python scripts/portal-container/inspect-boundary.py \
  --owner alice --registration "$REGISTRATION" \
  --installation-id "$INSTALLATION_ID" \
  --governance-namespace "$GOVERNANCE_NAMESPACE" \
  --api-server "$EXPECTED_API_SERVER" --profile-digest
```

These commands read public objects and do not grant approval or read Secrets.
Review the resource specifications against the intended configuration. Put the
approved reference under `automaticEnrollment.reference` and enable enrollment
in the values file. Review the rendered BOM and put its digest under
`automaticEnrollment.approvedProfiles.data-science`; foundation mode requires
neither placeholder hashes nor a previously approved profile digest. Re-run
`make saw-create`. For a previously approved site,
enrollment can be enabled on its first install.

The projector reads the immutable enrollment and relay publications; no one
copies generated intent or resource UIDs back into Git. Argo then enables the
reconciler, prepared mounts and owner-only browser relay. `make saw-create`
waits for the same current-generation, BOM and browser-readiness conditions as
RHDH. A failed API read or malformed publication returns a projection error,
not an empty workspace list that could prune working applications.

```sh
make saw-status # JSON readiness and authenticated UI links
make saw-delete # foreground deletion of this owned registration
```

The shared installation namespace and retained audit history are not removed
by per-workspace deletion. Provider material provisioned directly in Vault is
operator-owned; deleting the standalone Helm release does not erase it.

## Pattern and RHDH enablement

For static pattern users, put the same values under `overrides/saw-users.yaml`,
enable `projection`, commit them and let the existing `saw-users` Application
reconcile. Its namespace must be separate from Argo CD. VM users keep their
existing Applications and owner-resolution behavior. A container user's
resolved `ownerSubject` does not enable an owner override for VM users.

For RHDH, configure:

```yaml
portal:
  deploymentModes: [vm, container]
  containerSites:
    alice: # the same approved site object; no provider credentials here
      subject: <resolved-owner-subject>
      # stack, automaticEnrollment, approved profiles and site policy
```

Keep `projection.enabled` off for the RHDH-generated child values: the portal
already performs that projection. The Create/update form includes the deployment
selector; the server checks mode, approved profile, owner and cleanup policy.
The Delete form and state actions use the backend recorded in the registration.
Enabling the selector without a matching approved site does not permit creation.

## Updates and current limitations

Update public `modelInputs`, increment `intentGeneration` and
`restartGeneration`, then reapply through the same entry point. Keep
`initialModelInputs` and registration identity fixed. For stop/start, change
`desiredState` and increment `intentGeneration`; storage remains attached to the
registration. Do not switch an enrolled workspace back to foundation mode.

There is no additional upgrade controller. Argo reconciles pinned chart/image
changes; immutable preparation Jobs get input-derived revision names. An
enrolled boundary change requires deliberate approval, not automatic trust in
a newly observed hash. VM installation keeps its current signed installer,
live-input reconciliation and reboot path.

Administrator sessions are created per operation using the shared VM mechanism.
Their private material stays in memory-backed volumes; the charts grant the
controller and membership Job access only to their named public client-trust
Secret. No retained admin key, `adminDays` setting, renewal controller or operator
credential injection is needed. Server TLS and retained gateway identity remain
separate from this mechanism; a normal resync never rotates that identity.

VM guest commands
(`saw-vm-ssh`, installer logs and VM restart) remain VM-only. Container logs come
from the reconciler in `saw-ctl-<registration>` and the application Pods; lifecycle
changes use public intent or RHDH. See the architecture page's
[current boundaries](container-workspaces.md#current-boundaries) for the remaining
security and access limitations.
