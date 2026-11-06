# glmhg deployment inputs

This branch contains the cluster's GitOps values. The reusable implementation
and installation guide are on
[`dev/container-kata-deployment`](https://github.com/pmatouse/secure-agent-workspace/blob/dev/container-kata-deployment/docs/container-site-replay.md).

| Owner | Deployment | Approved profile | Access |
|---|---|---|---|
| `sawk8sowner` | Container | `custom-inference` | Existing headless OpenClaw workspace; unchanged runtime pin |
| `sawdsowner` | Container | `data-science` | Two owner-only browser chats: notebook and CUDA-development sandbox |

In RHDH, sign in as the approved owner and choose **Container → data-science**.
Supply the official OpenAI key and the two model selectors. The two chat links
appear in the workspace catalog after provisioning. This profile uses remote
OpenAI inference; it does not allocate a local GPU. Profile approvals are
owner-specific, even though the form lists the site's reviewed profiles.

The data-science public inputs are `data-science-inputs.yaml`. The generated
`data-science-owner.yaml` pins the exact shared VM BOM, controller image,
source revision, model inputs and browser configuration. Its independently
reviewed platform boundary is `data-science-reviewed-boundary.json`.
`values-prod.yaml` includes this owner file in the RHDH application's values.
Credentials are entered through RHDH and loaded into Vault/ESO; these files
contain no provider key or user password.

The shared runtime image was built by the GitOps-managed BuildConfig in
`container-foundation/build.yaml`, from source
`431ce749537117aab6cc2f0c8a43598c0e05123b`. The VM installer also contains the
canonical `saw_core.py`; its exact bytes are embedded inside `apply_bom.py`
under the existing signing-manifest format. Running VMs adopt installer
changes at their documented restart boundary.

The lifecycle qualification creates a disposable registration, tests both
chats and model changes, verifies persistence across stop/start, then deletes
the registration. The owner approval remains available for another creation;
the audit namespace is retained. See the reusable guide for commands and
acceptance evidence.

The 2026-11-06 fresh container run passed all of these gates, including
read-only remount checks after deletion. Both fresh VM browser chats also
passed with the same shared-core bytes. The earlier damaged `sawvmother`
upgrade canary is retained separately for diagnosis. Public receipts:
[container](https://github.com/pmatouse/secure-agent-workspace/blob/dev/container-kata-deployment/tests/acceptance/data-science-shared-rollout-2026-11-06.json),
[VM](https://github.com/pmatouse/secure-agent-workspace/blob/dev/container-kata-deployment/tests/acceptance/vm-shared-core-2026-11-06.json).
