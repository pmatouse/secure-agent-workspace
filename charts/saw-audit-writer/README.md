# Restricted OpenClaw audit writer

The VM installer and the Kubernetes reconciler build the same OpenClaw
`before_tool_call` extension from `charts/openshell-saw/files/installer`.
Its decision engine maps the tool and arguments to a policy rule and records the
owner, task, tool, argument digest, rule and decision. The VM appends to its
host-sealed log. The Kubernetes binding pins a writer verification key into the
read-only bundle and uses signed acknowledgements.

```text
Owner → HTTPS / OpenClaw chat → model tool call → shared SAW gate
                                                    │ publish .req
                                     per-sandbox exchange PVC (RWX)
                                                    │
                                          restricted forwarder
                                                    │ OpenShift service TLS
                                                    ▼
                                   writer in trusted namespace → SQLite FULL commit
                                                    │               history PVC (RWO)
                               signed receipt ◀─────┘
                                      │
                             gate verifies UUID + exact record hash
                                      ├─ allow → dispatch
                                      ├─ deny → block
                                      └─ approval → stock owner approval dialog
                                                     └─ resolution → second audit record
```

Only the writer mounts the history PVC. It exposes a single HTTPS POST. Each
UUID identifies one byte string. A retry returns a signature for the original
record, and reuse with different bytes returns HTTP 409. SQLite commits before
the writer signs. The writer's Ed25519 key persists with the database. The
forwarder validates the service certificate and publishes the signed receipt to
the exchange. The workload needs its existing filesystem access only. All three
Pods use restricted security contexts. The writer and forwarder mount no
Kubernetes API token.

**Deployment.** Use one Helm release per sandbox. Set the trusted and runtime
namespaces, identity (username, OIDC subject, workspace, sandbox), installation
UUID, pinned Node 24 image, RWO block storage class for history and RWX storage
class for the exchange. The runtime namespace already needs restricted
admission and the trusted namespace must be outside the gateway's Pod/exec
permissions. Retain the history claim on release removal.

1. Sync the chart. Verify both Deployments are ready. Record only the
   `receipt-public-key=` startup line from the trusted writer.
2. Prepare the gate PVC with the pinned controller image, as the runtime
   namespace UID. Run `python3 -m saw_kubernetes.prepare_gate --owner USER
   --subject SUB --workspace WS --sandbox SB --receipt-key PUBLIC_KEY` with the
   gate claim mounted at `/volume`. This publishes the shared bundle under
   `bundle/`. The forwarder creates `log/` on its exchange PVC.
3. Set the admin sandbox binding below using observed claim UIDs, add the
   claims to controller RBAC and pin the resulting plan. The governance image
   must enforce the reserved mount pair. The controller rechecks ownership
   and attachment permission before submitting the stock driver request.

```yaml
toolGate:
  ownerLogin: alice
  receiptKey: <Ed25519 SPKI DER, base64>
  trusted: {claimName: saw-gate-demo, uid: <gate-uid>, readOnly: true}
  audit: {claimName: saw-audit-demo, uid: <exchange-uid>, readOnly: false}
```

The `audit` binding names the exchange, not the history claim. OpenClaw checks
the mounted bundle's complete hash and plugin load before serving. The tested
profile exposes read, write and exec to the engine; policy permits read, denies
unlisted writes and requests owner approval for consequential exec. The browser
device requests only `operator.read`, `operator.write` and `operator.approvals`.

**Failure behavior.** The gate waits up to five seconds for an authentic
receipt for an initial decision. Missing, invalid or late receipts block the
tool. A request already published may reach the writer later. Stock OpenClaw
treats `onResolution` as a notification: failure to log a subsequent owner
approval cannot revoke that approval. A submitted resolution can retry via the
exchange. Protect and monitor the writer, exchange capacity and PVCs. The
writer protects existing records from the workspace. An actor able to write
the sandbox's exchange can submit new records for that identity. Storage
administrators remain trusted.

**End-to-end test.** Seed two disposable files and an unpredictable read canary
in an isolated workspace using an authorized fixture setup. Use the ordinary
owner account on its registered HTTPS chat Route. The test client performs the
actual OIDC/WSS login and uses `chat.send` and `plugin.approval.resolve`.
Pass the password on stdin and the exact build ID advertised by the shipped UI.

```sh
python3 tests/acceptance/openclaw_audit_chat.py \
  --origin "$CHAT_ORIGIN" --issuer "$ISSUER" --user "$OWNER" --version "$UI_BUILD_ID" \
  --session "agent:main:$RUN-approval" --decision allow-once \
  --prompt "Call exec now with this exact command on my disposable fixture: rm $CANARY" \
  < "$OWNER_PASSWORD_FILE"
```

Repeat with a distinct file and `--decision deny`. Request a denied write and
an allowed read in separate sessions. Check file existence independently.
Fingerprint ordered `seq,id,body,received` rows before stopping the sandbox.
Observe compute removal, start it from the same desired spec and claims, and
assert the original fingerprint and a new decision from a fresh chat.
