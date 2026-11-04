"""Create-once gateway identity; only selected leaf keys leave the trusted namespace.

The stock gateway generates PKI into a memory-backed volume. This helper issues
an admin client, retains one atomic bundle, then resumes its fixed projections.
It never updates, rotates, adopts or deletes an existing Kubernetes Secret.
"""
import base64
import hashlib
import json
import os
from pathlib import Path
import secrets
import ssl
import subprocess
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, HTTPSHandler, HTTPRedirectHandler, build_opener
import uuid
import re

OWNER = "saw.redhat.com/runtime-owner"
HASH = "saw.redhat.com/identity-config-sha256"
KEEP = "Prune=false,Delete=false"
LIMIT = 1024 * 1024
NAME = re.compile(r"[a-z0-9](?:[-a-z0-9]*[a-z0-9])?\Z")


class Failure(Exception):
    pass


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def encode(raw):
    return base64.b64encode(raw).decode("ascii")


def decode(raw):
    try:
        value = base64.b64decode(raw, validate=True)
        if not value or len(value) > LIMIT:
            raise ValueError()
        return value
    except (ValueError, TypeError):
        raise Failure("invalid retained identity encoding") from None


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Api:
    def __init__(self):
        root = Path("/var/run/secrets/kubernetes.io/serviceaccount")
        self.token = root / "token"
        self.opener = build_opener(NoRedirect(), HTTPSHandler(
            context=ssl.create_default_context(cafile=str(root / "ca.crt"))))

    def request(self, method, path, body=None):
        token = self.token.read_text().strip()
        if not token or any(c.isspace() for c in token):
            raise Failure("invalid bootstrap service account token")
        request = Request("https://kubernetes.default.svc" + path,
                          data=canonical(body).encode() if body is not None else None,
                          headers={"Authorization": "Bearer " + token,
                                   "Content-Type": "application/json"}, method=method)
        try:
            with self.opener.open(request, timeout=20) as response:
                raw = response.read(LIMIT + 1)
            if len(raw) > LIMIT:
                raise Failure("oversized API response")
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise Failure("invalid API response")
            return value
        except HTTPError as exc:
            code = exc.code
            exc.close()
            if method == "GET" and code == 404:
                return None
            if method == "POST" and code == 409:
                return None  # caller observes the winner, never overwrites it
            raise Failure(f"bootstrap API failed ({code})") from None
        except (URLError, OSError, ValueError):
            raise Failure("bootstrap API unavailable") from None

    def namespace(self, name):
        return self.request("GET", f"/api/v1/namespaces/{name}")

    def get(self, namespace, name):
        return self.request("GET", f"/api/v1/namespaces/{namespace}/secrets/{name}")

    def create(self, namespace, secret):
        self.request("POST", f"/api/v1/namespaces/{namespace}/secrets", secret)


def validate(config):
    if set(config) != {"ownerID", "namespace", "targetNamespace", "gateway", "serverSans", "adminDays"}:
        raise Failure("invalid bootstrap configuration fields")
    for key in ("namespace", "targetNamespace", "gateway"):
        value = config[key]
        if (not isinstance(value, str) or not NAME.fullmatch(value) or len(value) > 50
                or value == "default" or value.startswith(("openshift", "kube-"))):
            raise Failure("invalid bootstrap resource name")
    if config["namespace"] == config["targetNamespace"]:
        raise Failure("admin identity requires a separate trusted namespace")
    try:
        owner = uuid.UUID(config["ownerID"])
        if str(owner) != config["ownerID"] or owner.int == 0:
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise Failure("invalid installation identity") from None
    names = config["serverSans"]
    if (not isinstance(names, list) or not names or len(names) > 12
            or any(not isinstance(n, str) or len(n) > 253
                   or not all(NAME.fullmatch(p) for p in n.split(".")) for n in names)
            or len(set(names)) != len(names)):
        raise Failure("server SANs must be unique DNS names")
    expected = config["gateway"] + "-gateway." + config["targetNamespace"] + ".svc"
    if expected not in names or expected + ".cluster.local" not in names:
        raise Failure("gateway Service DNS SANs are required")
    if type(config["adminDays"]) is not int or not 1 <= config["adminDays"] <= 90:
        raise Failure("admin certificate lifetime must be 1..90 days")


def openssl(*args):
    try:
        result = subprocess.run(["openssl", *map(str, args)], capture_output=True,
                                timeout=20, check=False)
        if result.returncode:
            raise Failure("identity cryptographic validation failed")
        return result.stdout
    except (OSError, subprocess.SubprocessError):
        raise Failure("identity cryptographic tool unavailable") from None


def generate(config, directory):
    """Consume stock generate-certs output; CA key never enters a Secret."""
    directory = Path(directory)
    sources = {"ca": "ca.crt", "serverCert": "server/tls.crt", "serverKey": "server/tls.key",
               "signing": "jwt/signing.pem", "public": "jwt/public.pem", "kid": "jwt/kid"}
    data = {}
    for key, filename in sources.items():
        path = directory / filename
        if path.is_symlink() or not path.is_file():
            raise Failure("stock gateway generated incomplete identity")
        data[key] = encode(path.read_bytes())
    ca = directory / "ca.crt"
    cert = directory / "server/tls.crt"
    for name in config["serverSans"]:
        openssl("verify", "-CAfile", ca, "-verify_hostname", name, cert)
    admin = directory / "admin"
    admin.mkdir(mode=0o700, exist_ok=True)
    key, csr, client = [admin / n for n in ("tls.key", "request.csr", "tls.crt")]
    openssl("req", "-new", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1",
            "-nodes", "-keyout", key, "-out", csr,
            "-subj", "/O=openshell/OU=openshell-admin/CN=saw-reconciler")
    extensions = admin / "extensions"
    extensions.write_text("basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature\n"
                          "extendedKeyUsage=clientAuth\n")
    openssl("x509", "-req", "-in", csr, "-CA", ca, "-CAkey", directory / "ca.key",
            "-set_serial", "0x" + secrets.token_hex(16), "-days", config["adminDays"],
            "-extfile", extensions, "-out", client)
    openssl("verify", "-CAfile", ca, "-purpose", "sslclient", client)
    data.update(adminCert=encode(client.read_bytes()), adminKey=encode(key.read_bytes()),
                kek=encode(base64.b64encode(secrets.token_bytes(32))))
    return data


def projections(config, data):
    required = {"ca", "serverCert", "serverKey", "signing", "public", "kid", "adminCert", "adminKey", "kek"}
    if set(data) != required:
        raise Failure("retained identity bundle is incomplete")
    for value in data.values():
        decode(value)
    if len(decode(decode(data["kek"]))) != 32:
        raise Failure("invalid retained credential encryption key")
    ns, target, gateway = config["namespace"], config["targetNamespace"], config["gateway"]
    return [
        (target, gateway + "-server", "kubernetes.io/tls",
         {"ca.crt": data["ca"], "tls.crt": data["serverCert"], "tls.key": data["serverKey"]}),
        (target, gateway + "-client-ca", "Opaque", {"ca.crt": data["ca"]}),
        (target, gateway + "-jwt", "Opaque",
         {"signing.pem": data["signing"], "public.pem": data["public"], "kid": data["kid"]}),
        (target, gateway + "-kek", "Opaque", {"key-encryption-key": data["kek"]}),
        (ns, gateway + "-admin", "kubernetes.io/tls",
         {"ca.crt": data["ca"], "tls.crt": data["adminCert"], "tls.key": data["adminKey"]}),
    ]


def secret(config, revision, namespace, name, kind, data):
    return {"apiVersion": "v1", "kind": "Secret", "type": kind, "immutable": True,
            "metadata": {"name": name, "namespace": namespace, "labels": {OWNER: config["ownerID"]},
                         "annotations": {HASH: revision, "argocd.argoproj.io/sync-options": KEEP}},
            "data": data}


def check(actual, expected):
    if not actual:
        raise Failure("identity Secret missing after create")
    meta, wanted = actual.get("metadata", {}), expected["metadata"]
    if (meta.get("deletionTimestamp") or meta.get("ownerReferences")
            or any(meta.get(k) != wanted[k] for k in ("name", "namespace"))
            or meta.get("labels", {}).get(OWNER) != wanted["labels"][OWNER]
            or any(meta.get("annotations", {}).get(k) != v for k, v in wanted["annotations"].items())
            or actual.get("immutable") is not True or actual.get("type") != expected["type"]
            or actual.get("data") != expected["data"]):
        raise Failure("existing identity is foreign, changed or deleting; no automatic adoption or rotation")


def run(api, config, generator):
    validate(config)
    identities = {}
    for ns in (config["namespace"], config["targetNamespace"]):
        meta = (api.namespace(ns) or {}).get("metadata", {})
        if (not meta.get("uid") or meta.get("deletionTimestamp")
                or meta.get("labels", {}).get(OWNER) != config["ownerID"]):
            raise Failure("bootstrap namespace missing, deleting or owned by another installation")
        identities[ns] = meta["uid"]
    revision = hashlib.sha256(canonical({"config": config, "namespaces": identities}).encode()).hexdigest()
    ns, gateway = config["namespace"], config["gateway"]
    retained = api.get(ns, gateway + "-identity")
    if retained is None:
        names = [(config["targetNamespace"], gateway + suffix)
                 for suffix in ("-server", "-client-ca", "-jwt", "-kek")]
        names.append((ns, gateway + "-admin"))
        if any(api.get(n, name) is not None for n, name in names):
            raise Failure("orphaned identity projections; restore retained bundle, do not regenerate")
        data = generator()
        projections(config, data)  # reject invalid material before first side effect
        api.create(ns, secret(config, revision, ns, gateway + "-identity", "Opaque", data))
        retained = api.get(ns, gateway + "-identity")
    # A concurrent creator wins atomically. All projections use its bundle.
    data = (retained or {}).get("data", {})
    check(retained, secret(config, revision, ns, gateway + "-identity", "Opaque", data))
    for namespace, name, kind, values in projections(config, data):
        expected = secret(config, revision, namespace, name, kind, values)
        existing = api.get(namespace, name)
        if existing is None:
            api.create(namespace, expected)
            existing = api.get(namespace, name)
        check(existing, expected)


def main():
    os.umask(0o077)
    try:
        config = json.loads(Path("/config/config.json").read_text())
        run(Api(), config, lambda: generate(config, "/generated/pki"))
        print("Gateway identity retained and projections verified; no keys rotated.")
        return 0
    except Failure as exc:
        print("Identity bootstrap failed: " + str(exc), file=sys.stderr)
        return 1
    except (OSError, ValueError):
        # Never emit API bodies, subprocess stderr, PEMs or credential-bearing data.
        print("Identity bootstrap failed; inspect configuration, ownership and retained state.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
