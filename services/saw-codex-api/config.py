"""Configuration from environment variables."""

import os


OIDC_ISSUER_URL = os.environ.get(
    "OIDC_ISSUER_URL",
    "https://keycloak.openshell-agents.svc/realms/openshell",
)
OIDC_CLIENT_ID = os.environ.get("OIDC_CLIENT_ID", "openshell-cli")
MANAGED_NAMESPACE = os.environ.get("MANAGED_NAMESPACE", "openshell-agents")
SAW_CHART_PATH = os.environ.get("SAW_CHART_PATH", "/app/charts/openshell-saw/")
K8S_CHART_PATH = os.environ.get("K8S_CHART_PATH", "/app/charts/openshell-saw-kubernetes/")
DEFAULT_BACKEND = os.environ.get("DEFAULT_BACKEND", "kubernetes")
OIDC_JWKS_CACHE_TTL = int(os.environ.get("OIDC_JWKS_CACHE_TTL", "3600"))
_ca_bundle = os.environ.get("TLS_CA_BUNDLE", "")
TLS_VERIFY: bool | str = _ca_bundle if _ca_bundle else True

# Keycloak admin API (for per-session runtime client lifecycle)
KEYCLOAK_ADMIN_URL = os.environ.get("KEYCLOAK_ADMIN_URL", OIDC_ISSUER_URL.rsplit("/realms/", 1)[0])
KEYCLOAK_REALM = os.environ.get("KEYCLOAK_REALM", "openshell")
KEYCLOAK_ADMIN_CLIENT_ID = os.environ.get("KEYCLOAK_ADMIN_CLIENT_ID", "saw-keycloak-admin")
KEYCLOAK_ADMIN_CLIENT_SECRET = os.environ.get("KEYCLOAK_ADMIN_CLIENT_SECRET", "")
PROVISIONER_CLIENT_ID = os.environ.get("PROVISIONER_CLIENT_ID", "saw-provisioner")
PROVISIONER_CLIENT_SECRET = os.environ.get("PROVISIONER_CLIENT_SECRET", "")
RUNTIME_CLIENT_TOKEN_LIFETIME = int(os.environ.get("RUNTIME_CLIENT_TOKEN_LIFETIME", "28800"))
SESSION_TOKEN_TTL = int(os.environ.get("SESSION_TOKEN_TTL", "300"))
MAX_SESSIONS_PER_USER = int(os.environ.get("MAX_SESSIONS_PER_USER", "3"))
