# RHDH container workspace

The owner uses the same RHDH create/update and delete templates as a VM user.
The verified Backstage token selects the user; the form chooses a deployment
mode and BOM profile. GitOps owns the workload. This path is an opt-in pilot;
the default portal remains VM-only.

| Shared with VM | Specific to an audited container |
|---|---|
| Request Secret → Tekton → verified caller → Vault and registry | Only an enrolled owner and the `audited-openclaw` BOM are accepted. |
| ApplicationSet → `portal-ws-<user>` → `saw-users` | The last child renders `saw-portal-container`; no VM or VM SSH Secret is rendered. |
| Same profile catalog, BOM chart and installation generation | A create allocates an installation ID. Updates keep it and increment the runtime intent generation. |
| Delete mark → foreground Argo cleanup → generation-scoped Vault cleanup | Wait for the runtime, control and browser namespaces to disappear. The audit history claim is in a separately retained namespace. |

```text
RHDH → signed request → Tekton → Vault: hub/saw-USER/REG/inference
                              ↘ registry → ApplicationSet → owner Application
                                            ├─ saw-bom: audited OpenClaw profile
                                            └─ container chart
                                               ├─ saw-USER: stock gateway + supervisor/workload
                                               ├─ saw-ctl-REG: ESO → credential proxy; gateway admin identity
                                               ├─ saw-ui-REG: owner browser relay
                                               └─ saw-history-REG: restricted writer + retained SQLite PVC
```

The diagram shows the intended complete lifecycle. The chart currently projects
identity, network/admission policy, proxy, gateway and audit storage/writer from
operator-pinned chart revisions. The container is **not ready** until the
controller reports the exact current BOM/intent hash and the owner chat route
returns an authentication redirect. The portal cannot provide a route, owner
subject, arbitrary Helm values, or a Vault path through its form.

**Qualification boundary:** request handling, generation fencing, namespace
cleanup checks, and stock child-chart rendering have automated tests. New
registrations still require a trusted handoff for the boundary approvals, PVC
UIDs, writer public key and initial gate, then the owner-scoped browser relay.
The linked manually qualified workspace is not evidence of a self-service
create. Do not enable the example as a working end-to-end installation until a
fresh owner create, update, chat approval/denial and delete have passed together.

```sh
python3 -m pytest -q tests/portal/test_portal.py tests/charts/test_portal_container.py
PYTHONPATH=kubernetes-runtime python3 -m pytest -q tests/kubernetes_runtime/test_boundary.py
python3 scripts/saw-profile-catalog.py --check
```

[Site values](../../examples/portal-container/glmhg.yaml) contain no credential.
The API key is entered as an RHDH secret and ESO copies only its `api_key` field
to the trusted namespace. The gateway and agent have no mount of that Secret.
The [owner acceptance client](../../tests/acceptance/rhdh_workspace.py) uses
the installed scaffolder and an owner login. `inspect` is read-only; `create`
and `update` submit a template and return a task ID, not a success assertion.
