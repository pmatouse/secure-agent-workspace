"""OpenShell CLI gateway config adapter for v0.0.116.

Writes a temporary gateway configuration that the openshell CLI can use
to connect to a SAW session gateway with OIDC authentication.
"""

import json
import os
import secrets
import shutil
import tempfile
from pathlib import Path


class GatewayConfig:
    """Manages a temporary openshell gateway configuration."""

    def __init__(self, session_name: str, descriptor: dict, access_token: str):
        self.session_name = session_name
        self.alias = f"saw-{session_name}"
        self._tmpdir = Path(tempfile.mkdtemp(
            prefix=f"codex-saw-{session_name}-{secrets.token_hex(4)}-",
        ))
        os.chmod(self._tmpdir, 0o700)

        gw_dir = self._tmpdir / "openshell" / "gateways" / self.alias
        gw_dir.mkdir(parents=True)

        # metadata.json — v0.0.116 schema
        (gw_dir / "metadata.json").write_text(json.dumps({
            "name": self.alias,
            "gateway_endpoint": descriptor["gateway_endpoint"],
            "is_remote": False,
            "gateway_port": 443,
            "auth_mode": "oidc",
            "oidc_issuer": descriptor["oidc_issuer"],
            "oidc_client_id": descriptor["oidc_client_id"],
            "oidc_audience": descriptor["oidc_client_id"],
        }))

        # oidc_token.json — access token snapshot (no refresh_token)
        (gw_dir / "oidc_token.json").write_text(json.dumps({
            "access_token": access_token,
            "issuer": descriptor["oidc_issuer"],
            "client_id": descriptor["oidc_client_id"],
        }))

        # mtls/ca.crt — gateway CA for HTTPS verification
        ca_pem = descriptor.get("gateway_ca_pem")
        if ca_pem:
            mtls_dir = gw_dir / "mtls"
            mtls_dir.mkdir()
            (mtls_dir / "ca.crt").write_text(ca_pem)

    @property
    def env(self) -> dict[str, str]:
        """Environment variables to pass to openshell subprocess."""
        return {"XDG_CONFIG_HOME": str(self._tmpdir)}

    @property
    def gateway_name(self) -> str:
        return self.alias

    def cleanup(self):
        """Remove temporary configuration."""
        if self._tmpdir.exists():
            shutil.rmtree(self._tmpdir, ignore_errors=True)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.cleanup()
