#!/usr/bin/env python3
"""Exercise the installed RHDH scaffolder as the owner. Secrets stay in process."""
import argparse
import http.cookiejar
import json
from pathlib import Path
import re
import subprocess
import sys
import time
import urllib.parse as u
import urllib.request as r
from html.parser import HTMLParser


class LoginForm(HTMLParser):
    action = None

    def handle_starttag(self, tag, attrs):
        fields = dict(attrs)
        if tag == "form" and fields.get("id") == "kc-form-login":
            self.action = fields.get("action")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=("inspect", "create", "update", "delete", "status", "start", "stop", "workspace-status", "logs"))
    p.add_argument("--origin", required=True)
    p.add_argument("--issuer", required=True)
    p.add_argument("--user", required=True)
    p.add_argument("--profile",default="audited-openclaw")
    p.add_argument("--model",action="append",default=[],metavar="FIELD=MODEL")
    p.add_argument("--key-file", type=Path)
    p.add_argument("--task")
    p.add_argument("--run")
    p.add_argument("--wait", type=int, default=0, help="poll a status task with the same authenticated session")
    a = p.parse_args()
    root, issuer = a.origin.rstrip("/"), a.issuer.rstrip("/")
    if not re.fullmatch(r"https://[a-z0-9.-]+", root) or not re.fullmatch(r"https://[a-z0-9.-]+/realms/[A-Za-z0-9._-]+", issuer):
        p.error("explicit HTTPS portal and Keycloak realm required")
    if a.action == "status" and not re.fullmatch(r"[0-9a-f-]{36}", a.task or ""):
        p.error("explicit task UUID required")
    class Redirect(r.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            origin = u.urlsplit(newurl)
            if origin.scheme != "https" or origin.netloc not in {u.urlsplit(root).netloc, u.urlsplit(issuer).netloc} or (req.data and code not in (302,303)):
                raise RuntimeError("unexpected identity redirect")
            return super().redirect_request(req, fp, code, msg, headers, newurl)
    opener = r.build_opener(r.HTTPCookieProcessor(http.cookiejar.CookieJar()), Redirect())
    def get(req):
        with opener.open(req, timeout=25) as res:
            return res.url, res.read(1024*1024).decode()
    url, page = get(root + "/api/auth/oidc/start?" + u.urlencode(dict(env="production", origin=root, flow="popup", scope="openid profile email")))
    form = LoginForm()
    form.feed(page)
    action = u.urljoin(url, form.action or "")
    if not form.action or not action.startswith(issuer + "/login-actions/"):
        raise RuntimeError("expected the configured realm's login form")
    password = sys.stdin.readline().rstrip("\r\n")
    if not password:
        raise ValueError("owner password required on stdin")
    url, _ = get(r.Request(action, data=u.urlencode(dict(username=a.user,password=password)).encode()))
    if not url.startswith(root + "/api/auth/oidc/handler/frame"):
        raise RuntimeError("RHDH owner login did not finish")
    _, body = get(r.Request(root + "/api/auth/oidc/refresh?env=production", headers={"X-Requested-With":"XMLHttpRequest", "Origin":root}))
    identity = json.loads(body)["backstageIdentity"]
    if identity["identity"]["userEntityRef"] != "user:default/" + a.user:
        raise RuntimeError("unexpected RHDH identity")
    token = identity["token"]
    def api(path, data=None):
        # A bearer token must never follow a redirect, including to Keycloak.
        class NoRedirect(r.HTTPRedirectHandler):
            def redirect_request(self,*args):
                raise RuntimeError("unexpected authenticated redirect")
        req = r.Request(root+path, data=json.dumps(data).encode() if data is not None else None,
                        headers={"Authorization":"Bearer "+token,"Content-Type":"application/json"})
        with r.build_opener(NoRedirect()).open(req, timeout=30) as res:
            return json.load(res)
    if a.action in ("start", "stop", "workspace-status", "logs"):
        cmd = "status" if a.action == "workspace-status" else a.action
        args = [sys.executable, "-m", "openshell_saw.cli", "workspace", "--url", root, "--token-file", "-", cmd]
        if cmd == "logs":
            if not a.run:
                p.error("--run is required")
            args.append(a.run)
        output = subprocess.check_output(args, input=token, text=True)
        print(json.dumps({"text": output}) if cmd == "logs" else output.strip())
        return
    if a.action == "status":
        deadline=time.monotonic()+min(max(a.wait,0),3600)
        while True:
            task=api("/api/scaffolder/v2/tasks/"+a.task)
            if task["status"] not in ("open","processing") or time.monotonic()>=deadline:break
            time.sleep(6)
        print(json.dumps({"task":a.task,"status":task["status"]})); return
    template = ("delete" if a.action == "delete" else "create") + "-saw-workspace"
    entity = api("/api/catalog/entities/by-name/template/default/"+template)
    if a.action == "inspect":
        fields = entity["spec"]["parameters"][-1]["properties"]
        print(json.dumps({"user":a.user,"template":template,"deploymentModes":fields.get("deploymentMode", {"enum":["vm"]})["enum"],"profiles":fields["profile"]["enum"]})); return
    data = {"templateRef":"template:default/"+template, "values":{},"secrets":{}}
    if a.action == "delete":
        data["values"].update(workspace="component:default/saw-"+a.user, confirm=True)
    else:
        props = entity["spec"]["parameters"][-1]["properties"]
        if "container" not in props.get("deploymentMode", {}).get("enum", []) or a.profile not in props["profile"]["enum"]:
            raise RuntimeError("installed owner template does not offer the requested container profile")
        # The browser places a redacted value in form data to satisfy JSON
        # Schema. Only the separate secrets map carries the credential.
        data["values"].update(profile=a.profile,deploymentMode="container",inference__api_key="********")
        for assignment in a.model:
            field,sep,value=assignment.partition("=")
            if not sep or not re.fullmatch(r"inference__[a-z_]*model",field) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}",value):
                p.error("expected an inference model field and model ID")
            data["values"][field]=value
        if not a.key_file:
            raise ValueError("private --key-file required")
        data["secrets"]["inference__api_key"] = a.key_file.read_text().strip()
    print(json.dumps({"action":a.action,"task":api("/api/scaffolder/v2/tasks",data)["id"]}))


if __name__ == "__main__":
    main()
