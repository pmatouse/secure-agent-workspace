# SAW TP provider and driver support matrix

**Updated:** 2026-11-06. Historical VM live results: 2026-10-21.

Keep implementation, offline contracts and live qualification separate. The
Kubernetes integration now compiles native OpenAI, Anthropic and NVIDIA
providers, uses the shared governance/credential policy, and reconciles them
through the stock gateway. This does not by itself qualify a live provider.

## Validation matrix

| Provider | Historical VM model | Podman live (2026-10-21) | Kubernetes offline contracts | Kubernetes live qualification |
|---|---|---|---|---|
| OpenAI | `gpt-6-luna` | Historical pass; see scope below | Passed: native protocol/config, marker/host policy, mutable selection | Initial sandbox API inference, owner browser chat and audited tool decisions passed on both data-science slots; model-update and complete RHDH lifecycle qualification remain blocked; see below |
| Anthropic | `claude-sonnet-4-6` | Historical pass; see scope below | Passed: native Messages protocol/config, marker/host policy, mutable selection | Not qualified |
| NVIDIA | `nvidia/nemotron-3.5-lightning-30b-a3b` | Historical pass; see scope below | Passed: OpenAI protocol/config, marker/host policy, slash-qualified model selection | Not qualified |

Offline cases use synthetic credentials and Node execution of the actual
compiled OpenClaw configuration. Provider recovery tests cover a lost create
response, process restart and a later intent generation; drift, replacement,
changed markers and missing receipts fail closed. The Rust admission contract
test consumes the actual Helm/compiler harness output (3 volumes/5 mounts,
also with 16 extra data volumes) and rejects altered aliases. CI requires that
Rust test to execute, rather than silently treating a missing toolchain as a pass.

## Historical VM results

The 2026-10-21 results covered authenticated inference from a sandbox through
the in-VM OpenShell sandbox proxy, before namespace credential isolation. Each
API returned **HTTP 200** with a response matching the test prompt. These results
do not qualify the current namespace-proxy path or candidate installation.

OpenClaw chat also returned responses from all three providers. NVIDIA passed
with both an explicit model selection and the configured notebook default.

The historical backend was Podman inside KubeVirt VMs on OpenShift. This does
not validate the OpenShell Kubernetes driver. Environment identities and raw
live evidence belong in the separate qualification record, not this matrix.

## Remaining work

Follow [provider qualification](provider-driver-qualification.md) against the
candidate runtime and governance images: sandbox API inference, owner browser
chat, update/restart, credential isolation and RHDH delete. Record immutable
image/Git revisions and actual Kubernetes workload identities in that record.
Anthropic and NVIDIA require separate native-provider runs with real credentials
before their live cells can pass. Do not infer their results from OpenAI success.

The current OpenAI result uses the official remote API through the Kubernetes
credential proxy. The CUDA-named sandbox does not imply local GPU inference.
The stock gateway also passed committed-provider-response recovery with a fresh
temporary administrator identity; the same provider ID/version was recovered
and the disposable provider and temporary credentials were removed afterward.
These checks do not replace RHDH lifecycle or final clean-install qualification.

Current qualification also exposed failures that remain distinct from the
initial inference pass:

- A model update reached Ready and preserved storage, but a stock notebook
  OpenClaw release migrated the requested model to another model. Direct API
  inference used the requested model; the chat transcript did not. Model-update
  parity requires both paths to agree with the approved input.
- The stock CLI's browser-forward process briefly closes its listener when
  its OIDC token expires. New-request recovery and established WebSocket
  reconnection must be tested separately; a successful readiness check does
  not establish uninterrupted chat.
- An identity-service upgrade rejected the existing service-account admin API
  tokens and blocked RHDH enrollment. The shared bootstrap now assigns the
  supported built-in Admin API scope; live reads recovered for all three
  service clients with unchanged roles. Bootstrap runs during Sync to avoid
  waiting for the identity-dependent ApplicationSet's health. The portal also
  preserves the prior workspace projection on lookup failure. These recovery
  checks do not qualify a complete enrollment or fresh installation.

Credential-marker and destination denials passed in isolated live checks.
Separate direct-connect probes from both application Pods timed out to two
currently resolved OpenAI IPv4 addresses on TCP/443, while mediated inference
succeeded before and after; the stock deny-all network policies remained in
place. This bounds the network result to the tested destinations and transport.
An authenticated second owner was denied access to the first owner's notebook
in the browser, with the proxy confirming the rejected identity. Complete
profile/lifecycle coverage and retesting of the final candidate remain required.
Keep detailed failures and immutable revision evidence in the separate
qualification record.

The container compiler currently selects one inference provider per sandbox;
additional simultaneous `inference.models` chat choices remain unsupported and
fail closed. Kata/confidential runtime qualification is outside this matrix.

## Scope

The historical live scope was inference in existing workspaces after credential
and model updates. It did not qualify clean installation, restart recovery,
tools, or memory embeddings. The current candidate still needs its own
installation, browser lifecycle, persistence and denial checks. Offline tests
and image builds do not satisfy those live criteria.
