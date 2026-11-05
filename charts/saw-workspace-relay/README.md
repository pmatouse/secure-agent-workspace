# OpenShell workspace UI relay

One relay serves one OpenClaw workspace and sandbox. The user's browser signs in
to the existing Keycloak dashboard client. A separate confidential client
authenticates the stock OpenShell CLI to the gateway. OpenShell's
`WORKSPACE_ROLE_USER` includes normal workspace-user operations, including
sandbox exec. Treat the relay credential as a workspace-user credential.

```text
RHDH owner catalog link → HTTPS Route → oauth2-proxy (preferred_username allowlist)
                                      → loopback stock OpenShell CLI forward
                                        → gateway (relay OIDC subject + workspace membership)
                                          → supervisor → OpenClaw loopback :18789
```

## Install

1. Create a dedicated restricted namespace with default-deny networking. Label
   it for the SAW redirect registrar. Supply the site issuer, public gateway CA,
   endpoint, unique client ID, installation ID, gateway namespace, build namespace,
   pinned images, target workspace ID, owner login/subject and sandbox name.
   Allow cluster DNS and HTTPS to the issuer. The UI Route needs a cluster apps
   hostname and the standard ingress TLS certificate.
2. Install this chart through Argo with `enabled: true` and empty `subject`.
   Configure Argo to ignore `/data` on **only** the precreated
   `relay-credentials` Secret in the UI namespace and respect differences during
   sync. The Keycloak-namespace Job uses the standard bootstrap credential. It
   creates a client-credentials-only client with restricted scope, grants
   `openshell-user`, verifies the issued token and reports the public subject UUID.
3. Commit that UUID as `subject`. The one-time membership Job runs in the
   trusted namespace. It verifies the workspace UUID, installation label and
   owner's admin membership before granting the relay `WORKSPACE_ROLE_USER`.
   The relay Deployment receives the client secret and a memory-backed token
   cache. Only the binding Job mounts gateway admin credentials. The gateway's
   client CA and the VM baseline remain independently managed.
4. On the administrator's approved OpenClaw sandbox binding, set
   `browser.origin` to the exact HTTPS UI origin and `browser.ownerLogin`
   to the same owner as this chart. Generate the intent using `--pin-plan`.
   Apply browser settings at agent launch. A hot change to gateway
   authentication can exit the canonical process. OpenClaw trusts loopback and
   the proxy-overwritten email header, checks the owner, and auto-approves
   read/write scopes for the authenticated owner's device.
5. Add the site-owned catalog link via `portal.linkedWorkspaces`. Set
   `routeLabel`, `title` and `owner`. RHDH applies entity-owner permissions.
   This registers an existing deployment. Portal lifecycle forms have their
   own backend qualification gates.

## Verify and operate

Use `openshell workspace list -g relay -o json` in the forward container.
Expect precisely the selected workspace ID. Attempt `workspace get` for a
known second workspace and expect a membership denial. Sign in as the owner
and send a new chat prompt through the Route. Repeat sign-in as a second user
and expect HTTP 403. For the catalog, the owner should retrieve the linked
Component and the second user should receive 403 or 404.

The token refresher verifies issuer, client, subject, audience and roles at
each exchange, then replaces the CLI token atomically. The CLI forward restarts
on exit and reacquires the current token; clients may reconnect during renewal.
The browser allowlist and launch-time allowUsers must match. The Route replaces
forwarded headers, and only the ingress namespace can reach the login proxy.
The relay and workload never need an OpenAI API key for browser authentication.

To revoke access, disable the dedicated client, remove that exact workspace
membership, withdraw the Route and catalog link, and retire the retained Secret
under the site's credential-retention policy. Removing a Git manifest alone
does not revoke an issued token or delete an external Keycloak client. A
recreated client has a new subject and requires a reviewed membership change.
