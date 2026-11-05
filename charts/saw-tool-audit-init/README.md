# Append-only tool audit

The VM installer applies `chattr +a` to the existing tool gate's JSONL audit
file. On an ext4-backed PVC, the preparation Job sets the same inode flag with
`FS_IOC_SETFLAGS`. It opens the file with append and no-follow, verifies its
owner, link count and type, and refuses to adopt an existing unsealed, nonempty
log. Re-running the Job verifies the sealed inode. Each sandbox needs its own
retained audit PVC.

The opt-in chart grants `LINUX_IMMUTABLE` to one named nonroot Job service
account. A native validating policy limits it to the pinned command, named
claim and stock Job controller. The Pod drops all other capabilities, has a
read-only root, and mounts no API token. Deploy the admission policy and binding
before granting SCC use. Review the rendered cluster-scoped policy with the
platform administrator. The sandbox and the relay continue under restricted-v2.

Render the manifests for review with a digest of the SAW controller image that
contains the preparation module:

```sh
helm template audit charts/saw-tool-audit-init --namespace "$NAMESPACE" \
  --set enabled=true --set-string image="$CONTROLLER_IMAGE" \
  --set-string auditClaim="$AUDIT_CLAIM"
```

The audit PVC must already exist. Its name starts with `saw-audit-`. The stock
driver mounts its `log` subdirectory at `/sandbox/.saw/audit`. The runtime
requires a successful append-mode open and a kernel refusal of a plain writable
open. Treat a filesystem that cannot preserve the flag across detach and
reattach as unsupported. A separate restricted Job can run
`python3 -m saw_kubernetes.prepare_gate --owner … --subject … --workspace … --sandbox …`
with the dedicated policy PVC at `/volume`. Its `bundle` subdirectory mounts
read-only at `/sandbox/.saw/trusted`. Both claims have the usual workspace,
installation and UID checks. Provision a new gate claim for a new bundle.

The optional controller binding prepares the OpenClaw plugin configuration.
The application tool deny list stays in force until the live gateway dispatch,
approval, audit retention and tamper tests pass.

On the `glmhg` OpenShift 4.22.20 test, SCC and native admission policy
installation succeeded. Pod Security Admission then rejected the Job before
a Pod started because its namespace enforces `restricted`. The capability is
outside that profile. A matching SCC alone is insufficient. Keep this chart
disabled in a restricted workspace namespace. The isolated grant, Job and
disposable PVC were pruned after this check.
