#!/usr/bin/env python3
"""Exercise the real owner HTTPS/WSS chat route using a fresh login and OpenClaw device.

Read the owner's password on stdin. Only ordinary chat status and acceptance
results are printed. The TLS session, login cookies and device stay in one process.
"""
import argparse
import base64
import hashlib
from html.parser import HTMLParser
import http.cookiejar
import json
import os
from pathlib import Path
import secrets
import socket
import ssl
import struct
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit, urljoin, urlencode
import urllib.request
import uuid


class Form(HTMLParser):
    action = None
    def handle_starttag(self, tag, attrs):
        fields = dict(attrs)
        if tag == "form" and fields.get("id") == "kc-form-login":
            self.action = fields.get("action")


def owner_cookie(origin, issuer, user, password):
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    with opener.open(origin + "/oauth2/start?rd=%2F", timeout=20) as response:
        page = Form()
        page.feed(response.read().decode())
        action = urljoin(response.url, page.action or "")
    if not page.action or not action.startswith(issuer.rstrip("/") + "/login-actions/"):
        raise RuntimeError("unexpected Keycloak login action")
    # Disallow credential-preserving redirects on the password POST.
    class LoginRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            if req.data and code not in (302,303):
                raise RuntimeError("unexpected login redirect")
            if urlsplit(newurl).netloc not in (urlsplit(origin).netloc, urlsplit(issuer).netloc):
                raise RuntimeError("unexpected login destination")
            return super().redirect_request(req, fp, code, msg, headers, newurl)
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar), LoginRedirect())
    data = urlencode({"username":user,"password":password,"credentialId":""}).encode()
    with opener.open(action, data=data, timeout=20) as response:
        if urlsplit(response.url).netloc != urlsplit(origin).netloc:
            raise RuntimeError("owner login did not return to the chat route")
    request = urllib.request.Request(origin + "/")
    jar.add_cookie_header(request)
    cookie = request.get_header("Cookie")
    if not cookie: raise RuntimeError("no owner session for this route")
    return cookie


def b64url(data):
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


class Chat:
    def __init__(self, origin, cookie, version):
        self.events = []
        host = urlsplit(origin).hostname
        self.sock = ssl.create_default_context().wrap_socket(socket.create_connection((host,443),timeout=20),
                                                             server_hostname=host)
        self.file = self.sock.makefile("rb")
        key = base64.b64encode(secrets.token_bytes(16)).decode()
        self.sock.sendall((f"GET / HTTP/1.1\r\nHost: {host}\r\nOrigin: {origin}\r\nCookie: {cookie}\r\n"
                           f"Upgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Version: 13\r\n"
                           f"Sec-WebSocket-Key: {key}\r\n\r\n").encode())
        status = self.file.readline()
        if not status.startswith(b"HTTP/1.1 101 "): raise RuntimeError("WebSocket upgrade failed")
        headers = {}
        for line in iter(self.file.readline,b"\r\n"):
            if not line: raise EOFError()
            field,value=line.decode().split(":",1)
            headers[field.lower()]=value.strip()
        expected=base64.b64encode(hashlib.sha1((key+"258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()).decode()
        if headers.get("sec-websocket-accept") != expected: raise RuntimeError("invalid WebSocket accept")
        challenge = self.read()
        assert challenge["event"]=="connect.challenge"
        nonce=challenge["payload"]["nonce"]
        scopes=["operator.read","operator.write","operator.approvals"]
        client_id="openclaw-control-ui"
        with tempfile.TemporaryDirectory() as td:
            private=Path(td)/"device"; msg=Path(td)/"challenge"
            def openssl(*args):
                return subprocess.run(["openssl",*map(str,args)],check=True,capture_output=True).stdout
            openssl("genpkey","-algorithm","ED25519","-out", private)
            pub=openssl("pkey","-in",private,"-pubout","-outform","DER")[-32:]
            device=hashlib.sha256(pub).hexdigest()
            now=int(time.time()*1000)
            msg.write_text("|".join(["v2",device,client_id,"webchat","operator",",".join(scopes),str(now),"",nonce]))
            sig=b64url(openssl("pkeyutl","-sign","-rawin","-inkey",private,"-in",msg))
            hello=self.call("connect",{"minProtocol":4,"maxProtocol":4,
                "client":{"id":client_id,"version":version.split("-")[0],"buildId":version,"platform":"Linux","mode":"webchat"},
                "role":"operator","scopes":scopes,"caps":["tool-events"],"device":{
                "id":device,"publicKey":b64url(pub),"signature":sig,"signedAt":now,"nonce":nonce}})
        if not set(scopes)<=set(hello.get("auth",{}).get("scopes",[])): raise RuntimeError("missing owner scopes")

    def frame(self, body, op=1):
        mask=os.urandom(4); n=len(body)
        header=bytes([128|op,128|n]) if n<126 else bytes([128|op,254])+struct.pack("!H",n)
        self.sock.sendall(header+mask+bytes(b^mask[i%4] for i,b in enumerate(body)))

    def read(self):
        parts=bytearray()
        while True:
            head=self.file.read(2)
            if len(head)!=2: raise EOFError("chat disconnected")
            op=head[0]&15; n=head[1]&127
            if n==126:n=struct.unpack("!H",self.file.read(2))[0]
            if n==127:n=struct.unpack("!Q",self.file.read(8))[0]
            if n+len(parts)>4_000_000:raise ValueError("oversized frame")
            body=self.file.read(n)
            if op==8:raise EOFError("gateway closed chat")
            if op==9:self.frame(body,10);continue
            if op==10:continue
            if op not in (0,1):raise ValueError("unexpected opcode")
            parts.extend(body)
            if head[0]&128:return json.loads(parts)

    def call(self, method, params):
        ident=str(uuid.uuid4())
        self.frame(json.dumps({"type":"req","id":ident,"method":method,"params":params}).encode())
        while True:
            event=self.read()
            if event.get("id")==ident:
                if not event["ok"]:
                    raise RuntimeError(method+": "+str(event.get("error",{}).get("message","denied"))[:220])
                return event.get("payload",{})
            self.events.append(event)

    def turn(self, session, message, decision=None, confirm_fixture=False):
        run=str(uuid.uuid4()); self.events.clear()
        self.call("chat.send",{"sessionKey":session,"message":message,"idempotencyKey":run})
        deadline=time.monotonic()+185; resolved=False
        while time.monotonic()<deadline:
            event=self.events.pop(0) if self.events else self.read()
            kind=event.get("event"); payload=event.get("payload") or {}
            if kind=="plugin.approval.requested" and decision:
                request=payload.get("request",{})
                if request.get("sessionKey")!=session or request.get("pluginId")!="saw-tool-gate":
                    continue
                self.call("plugin.approval.resolve",{"id":payload["id"],"decision":decision})
                resolved=True
            if kind=="chat" and payload.get("runId")==run and payload.get("state") in ("final","error","aborted"):
                text=" ".join(c.get("text","") for c in (payload.get("message") or {}).get("content",[]) if isinstance(c,dict))
                if (confirm_fixture and decision and not resolved and payload["state"]=="final" and
                        any(question in text.lower() for question in ("confirm","are you sure","do you want me to"))):
                    # A model asking a question is not the gate. Answer once, then
                    # still require the real plugin event and owner resolution.
                    return self.turn(session,"Yes, I confirm the disposable fixture operation from my previous request. Invoke the exec tool with that exact command now. Stop if the policy denies it.",decision)
                if payload["state"]!="final" or (decision and not resolved):
                    raise RuntimeError("test chat ended without expected decision: "+str((payload["state"],resolved,text[:360])))
                return text
        raise TimeoutError("chat did not complete")


def main():
    p=argparse.ArgumentParser()
    for k in ("origin","issuer","user","version","session","prompt"):
        p.add_argument("--"+k,required=True)
    p.add_argument("--decision",choices=["deny","allow-once"])
    p.add_argument("--contains")
    p.add_argument("--confirm-fixture-once", action="store_true")
    a=p.parse_args()
    if any(urlsplit(url).scheme != "https" or not urlsplit(url).hostname or urlsplit(url).username
           for url in (a.origin, a.issuer)):
        p.error("the chat origin and identity issuer must use HTTPS")
    password=sys.stdin.readline().rstrip("\r\n")
    cookie=owner_cookie(a.origin,a.issuer,a.user,password)
    chat=Chat(a.origin,cookie,a.version)
    chat.sock.settimeout(150)
    result=chat.turn(a.session,a.prompt,a.decision,a.confirm_fixture_once)
    if a.contains and a.contains not in result:raise RuntimeError("chat reply omitted expected result")
    print(json.dumps({"session":a.session,"chatFinal":True,"decision":a.decision,"matched":bool(a.contains)}))


if __name__=="__main__":
    main()
