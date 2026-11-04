# Future proposal: independent supervisor RuntimeClass

**Status: design only.** Current SAW integration uses a stock ordinary supervisor
Pod and optionally a Kata workload Pod. No OpenShell source patch, image rebuild,
admission mutator or Kyverno dependency is shipped. Native runtime policies are
documented in the [policy chart](../../charts/saw-runtime-policies/README.md).

## Upstream gap

Source reviewed: `opendatahub-io/openshell` `v0.1.2-rhaiv.6`, commit
`305c8b3d7bbdb97a6f2f7264c3ad43b0087c307f`.

| Source | Current behavior |
|---|---|
| [`KubernetesComputeConfig`](https://github.com/opendatahub-io/openshell/blob/305c8b3d7bbdb97a6f2f7264c3ad43b0087c307f/crates/openshell-driver-kubernetes/src/config.rs#L158) | `default_runtime_class_name` defaults to empty; there is no supervisor placement field. Unknown config fields are rejected. |
| [Workload Pod template](https://github.com/opendatahub-io/openshell/blob/305c8b3d7bbdb97a6f2f7264c3ad43b0087c307f/crates/openshell-driver-kubernetes/src/driver.rs#L6390) | Resolves class from template, caller config, then driver default. |
| [`supervisor_pod`](https://github.com/opendatahub-io/openshell/blob/305c8b3d7bbdb97a6f2f7264c3ad43b0087c307f/crates/openshell-driver-kubernetes/src/sandbox_runtime.rs#L211) | Separate Pod; `PodSpec` omits `runtime_class_name`. |
| [Creation](https://github.com/opendatahub-io/openshell/blob/305c8b3d7bbdb97a6f2f7264c3ad43b0087c307f/crates/openshell-driver-kubernetes/src/driver.rs#L2426) and [new generation](https://github.com/opendatahub-io/openshell/blob/305c8b3d7bbdb97a6f2f7264c3ad43b0087c307f/crates/openshell-driver-kubernetes/src/driver.rs#L3228) | Both build supervisors through the same helper. |

Kata is Pod-scoped. Setting only the existing workload field cannot place the
separate supervisor into another Kata VM. The protocol already connects the two
Pods over a Service/TCP boundary; a future placement option should preserve that
protocol and its Pod UID/generation binding.

## Proposed administrator-only configuration

```yaml
# Proposed fields inside Kubernetes compute-driver configuration.
# supervisor_runtime_class_name does NOT exist in the pinned release.
default_runtime_class_name: kata-workload
supervisor_runtime_class_name: kata-supervisor
```

The new supervisor field defaults to empty, preserving the ordinary supervisor
Pod. A nonempty value selects a preinstalled, administrator-approved RuntimeClass.
It must not derive from `CreateSandbox` input, workload template values or caller
`driver_config`. Workload runtime selection remains independent. No new port or
new trusted transport is necessary solely for placement.

Illustrative change shape, **not an applicable patch**:

```diff
 // config.rs: KubernetesComputeConfig and its Default
+pub supervisor_runtime_class_name: String,
+supervisor_runtime_class_name: String::new(),

 // sandbox_runtime.rs: supervisor_pod parameter and PodSpec
+supervisor_runtime_class_name: &str,
+runtime_class_name: (!supervisor_runtime_class_name.is_empty())
+    .then(|| supervisor_runtime_class_name.to_string()),

 // driver.rs: BOTH initial creation and replacement/generation call sites
+&self.config.supervisor_runtime_class_name,
```

Before proposing upstream, also implement configuration syntax validation and
administrator-approved RuntimeClass metadata checks in initial creation and
restart paths. Missing, deleting or unauthorized classes must fail without
retrying on the default runtime. Pin/check the admitted class identity where the
driver's resource-admission contract requires it. Do not reuse the entire
workload resource inventory on a supervisor: supervisors intentionally have
projected bootstrap credentials that the workload inventory forbids.

The current native VAP explicitly requires an ordinary supervisor. Enabling a
future supported field would therefore require a coordinated policy change:
admit only the exact supervisor class, keep its role/account/gateway labels
immutable and preserve the workload class constraint. It must remain impossible
to opt out through sandbox input.

## Admission-only alternative, future research

A narrowly scoped native admission mutation could insert a supervisor class on
CREATE while a separate VAP requires that exact value. This would keep binaries
stock, but a production-supported mutator must first exist on the target
OpenShift release. Native `MutatingAdmissionPolicy` on the proposed OpenShift
4.22 baseline is a Technology Preview / `TechPreviewNoUpgrade` consideration,
not a dependency to enable for this integration. Do not switch the cluster's
feature set or claim that stock OpenShift supplies an independent stable
mutation controller. Kyverno is intentionally not part of the current design.
[OpenShift 4.22 feature-gate declaration](https://github.com/openshift/api/blob/release-4.22/features/features.go#L85)

Source review found no full supervisor Pod-spec hash or explicit RuntimeClass
comparison in bootstrap/recovery. Identity checks use Pod UID, role/pair/sandbox
labels and the Sandbox owner. That makes admission-time placement a plausible
future integration; it is **not** evidence that dual-Kata bootstrapping works.
Projected tokens, bootstrap Secret handling, Service access, probes and restart
generation still require end-to-end validation.

## Required verification before adoption

1. Rust config tests: empty default, explicit field parsing, invalid names;
   backward compatibility and no caller-controlled supervisor override.
2. Pod-builder tests: unset field omitted; configured field exact; existing
   security context, owner, labels, scheduling gate, volumes and token audience
   unchanged. Both creation paths pass the administrator field.
3. API tests: missing/deleting/unauthorized RuntimeClass fails before releasing
   the supervisor's bootstrap gate; class replacement/restart is revalidated.
4. A supported stock Kata cluster: ordinary/ordinary, ordinary/Kata and then
   Kata/Kata; UID-bound bootstrap, exec/session/SSH, provider/proxy connections,
   workspace persistence and generation recovery all pass.
5. Preserve stock workload deny-egress fence and external ANP behavior. Invalid
   supervisor/workload classes and direct workload egress remain denied.

With an upstream change checked out, run its normal Rust checks in CI (not on
the storage-constrained workstation):

```sh
cargo fmt --all -- --check
cargo test -p openshell-driver-kubernetes --lib
```

These commands have not been run for a patch: there is no patch in this repository.
