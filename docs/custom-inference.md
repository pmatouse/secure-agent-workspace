# Custom inference endpoint (vLLM, Ollama, NIM, any OpenAI-compatible server)

A SAW can use a model server of your own instead of a cloud provider.
OpenShell 0.1.x removed managed inference routing (`openshell inference`,
`https://inference.local`), so the agent calls the endpoint itself:

- The endpoint, the model and the key are the `inference` Secret (`url`,
  `model`, `api_key`). The `custom-inference` SAW-BOM profile reads them
  through the sandbox's `inference:` block; the installer validates the URL
  and onboards OpenClaw against it.
- The key never enters the VM or sandbox. The namespace credential proxy
  replaces a marker only for the host of `url` in the credential Secret.
  Keyed endpoints require HTTPS on port 443 with a publicly trusted
  certificate. The gateway's governance profile separately permits the
  sandbox binary to reach that host.
- The pattern ships no profile for a host it cannot know. **You add one**,
  as a plain OpenShell profile file under `overrides/governance-profiles/`,
  and the `governance-extra-profiles` application serves it next to the
  shipped profiles. OpenShell recommends exactly this (one profile per
  credential) over reusing the `openai` profile for another host.

## Configure

1. **The profile.** Copy the chart's example,
   `charts/governance-policy/profiles/examples/custom-inference.yaml`, to
   `overrides/governance-profiles/custom-inference.yaml` (shipped as that
   same example), set `endpoints` to your server, and uncomment the
   `configMapGenerator` in `overrides/governance-profiles/kustomization.yaml`
   listing the file:

   ```yaml
   id: custom-inference
   ...
   endpoints:
     - host: models.example.com    # the host of the url below
       port: 443                   # keyed HTTPS only
       protocol: rest
       enforcement: enforce
       access: read-write
   ```

   The proxy binds a deployment-owned provider only to the Secret's `url`
   host, even if its governance profile lists more hosts. A second server
   with its own key is a second file with its own
   `id`, used by a provider with that `type` **and that name**: the
   governance interceptor matches a sandbox's providers by profile id, so a
   governed provider is always named after its type (the installer refuses
   anything else).

2. **Egress.** A host outside the cluster must be allowed by the VM
   firewall: `egress.extraAllow` under `defaults.openshellSaw` (or one
   user's `values`) in `overrides/saw-users.yaml`. An in-cluster Service
   (`*.svc`) needs a `networkPolicy.extraEgress` rule instead
   ([Egress from the VM](deployment-guide.md#egress-from-the-vm)).

3. **The profile selection.** The workspace uses `profiles: [custom-inference]`
   (a user entry in `overrides/saw-users.yaml`, the portal, or
   `make saw-create ... PROFILES=custom-inference`).

4. **The Secret** (`~/values-secret-secure-agent-workspace.yaml`, then
   `./pattern.sh make load-secrets`; the quickstart's `make saw-create
   PROVIDER=custom-inference MODEL=... ENDPOINT_URL=... API_KEY=...` writes
   the same keys):

   | Key | Value |
   |---|---|
   | `url` | the OpenAI-compatible base URL, ending in `/v1` |
   | `model` | the model name the server serves |
   | `api_key` | the server's key, mounted only by the namespace proxy; for keyless HTTP use `API_KEY=''` in quickstart |
   | `provider` | optional: `custom-inference` (the installer refuses a key labelled for another service); leave it out of a Secret shared with other profiles |

   The VM mounts `inference-meta`, containing every non-credential field
   selected by the profile catalog (including `url`, `model`, and optional
   `provider`), with no `api_key`. A deployment-owned keyed provider's
   `inference.baseUrl` must reference `{secretKeyRef: {name: inference, key: url}}`
   so the installer and proxy use the same host.

5. Commit and push steps 1-3, wait for Argo CD, then restart the VM
   (`make saw-restart`) so the installer applies the Secret.

### Changing the endpoint

Change `url` in the Secret and `host`/`port` in the profile file (and
`extraAllow`), push, restart the VM. The sandbox is not recreated: the
endpoint is agent configuration (`inference:`), not sandbox environment, so
`/sandbox` is untouched; OpenClaw is onboarded again against the new URL.

## How the pieces fit

| Where | What | Changed by |
|---|---|---|
| `overrides/governance-profiles/<id>.yaml` | which host(s) the key may reach | git |
| `inference` Secret in Vault | `url`, `model`, `api_key` | `load-secrets` / the portal |
| `charts/saw-bom/profiles/custom-inference` | provider `type: custom-inference`; sandbox `inference:` reading the Secret | shipped |

The installer sees `custom-inference` as a type it neither has built in
nor ships, looks it up in the gateway's live catalog, and takes the
credential variable (`CUSTOM_INFERENCE_API_KEY`) from the served profile.
If the profile is not there yet (the extra-profiles app has not synced,
or the file is not listed), the apply fails before creating anything, with
a message naming this directory. The sandbox's `inference.protocol` is
stated (`openai`): the installer cannot infer it for a profile of your own.

## Requirements

- The **credential proxy** must reach keyed HTTPS endpoints; the **VM**
  must reach keyless HTTP endpoints such as `http://vllm.<ns>.svc:8000/v1`.
  `localhost` is refused.
- `url` must be `http(s)://host[:port][/path]` without credentials, query or
  fragment. The installer rejects anything else without logging the value.
- A keyed HTTPS endpoint must use port 443 and a publicly trusted
  certificate. Other HTTPS ports are refused. HTTP bypasses credential
  injection and sends only a marker, so use it only for a keyless server.
  Custom keyed ports and in-cluster service-CA trust are follow-up work.
- `inferenceTimeout` on a provider is no longer used: there is no gateway
  router to time out. Use the sandbox's `inference.timeoutSeconds`.

## Limitations

- One custom endpoint per deployment is the shipped shape; a second server
  is a second profile file and a provider of that type (and, for the shipped
  `custom-inference` BOM profile, a copy of it with that type).
- With governance **off** the gateway reads only the profiles the installer
  ships; extra profiles are not delivered to the VM. Keep governance on for
  custom endpoints.
- NemoClaw sandboxes onboard their own provider settings; the profile only
  ships an OpenClaw sandbox.

## Container deployment

The container backend uses the same `custom-inference` BOM, input resolver and
credential broker. The shipped notebook has no browser route. Its OpenClaw
agent can be used through the normal OpenShell workspace access path. The
container implementation currently supports **one keyed HTTPS endpoint on port
443 per registration**, with a DNS hostname and a base path ending in `/v1`.

1. Install the extra OpenShell governance profile described above in the
   workspace gateway's governance deployment. For this container contract its
   single enforced endpoint must match the site host, and its `api_key`
   credential must declare `CUSTOM_INFERENCE_API_KEY`. The controller checks
   the platform-scoped profile returned by the gateway before creating the sandbox.
2. Pin a supporting controller image and the notebook image approved for the
   site's OpenShift UID range. In the existing container owner's site YAML add
   the rendered BOM digest to `automaticEnrollment.approvedProfiles`. Supply the
   profile-specific reviewed boundary and endpoint, for example:

   ```yaml
   profileBoundaries:
     custom-inference:
       inferenceBaseURL: https://models.example.com/v1
       allowHosts: [models.example.com]
       reference: <reviewed boundary map for this owner and proxy configuration>
   ```

3. In RHDH choose **Container** and **custom-inference**. Enter the endpoint URL,
   the served model ID and the provider API key. The portal compares the URL
   to the site value before writing to Vault. Web search is disabled for this
   dedicated broker. Changing endpoint requires a fresh registration.
4. ESO merges the enrolled URL into the broker's trusted Secret and reads only
   the API key from Vault. OpenClaw receives a marker. The stock broker uses the
   Secret's URL to bind that marker to one host. The shared BOM resolver supplies
   the model and timeout (300 seconds in the shipped profile). With model lifecycle
   enabled, model updates use the existing publication and restart flow.

### Run the controlled endpoint test

Use the tested runtime image digest and an OpenShift namespace with permission to
pull it and the pinned notebook image. From the repository root:

```sh
ns=saw-k8s-build
id=check-$(date +%s)
python3 tests/acceptance/custom_inference_fixture.py --runtime-image "$RUNTIME_IMAGE" --suffix "$id" |
  oc -n "$ns" create -f -
oc -n "$ns" wait --for=condition=complete "job/custom-inference-$id" --timeout=16m
oc -n "$ns" logs "job/custom-inference-$id" -c agent
oc -n "$ns" logs "job/custom-inference-$id" -c endpoint
oc -n "$ns" delete job,configmap,networkpolicy -l "saw.redhat.com/fixture=custom-inference-$id"
```

The Job compiles the actual BOM with the packaged runtime and runs the stock SAW
broker, OpenClaw notebook and an isolated OpenAI-compatible HTTPS responder.
It uses a fresh random key and private fixture CAs. An accepted response requires
the rewritten bearer credential and the requested model ID. The client verifies
the challenge response and requires HTTP 403 for a CONNECT to a second hostname.
The Job checks application and broker behavior. RHDH owner enrollment and a
production model server are separate qualification steps.

The glmhg run used the packaged controller image
`image-registry.openshift-image-registry.svc:5000/saw-k8s-build/saw-runtime-controller@sha256:f57b928684c48597de98a5f374d3464195b04c8c75dd9eaf3f385cea76cd44c2`.
The approved streaming POST returned 200; the broker refused the second host
with 403. [Cluster validation record](../tests/acceptance/custom-inference-container-2026-11-05.json)
