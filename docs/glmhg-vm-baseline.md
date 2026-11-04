# glmhg VM baseline

This branch is upstream `c9691be3ff0a9a2dde4fee91514b5215bbcb9275` plus site configuration and an optional Keycloak resource-values input. It does not include the container/Kata implementation. Installation follows README Option A through the Validated Patterns utility container and Argo CD. Component images and operator code remain stock.

## Site inputs

- OpenShift 4.22.20, AMD64, OVN-Kubernetes, default `ocs-external-storagecluster-ceph-rbd`.
- Cluster UID: `8a8c74bb-2c80-43d5-b7fb-a00d422c47f2`.
- API: `https://api.cluster-glmhg.dyn.redhatworkshops.io:6443`.
- Topology and image selections: `overrides/saw-users.yaml`.
- Both data-science workspaces use the official OpenAI API and `gpt-4.1-mini`; no NVIDIA credential is needed. Their supported profile YAML and generated RHDH catalog describe that selection.
- Both sandbox `inference` blocks explicitly set `protocol: openai` and
  `baseUrl: https://api.openai.com/v1`. SAW's existing custom-endpoint onboarding
  registers the selected model with OpenClaw. This still uses the official API
  through the credential proxy; no OpenClaw/OpenShell image is changed.
- Web search is off because no search credential was supplied. Web-search qualification remains pending.
- Provider keys enter through the private Validated Patterns secret-loader input and Vault. Credential-proxy mode remains enabled. No credential belongs in Git.
- Initial `users: []` intentionally allows the platform to converge before adding VM accounts through Git.

## Artifacts

| Artifact | Selection |
|---|---|
| Golden image source build | [upstream run 40657924797](https://github.com/validatedpatterns-sandbox/secure-agent-workspace/actions/runs/40657924797), commit `a799a1efaab530235bf66cebcf866e9fc2013a64` |
| Golden image index | `sha256:eaf603d12d763c7154c04fcb78b8cae8cebfc3bdf25a155c63adfa6f74e7d31d` |
| Credential proxy | [upstream run 40916230616](https://github.com/validatedpatterns-sandbox/secure-agent-workspace/actions/runs/40916230616), index `sha256:73f271de2eb6166315603fbb72c800b939a14770a69c86debaabbd29a46a0f93` |
| OpenShell components | Unchanged stock BOM `0.1.2-rhaiv.6`, existing digest pins |
| Local CLI | Stock NVIDIA OpenShell `0.1.2`, release SHA-256 verified |
| Utility container index | `quay.io/validatedpatterns/utility-container@sha256:cdac62c3746f65d69f05b71fd99a347f7dbdf345776c56d9a6893adb1e9aa040` |
| NemoClaw CLI/sandbox and dashboard | Digests in site values and profile YAML, resolved before installation |

Published golden-image tag was verified before mirroring. The in-cluster mirror preserved the index digest. Neither the VM disk nor container layers were downloaded onto the laptop. Registry resources were created only by the documented `make images-mirror` bootstrap.

## Replay commands

On the provisioned Linux bastion, with cluster-admin kubeconfig and private secret inputs:

```bash
export TARGET_ORIGIN=origin TARGET_BRANCH=site/glmhg-vm-baseline
export PATTERN_UTILITY_CONTAINER=quay.io/validatedpatterns/utility-container@sha256:cdac62c3746f65d69f05b71fd99a347f7dbdf345776c56d9a6893adb1e9aa040
make prereqs-check
make ssh-key-generate
make images-mirror IMAGE_TAG=sha-a799a1efaab530235bf66cebcf866e9fc2013a64
make check-oidc-ca
./pattern.sh make install
./pattern.sh make argo-healthcheck
```

On this bastion the default rootless UID remap was too slow and was stopped
before any Ansible task ran. The successful runner invocation uses the
wrapper's existing input (no wrapper modification):

```bash
export VALUES_SECRET=/home/lab-user/.saw-private/glmhg/values-secret.yaml
export EXTRA_ARGS="--userns=keep-id:uid=0,gid=0 --user=0:0 -v /home/lab-user:/root"
./pattern.sh make install SSH_KEY_PATH=/home/lab-user/.saw-private/glmhg/sandbox-ssh
```

This is rootless Podman: container UID 0 maps to the unprivileged bastion user,
not host root. It changes the installer runner only.

### Operator bootstrap recovery

The initial External Secrets bundle Job exceeded OLM's ten-minute deadline
during cold image pulls on the nested lab. Vault initialized and unsealed,
but its Kubernetes auth setup waits for the missing ESO service-account token.
This run is not evidence of a clean first-pass installation.

`values-cluster-glmhg.yaml` gives that OperatorGroup a 30-minute bundle timeout
and a ten-minute minimum retry interval. OLM performs failed-job cleanup and
retry; no Job, Subscription or InstallPlan is manually deleted. The root
Application already includes this cluster-specific values file.

The stock clustergroup 0.9.58 map-form namespace helper omits OperatorGroup
annotations, so the override disables only that generated object and renders
the same name, namespace and all-namespaces scope through `extraObjects`.
Argo retains ownership of the same Kubernetes object. No chart fork is needed.
See [OLM bundle retry documentation](https://olm.operatorframework.io/docs/troubleshooting/subscription/#subscriptions-failing-due-to-unpacking-errors)
and [OLM's timeout annotation implementation](https://github.com/operator-framework/operator-lifecycle-manager/blob/master/pkg/controller/bundle/bundle_unpacker.go).

Wait for ESO, Vault auth and secret loading before VM users. If the original
installer times out, use the documented `./pattern.sh make load-secrets` after
those dependencies are ready; do not create ad hoc Vault policies or tokens.

### Nested-cluster CPU contention

After ESO recovery, both `virt-operator` replicas repeatedly failed their stock
liveness probes before serving metrics. A read-only `/proc/stat` sample on
control-plane-1 measured approximately 73% CPU steal; its load average was 96.
This indicates outer-hypervisor CPU contention, not memory exhaustion in this
cluster. It is a likely contributor to slow startup, not proof of the sole cause.

The site file uses supported Subscription `config.resources` to request
`250m` CPU and `512Mi` memory per CNV operator container, without limits. The
largest original bundle requests were `200m` CPU and `450Mi` memory. This raises
CPU scheduling weight without reducing any existing request. It applies to all
eleven operator deployments in that subscription, not just `virt-operator`;
OLM owns their rollout. No health probes or operator binaries are changed.
See [OLM Subscription resource configuration](https://github.com/operator-framework/operator-lifecycle-manager/blob/master/doc/design/subscription-config.md#resources).

This tuning cannot guarantee outer-host CPU capacity. Require real operator,
HyperConverged and VM readiness; an Argo Application reporting Healthy is not
sufficient. If contention persists, the RHDP infrastructure needs more available
CPU or relocation before this environment can qualify the baseline.

The SAW Keycloak chart additionally exposes optional `keycloak.resources`,
forwarded unchanged to the supported Keycloak CR `spec.resources`. Its empty
default preserves the original render; existing-server mode never modifies the
shared server. The lab requests `500m` CPU while preserving the operator's
`1700Mi` memory request and `2Gi` memory limit, with no CPU limit. The RHBK
operator owns the resulting rollout. This is a chart input addition, not a
Keycloak binary, probe, realm or authentication change. It is the one integration
code addition to this VM baseline; do not describe the branch as site-values-only.
See [Keycloak resource requirements](https://www.keycloak.org/operator/advanced-configuration#_resource_requirements).

Recovery results so far: standard `make load-secrets` exited zero, Vault's
ClusterSecretStore reports Ready, RHDH ExternalSecrets report SecretSynced,
both tuned `virt-operator` replicas became Ready, and realm import reports
Done/Job Complete. Full platform readiness remains required before the two VM
acceptance users are deployed.

The first Keycloak server was already unhealthy when its resource request was
changed. Its `OrderedReady` StatefulSet waited on the old Pod before replacing
it, leaving the new request only in the template. Recovery uses the existing
`keycloak.instances` chart input in two GitOps stages: zero, wait for the
operator-managed server Pod to disappear, then one. PostgreSQL/PVC and imported
realm remain intact; no direct Pod deletion or StatefulSet patch is used.
This is recovery history only. A fresh installation starts with one replica
and the final CPU request from the beginning.

The zero-replica stage was observed in both the Keycloak CR and StatefulSet,
and the old server Pod disappeared before restoring one replica. HyperConverged
also reached Available=True, Progressing=False, Degraded=False and
Upgradeable=True. The replacement Keycloak Pod became Ready without restarting;
the Keycloak CR, owner resolver and redirect registrar subsequently became Ready.
RHDH's three init containers completed successfully. Its standard OIDC-client
Job also completed, creating the client, catalog-reader roles and default user
group. RHDH subsequently became Ready. No workload inference is claimed by this
platform receipt.

The private values file must supply `inference.provider=openai`, the private API-key file, model `gpt-4.1-mini`, generated SSH-key file references and the standard generated RHDH OIDC/session fields. Omit the unused web-search entry. Use `VALUES_SECRET` to select that file explicitly; do not overwrite unrelated home-directory secrets.

## Verification receipt — 2026-11-04

- Cluster API/certificate login works; all cluster operators available, no degraded operator reported at preflight. Platform Keycloak realm import completed and authentication recovered.
- Worker `worker-cluster-glmhg-1`: `/dev/kvm` present, VMX exposed. The read-only debug pod was removed automatically. CNV scheduling still requires the operator installation and live VM test.
- Upstream `make prereqs-check` passed with OpenShell 0.1.2.
- Golden image mirror completed and internal digest matches the selected source index.
- Official OpenAI API model listing authenticated successfully; model listed. This is not yet an inference test from SAW.
- `make catalog`, `make catalog-check`, BOM render and a canary saw-users render passed.
- Platform bootstrap gate passed: the documented `pattern.sh make argo-healthcheck`
  exited zero with all ten Applications Synced/Healthy; Keycloak, both identity
  helpers and both RHDH containers are Ready; its OIDC-client Job is Complete.
- The next declared inventory contains `sawvmowner` and `sawvmother`, each using
  `data-science` with NetworkPolicy enabled. It exactly matches the successful
  bastion preflight input; Helm renders six child Applications. VM guest startup,
  inference, owner isolation, persistence and RHDH self-service acceptance remain
  pending. No container/Kata qualification is claimed.

Operator channels and external chart ranges remain upstream defaults. This freezes workload image selections, not every future dependency resolution. Record the installed CSV/chart versions when the platform converges before claiming deterministic replay.

### VM model-selection recovery (qualification pending)

Both root disks imported successfully and both VMs reached Running. The first
guest completed component installation, but profile apply failed when OpenClaw
validated `agents.entries.main.model` for `openai/gpt-4.1-mini`. Its pinned
`2026.9.6` image reported an empty local OpenAI catalog before its gateway started.
The configured wildcard already selected the `openclaw` runtime; no missing
runtime setting was demonstrated. The provider's live API had independently
listed this model. Tool-gate configuration follows model selection, so its
absence in this failed apply is a downstream failure, not a passed security test.

The recovery uses the existing explicit-endpoint profile inputs above. Native
onboarding depends on catalog resolution; explicit onboarding writes the model
definition for the requested endpoint. The installer still validates the model
and tool gate. After Argo sync, apply changed disk-backed inputs using the
documented restart, retaining the root PVC:

```bash
make saw-restart OPENSHELL_SAW_NAME=sawvmowner SAW_NS=saw-sawvmowner
make saw-status OPENSHELL_SAW_NAME=sawvmowner SAW_NS=saw-sawvmowner \
  SSH_KEY_PATH=/home/lab-user/.saw-private/glmhg/sandbox-ssh
```

Qualify the first VM before restarting `sawvmother` in the same way. Require
both `install.phase` and `apply.phase` to be `Done`, then run real inference,
cross-owner denial, credential isolation, persistence and portal tests. This is
a GitOps configuration recovery, not evidence of a clean first-pass VM install.
