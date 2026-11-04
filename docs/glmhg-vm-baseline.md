# glmhg VM baseline

This branch is upstream `c9691be3ff0a9a2dde4fee91514b5215bbcb9275` plus site configuration. It does not include the container/Kata implementation. Installation follows README Option A through the Validated Patterns utility container and Argo CD.

## Site inputs

- OpenShift 4.22.20, AMD64, OVN-Kubernetes, default `ocs-external-storagecluster-ceph-rbd`.
- Cluster UID: `8a8c74bb-2c80-43d5-b7fb-a00d422c47f2`.
- API: `https://api.cluster-glmhg.dyn.redhatworkshops.io:6443`.
- Topology and image selections: `overrides/saw-users.yaml`.
- Both data-science workspaces use the official OpenAI API and `gpt-4.1-mini`; no NVIDIA credential is needed. Their supported profile YAML and generated RHDH catalog describe that selection.
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

The private values file must supply `inference.provider=openai`, the private API-key file, model `gpt-4.1-mini`, generated SSH-key file references and the standard generated RHDH OIDC/session fields. Omit the unused web-search entry. Use `VALUES_SECRET` to select that file explicitly; do not overwrite unrelated home-directory secrets.

## Verification receipt — 2026-11-04

- Cluster API/certificate login works; all cluster operators available, no degraded operator reported at preflight. Platform Keycloak realm import completed and authentication recovered.
- Worker `worker-cluster-glmhg-1`: `/dev/kvm` present, VMX exposed. The read-only debug pod was removed automatically. CNV scheduling still requires the operator installation and live VM test.
- Upstream `make prereqs-check` passed with OpenShell 0.1.2.
- Golden image mirror completed and internal digest matches the selected source index.
- Official OpenAI API model listing authenticated successfully; model listed. This is not yet an inference test from SAW.
- `make catalog`, `make catalog-check`, BOM render and a canary saw-users render passed.
- Full platform installation and VM/RHDH acceptance remain pending; no container/Kata qualification is claimed.

Operator channels and external chart ranges remain upstream defaults. This freezes workload image selections, not every future dependency resolution. Record the installed CSV/chart versions when the platform converges before claiming deterministic replay.
