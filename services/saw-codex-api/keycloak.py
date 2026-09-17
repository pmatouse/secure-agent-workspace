"""Keycloak admin helper for per-session runtime client lifecycle."""

import logging
import time

import httpx

from . import config

logger = logging.getLogger(__name__)


def _admin_token() -> str:
    """Get a token for the Keycloak admin client (realm-management)."""
    url = f"{config.KEYCLOAK_ADMIN_URL}/realms/{config.KEYCLOAK_REALM}/protocol/openid-connect/token"
    resp = httpx.post(
        url,
        data={
            "grant_type": "client_credentials",
            "client_id": config.KEYCLOAK_ADMIN_CLIENT_ID,
            "client_secret": config.KEYCLOAK_ADMIN_CLIENT_SECRET,
        },
        verify=config.TLS_VERIFY,
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def get_provisioner_token() -> tuple[str, int]:
    """Get a token for the provisioner client (OpenShell platform-admin).

    Returns (access_token, expires_at_epoch).
    """
    url = f"{config.KEYCLOAK_ADMIN_URL}/realms/{config.KEYCLOAK_REALM}/protocol/openid-connect/token"
    resp = httpx.post(
        url,
        data={
            "grant_type": "client_credentials",
            "client_id": config.PROVISIONER_CLIENT_ID,
            "client_secret": config.PROVISIONER_CLIENT_SECRET,
        },
        verify=config.TLS_VERIFY,
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    expires_at = int(time.time()) + data.get("expires_in", 300)
    return data["access_token"], expires_at


def create_session_client(
    session_uid: str,
    token_lifetime: int | None = None,
) -> tuple[str, str]:
    """Create a per-session runtime client in Keycloak.

    Returns (client_id, client_secret).
    """
    admin_token = _admin_token()
    client_id = f"saw-rt-{session_uid[:8]}"
    if token_lifetime is None:
        token_lifetime = config.RUNTIME_CLIENT_TOKEN_LIFETIME

    base = f"{config.KEYCLOAK_ADMIN_URL}/admin/realms/{config.KEYCLOAK_REALM}"
    headers = {"Authorization": f"Bearer {admin_token}"}

    # Check if client already exists
    resp = httpx.get(
        f"{base}/clients",
        params={"clientId": client_id},
        headers=headers,
        verify=config.TLS_VERIFY,
        timeout=10,
    )
    resp.raise_for_status()
    existing = resp.json()

    if existing:
        kc_id = existing[0]["id"]
        logger.info("Runtime client %s already exists (kc_id=%s)", client_id, kc_id)
        # Retrieve secret
        resp = httpx.get(
            f"{base}/clients/{kc_id}/client-secret",
            headers=headers,
            verify=config.TLS_VERIFY,
            timeout=10,
        )
        resp.raise_for_status()
        return client_id, resp.json()["value"]

    # Create the client
    client_repr = {
        "clientId": client_id,
        "name": f"SAW Runtime {session_uid[:8]}",
        "enabled": True,
        "publicClient": False,
        "clientAuthenticatorType": "client-secret",
        "standardFlowEnabled": False,
        "directAccessGrantsEnabled": False,
        "serviceAccountsEnabled": True,
        "attributes": {
            "access.token.lifespan": str(token_lifetime),
        },
        "protocolMappers": [
            {
                "name": "realm-roles",
                "protocol": "openid-connect",
                "protocolMapper": "oidc-usermodel-realm-role-mapper",
                "config": {
                    "multivalued": "true",
                    "claim.name": "realm_access.roles",
                    "jsonType.label": "String",
                    "id.token.claim": "false",
                    "access.token.claim": "true",
                },
            },
            {
                "name": "audience",
                "protocol": "openid-connect",
                "protocolMapper": "oidc-audience-mapper",
                "config": {
                    "included.client.audience": config.OIDC_CLIENT_ID,
                    "id.token.claim": "false",
                    "access.token.claim": "true",
                },
            },
        ],
    }

    resp = httpx.post(
        f"{base}/clients",
        json=client_repr,
        headers=headers,
        verify=config.TLS_VERIFY,
        timeout=10,
    )
    if resp.status_code == 409:
        logger.info("Runtime client %s created concurrently, retrieving", client_id)
        return create_session_client(session_uid, token_lifetime)
    resp.raise_for_status()

    # Get the auto-generated Keycloak internal ID from the Location header
    location = resp.headers.get("Location", "")
    kc_id = location.rstrip("/").rsplit("/", 1)[-1]

    # Assign openshell-user role to the service account
    _assign_role_to_service_account(base, headers, kc_id, "openshell-user")

    # Retrieve the generated secret
    resp = httpx.get(
        f"{base}/clients/{kc_id}/client-secret",
        headers=headers,
        verify=config.TLS_VERIFY,
        timeout=10,
    )
    resp.raise_for_status()
    client_secret = resp.json()["value"]

    logger.info("Created runtime client %s (kc_id=%s)", client_id, kc_id)
    return client_id, client_secret


def delete_session_client(session_uid: str) -> None:
    """Delete a per-session runtime client from Keycloak."""
    admin_token = _admin_token()
    client_id = f"saw-rt-{session_uid[:8]}"
    base = f"{config.KEYCLOAK_ADMIN_URL}/admin/realms/{config.KEYCLOAK_REALM}"
    headers = {"Authorization": f"Bearer {admin_token}"}

    resp = httpx.get(
        f"{base}/clients",
        params={"clientId": client_id},
        headers=headers,
        verify=config.TLS_VERIFY,
        timeout=10,
    )
    resp.raise_for_status()
    clients = resp.json()

    if not clients:
        logger.info("Runtime client %s not found, nothing to delete", client_id)
        return

    kc_id = clients[0]["id"]
    resp = httpx.delete(
        f"{base}/clients/{kc_id}",
        headers=headers,
        verify=config.TLS_VERIFY,
        timeout=10,
    )
    if resp.status_code == 404:
        return
    resp.raise_for_status()
    logger.info("Deleted runtime client %s", client_id)


def get_service_account_subject(client_id: str) -> str | None:
    """Get the service account user ID (sub) for a client."""
    admin_token = _admin_token()
    base = f"{config.KEYCLOAK_ADMIN_URL}/admin/realms/{config.KEYCLOAK_REALM}"
    headers = {"Authorization": f"Bearer {admin_token}"}

    resp = httpx.get(
        f"{base}/clients",
        params={"clientId": client_id},
        headers=headers,
        verify=config.TLS_VERIFY,
        timeout=10,
    )
    resp.raise_for_status()
    clients = resp.json()
    if not clients:
        return None

    kc_id = clients[0]["id"]
    resp = httpx.get(
        f"{base}/clients/{kc_id}/service-account-user",
        headers=headers,
        verify=config.TLS_VERIFY,
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json().get("id")


def _assign_role_to_service_account(
    base: str, headers: dict, client_kc_id: str, role_name: str
) -> None:
    """Assign a realm role to a client's service account user."""
    # Get the service account user
    resp = httpx.get(
        f"{base}/clients/{client_kc_id}/service-account-user",
        headers=headers,
        verify=config.TLS_VERIFY,
        timeout=10,
    )
    resp.raise_for_status()
    sa_user_id = resp.json()["id"]

    # Get the role representation
    resp = httpx.get(
        f"{base}/roles/{role_name}",
        headers=headers,
        verify=config.TLS_VERIFY,
        timeout=10,
    )
    resp.raise_for_status()
    role_repr = resp.json()

    # Assign the role
    resp = httpx.post(
        f"{base}/users/{sa_user_id}/role-mappings/realm",
        json=[role_repr],
        headers=headers,
        verify=config.TLS_VERIFY,
        timeout=10,
    )
    if resp.status_code not in (200, 204, 409):
        resp.raise_for_status()
