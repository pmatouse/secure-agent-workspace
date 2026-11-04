#!/usr/bin/env bash
# Use the stock CLI with the ordinary owner's existing OIDC gateway login.
set -euo pipefail
if [[ $# != 5 ]]; then
  echo 'usage: check-toolbox.sh GATEWAY WORKSPACE SANDBOX write|read|deny-api|nonmember VALUE' >&2
  exit 2
fi
gateway=$1 workspace=$2 sandbox=$3 action=$4 value=$5
scope=(-g "$gateway" --workspace "$workspace")
exec_args=(--name "$sandbox" --no-tty --no-login-shell --timeout 15 --)
case "$action" in
  write|read)
    [[ "$value" =~ ^[a-f0-9]{32}$ ]] || { echo 'use a fresh 32-character hexadecimal test nonce' >&2; exit 2; }
    openshell sandbox exec "${scope[@]}" "${exec_args[@]}" python3 -c '
from pathlib import Path
import sys
action, nonce = sys.argv[1:]
path = Path("/sandbox/workspace") / (".saw-test-" + nonce)
if action == "write":
    with path.open("x") as f:
        f.write(nonce)
else:
    if path.read_text() != nonce:
        raise SystemExit("persistence mismatch")
    path.unlink()
print("PVC_" + action.upper() + "_OK")
' "$action" "$value"
    ;;
  deny-api)
    openshell sandbox exec "${scope[@]}" "${exec_args[@]}" python3 -c '
import ipaddress, socket, sys
host = str(ipaddress.ip_address(sys.argv[1]))
try:
    conn = socket.create_connection((host, 443), timeout=3)
except (TimeoutError, PermissionError):
    print("DIRECT_API_BLOCKED")
else:
    conn.close()
    raise SystemExit("unexpected direct TCP connection to the API")
' "$value"
    ;;
  nonmember)
    if membership=$(openshell workspace get -g "$gateway" "$workspace" 2>&1); then
      echo 'unexpected workspace membership' >&2
      exit 1
    fi
    case "$membership" in
      *"not a member"*|*"PermissionDenied"*|*"permission denied"*) ;;
      *) echo 'expected an authenticated workspace authorization denial' >&2; exit 1 ;;
    esac
    if result=$(openshell sandbox get "${scope[@]}" "$sandbox" 2>&1); then
      echo 'unexpected nonmember access' >&2
      exit 1
    fi
    # Some gateways conceal sandbox existence after refusing workspace access.
    case "$result" in
      *"not a member"*|*"PermissionDenied"*|*"permission denied"*|*"not found"*) echo NONMEMBER_DENIED ;;
      *) echo 'expected an authenticated workspace authorization denial' >&2; exit 1 ;;
    esac
    ;;
  *) echo 'unknown test action' >&2; exit 2 ;;
esac
