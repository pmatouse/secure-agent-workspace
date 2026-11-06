# SAW TP provider and driver support matrix

**Updated:** 2026-11-06. Historical VM live results: 2026-10-21.

Keep implementation, offline contracts and live qualification separate. The
Kubernetes integration now compiles native OpenAI, Anthropic and NVIDIA
providers, uses the shared governance/credential policy, and reconciles them
through the stock gateway. This does not by itself qualify a live provider.

## Validation matrix

| Provider | Historical VM model | Podman live (2026-10-21) | Kubernetes offline contracts | Kubernetes live (this revision) |
|---|---|---|---|---|
| OpenAI | `gpt-6-luna` | Passed; see scope below | Passed: native protocol/config, marker/host policy, mutable selection | Pending glmhg qualification |
| Anthropic | `claude-sonnet-4-6` | Passed; see scope below | Passed: native Messages protocol/config, marker/host policy, mutable selection | Blocked: no test credential |
| NVIDIA | `nvidia/nemotron-3.5-lightning-30b-a3b` | Passed; see scope below | Passed: OpenAI protocol/config, marker/host policy, slash-qualified model selection | Blocked: no test credential |

Offline cases use synthetic credentials and Node execution of the actual
compiled OpenClaw configuration. Provider recovery tests cover a lost create
response, process restart and a later intent generation; drift, replacement,
changed markers and missing receipts fail closed. The Rust admission contract
test consumes the actual Helm/compiler harness output (3 volumes/5 mounts,
also with 16 extra data volumes) and rejects altered aliases. CI requires that
Rust test to execute, rather than silently treating a missing toolchain as a pass.

## Historical VM results

All three providers passed authenticated inference requests from inside the
sandbox through the in-VM OpenShell sandbox proxy, before namespace credential isolation. The namespace-proxy path is **not yet re-validated** for this matrix. Each API returned **HTTP 200**
with a response matching the test prompt.

OpenClaw chat also returned responses from all three providers. NVIDIA passed
with both an explicit model selection and the configured notebook default.

**Environment:** OpenShift with Podman running inside KubeVirt VMs;
`default/notebook` in `saw-provider-test` (OpenAI and Anthropic) and
`saw-nvidia-test` (NVIDIA). Running on OpenShift does not validate the
OpenShell Kubernetes driver.

## Remaining work

Follow [provider qualification](provider-driver-qualification.md) against the
candidate runtime and governance images: sandbox API inference, owner browser
chat, update/restart, credential isolation and RHDH delete. Record immutable
image/Git revisions and actual Kubernetes workload identities. Anthropic and
NVIDIA require real provider credentials before their live cells can pass.

The container compiler currently selects one inference provider per sandbox;
additional simultaneous `inference.models` chat choices remain unsupported and
fail closed. Kata/confidential runtime qualification is outside this matrix.

## Scope

Validation covers inference in existing workspaces after credential and model
updates. Clean deployment, restart recovery, tools, and memory embeddings are
not validated. A memory-embedding credential error was observed separately
while chat succeeded.
