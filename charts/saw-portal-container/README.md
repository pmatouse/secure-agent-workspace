# RHDH container workspaces

An enrolled owner chooses **Container** in the existing RHDH create/update template, selects a site-approved BOM profile, and enters the provider credential. The existing owner picker handles deletion. The portal currently supports one registration per owner. VM is the default deployment.

### How a profile reaches either runtime

Both deployment methods render `charts/saw-bom` and read the same profile documents. Both use `saw_core` to parse and validate those documents, resolve typed inference inputs and defaults, and order workspace, provider and sandbox creation. The profile catalog lists the enabled workspaces, sandboxes and browser routes. The VM installer supplies its filesystem reader for inference inputs. The Kubernetes adapter supplies public model selections and attaches PVCs to stock OpenShell sandboxes.

The site approves the rendered BOM digest in `automaticEnrollment.approvedProfiles`. RHDH derives one storage binding per enabled sandbox, and a scoped owner relay for each declared UI. An additional profile using these capabilities needs a digest approval and qualification. A new BOM capability belongs in the shared engine when both runtimes need it, with storage, placement and authorization supplied by the adapters.

The glmhg data-science VM BOM enables `default/notebook` (OpenClaw) and `cuda-dev/cuda-sandbox` (NemoClaw running OpenClaw). It uses external OpenAI inference and disables the optional inline harness at this site. NemoClaw uses its original image digest. The AIPCC notebook image sets `/sandbox` to mode 0770 for UID 1000 and group 0. The stock Kubernetes driver uses the OpenShift namespace UID/GID for the workload. The [image build chart](../../image-builder-charts/helm/openshift-home-access) derives the notebook image from the exact VM digest, adds directory traversal with `chmod o+x /sandbox`, and restores the image user. The owner portal passes the resulting digest through the existing `saw-bom.imageOverrides` input. The same BOM sources produce both deployments, with a different reviewed render digest for that image selection. The sandbox keeps the OpenShift-assigned identity.

The two model selectors are public configuration. API keys stay in the registration's Vault path. The current update path can refresh provider credentials and reconcile the existing topology. Changing the selected model or profile currently requires a fresh registration.


```mermaid
flowchart LR
  O[Workspace owner] --> R[RHDH scaffolder]
  R --> T[Shared Tekton lifecycle]
  T --> V[Vault: registration-specific key]
  T --> W[Workspace registry]
  W --> A[ApplicationSet / owner Application]
  A --> B[Shared profile BOM]
  A --> F[Gateway, policy, proxy, writer and claims]
  B --> E[Trusted enrollment Job]
  F --> E
  E --> P[Immutable public enrollment]
  P --> A
  A --> C[Workspace reconciler]
  C --> G[Stock OpenShell gateway]
  G --> S[Supervisor + audited OpenClaw]
  O --> L[Owner HTTPS login / scoped relay]
  L --> G
  S --> X[Audit exchange]
  X --> H[Restricted writer / retained history PVC]
  V --> Z[ESO / credential proxy]
  S --> Z
```

| Step | What happens |
|---|---|
| Create | The shared portal verifies the Backstage caller, looks up the approved owner subject and profile, stores the key in a generation-specific Vault path, and records the registration. Argo renders the same BOM used by VM workspaces. Container mode selects a dedicated gateway instead of a VM. |
| Enroll | A restricted Job compares the live admission, network, gateway, proxy and governance configuration with the site's previously reviewed reference. It checks cluster realization, PVC ownership/UIDs, and the BOM digest; it obtains the audit receipt public key over service-CA-verified TLS. It can patch only its precreated enrollment ConfigMap. It cannot read Secrets via the API, mount audit history or change policy. Its gateway CA mount projects only the public certificate. |
| Start | The portal generator reads the immutable public binding. Argo deploys the gate preparation Job and reconciler. The reconciler verifies the concrete resource UIDs and hashes again before creating the workspace and sandbox via stock OpenShell RPCs. The model key stays in the credential proxy's trusted namespace. |
| Open chat | Keycloak issues a dedicated service-account subject bound to this registration. The membership Job checks the gateway's workspace ID, installation label and owner administrator before granting the relay only the workspace user role. The owner must separately sign in via the registered HTTPS callback. The relay forwards to the sandbox's OpenClaw listener. |
| Use a tool | OpenClaw uses the shared VM tool gate. A mutating call can require an owner decision. The trusted writer commits the record before signing a receipt. The agent mounts an exchange, never the writer's history PVC or signing key. |
| Update | The same form retains the registration and claims and increments intent generation. Readiness requires the current generation, profile UID, and intent/BOM digest, plus a healthy Argo application and a working owner login challenge. |
| Delete | The shared deletion pipeline fences the registration and waits for foreground GitOps removal before destroying the scoped Vault data and registry entry. The relay client and callback are removed. The separate history namespace/PVC is retained; a subsequent create gets a different one. |

**Site inputs:** [example values](../../examples/portal-container/glmhg.yaml) contain the authorized owner/Keycloak subject, reviewed chart revisions, image digest, storage classes, gateway and proxy networking, governance namespace, approved BOM digest and boundary reference. These values are operator policy, never form input. A change to a pinned policy, shared governance identity, or approved BOM requires review. The owner enters only the profile, backend and inference key. No OpenShell driver or VM image patch is required.

**Acceptance:** [RHDH owner client](../../tests/acceptance/rhdh_workspace.py) submits the actual installed templates. A returned task ID is not a pass: wait for the Backstage task **and** Tekton PipelineRun. [Chat client](../../tests/acceptance/openclaw_audit_chat.py) signs in to the real HTTPS/WSS route, reads an unpredictable canary, and resolves tool approval requests as the owner. Also check the actual disposable files. [Archive verifier](../../tests/acceptance/portal_audit_evidence.cjs) checks the decision sequences and hashes the ordered records for comparison after deletion.

**Audited OpenClaw validation (glmhg, 2026-11-05):** the owner’s create, update and delete tasks all completed in RHDH and succeeded in Tekton. Generation 2 retained the same sandbox and history PVC. Five expected tool-gate records matched byte-for-byte after foreground deletion and an independent read-only remount. The [validation record](../../tests/acceptance/portal-container-validation-2026-11-05.json) includes run IDs, digests and the two issues encountered during qualification.

### Repeat the owner lifecycle

Use an enrolled **disposable owner with no current registration or runtime namespace**. Use an operator `oc` context for the same cluster. The harness needs read access to registration/runtime state, workspace exec for test fixtures, and permission to run a restricted read-only verification Job in the resulting audit namespace. These permissions are for the test observer, not the RHDH user.

```sh
python3 tests/acceptance/portal_container_lifecycle.py \
  --user "$TEST_OWNER" --portal "$RHDH_URL" --issuer "$KEYCLOAK_REALM_URL" \
  --domain "$CLUSTER_DOMAIN" --openclaw-version "$OPENCLAW_CLIENT_VERSION" \
  --password-file "$OWNER_PASSWORD_FILE" --key-file "$INFERENCE_KEY_FILE"
```

The final JSON contains three Backstage task IDs, the archive PVC UID, decision sequences and a before/after SHA-256. An intermediate task ID or PipelineRun does not indicate completion. On a failed step the harness stops and leaves evidence for inspection. To retry a clean cycle, first inspect the task and remove only the disposable registration using the normal RHDH delete template. The example site uses OpenClaw client version `2026.9.6-eb377ac59e6c-2026-09-23T16-32-01.435Z`.
