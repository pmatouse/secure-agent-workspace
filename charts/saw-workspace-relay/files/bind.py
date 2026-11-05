"""Grant the relay the stock workspace user role after checking the live owner and IDs."""
import json
import os
import uuid
from saw_kubernetes.adapters import GrpcGateway


def main():
    ws, wid = os.environ["WORKSPACE"], os.environ["WORKSPACE_ID"]
    relay, owner = os.environ["SUBJECT"], os.environ["OWNER"]
    if (any(uuid.UUID(v).int == 0 for v in (wid, relay, owner, os.environ["INSTALLATION"]))
            or relay == owner or ws == "default"):
        raise ValueError("invalid relay scope")
    g = GrpcGateway(os.environ["ENDPOINT"], "/identity/ca.crt", "/identity/tls.crt", "/identity/tls.key")
    try:
        meta = g.call("GetWorkspace", {"name":ws})["workspace"]["metadata"]
        if (meta["id"] != wid or meta["name"] != ws or meta.get("deletion_time") or
                meta["labels"].get("saw.redhat.com/runtime-owner") != os.environ["INSTALLATION"]):
            raise ValueError("workspace identity mismatch")
        scope = {"workspace_scope":{"workspace":ws}}
        def members():
            result, page = {}, ""
            while True:
                response = g.call("ListWorkspaceMembers", {**scope, "page_size":100, "page_token":page})
                for m in response.get("members", []):
                    result[m["principal_subject"]] = m["role"]
                page = response.get("next_page_token")
                if not page:
                    return result
        roles = members()
        if roles.get(owner) != "WORKSPACE_ROLE_ADMIN":
            raise ValueError("owner mismatch")
        if relay not in roles:
            g.call("AddWorkspaceMember", {**scope,"principal_subject":relay, "role":"WORKSPACE_ROLE_USER",
                "request_id":str(uuid.uuid5(uuid.UUID(wid), "relay-user/" + relay))})
        if members().get(relay) != "WORKSPACE_ROLE_USER":
            raise ValueError("unexpected relay role")
        print(json.dumps({"workspace":ws, "workspaceID":wid, "subject":relay,"role":"WORKSPACE_ROLE_USER"}))
    finally:
        g.close()


if __name__ == "__main__":
    main()
