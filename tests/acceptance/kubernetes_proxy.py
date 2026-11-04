#!/usr/bin/env python3
"""Opt-in live proxy transport test. No credential values used by the client or workload writes.

Uses an existing cluster login and a loopback-only port-forward. This tests the
proxy's TLS, provider binding and upstream egress, NOT client-side CNI ingress.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import ssl
import subprocess
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.request import HTTPSHandler, ProxyHandler, Request, build_opener


def oc(*args):
    result=subprocess.run(['oc',*args,'--request-timeout=20s'],capture_output=True,text=True,timeout=30)
    if result.returncode:
        raise RuntimeError('cluster read failed')
    return result.stdout


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--trusted-namespace',required=True)
    p.add_argument('--runtime-namespace',required=True)
    p.add_argument('--gateway',required=True)
    p.add_argument('--model',default='gpt-4.1-mini-2025-04-14')
    p.add_argument('--trust-only',action='store_true')
    args=p.parse_args()
    for name in [args.trusted_namespace,args.runtime_namespace,args.gateway]:
        if not re.fullmatch(r'[a-z0-9]([-a-z0-9]*[a-z0-9])?',name):
            p.error('explicit DNS-label namespaces/gateway required')
    name=args.gateway+'-proxy-ca'
    maps=[json.loads(oc('get','configmap',name,'-n',ns,'-o','json')) for ns in [args.trusted_namespace,args.runtime_namespace]]
    pem=maps[0]['data']['ca.crt']
    assert maps[1]['data']=={'ca.crt':pem} and maps[1].get('immutable') is True
    assert 'PRIVATE KEY' not in pem and pem.count('-----BEGIN CERTIFICATE-----')==1
    receipt={'publicCA_SHA256':hashlib.sha256(ssl.PEM_cert_to_DER_cert(pem)).hexdigest(),
             'runtimeConfigMapUID':maps[1]['metadata']['uid'],
             'privateCASecretUID':oc('get','secret',name,'-n',args.trusted_namespace,'-o','jsonpath={.metadata.uid}'),
             'publicProjectionMatches':True,'clientCNIIngressTested':False}
    if args.trust_only:
        print(json.dumps(receipt,sort_keys=True));return
    for key in list(os.environ):
        if key.lower().endswith('_proxy'):os.environ.pop(key)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    with tempfile.TemporaryDirectory(prefix='saw-proxy-public-ca-') as directory:
        path=Path(directory)/'ca.crt';path.write_text(pem)
        process=subprocess.Popen(['oc','-n',args.trusted_namespace,'port-forward',
            'service/'+args.gateway+'-credential-proxy',f'{port}:3128','--address=127.0.0.1'],
            stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        try:
            deadline=time.monotonic()+30
            while True:
                if process.poll() is not None:raise RuntimeError('port-forward failed')
                try:
                    with socket.create_connection(('127.0.0.1',port),timeout=1):break
                except OSError:
                    if time.monotonic()>deadline:raise RuntimeError('port-forward timeout')
                    time.sleep(.2)
            opener=build_opener(ProxyHandler({'https':f'http://127.0.0.1:{port}'}),
                                HTTPSHandler(context=ssl.create_default_context(cafile=str(path))))
            try:
                opener.open('https://example.org/',timeout=20)
                raise AssertionError('unapproved host unexpectedly permitted')
            except URLError as exc:
                assert '403 Forbidden' in str(exc.reason)
            receipt['unapprovedHostDenied']=True
            def request(marker):
                return Request('https://api.openai.com/v1/chat/completions',
                    data=json.dumps({'model':args.model,'messages':[{'role':'user','content':'Reply with exactly SAW_PROXY_OK. Do not use tools.'}],
                                     'max_tokens':20,'temperature':0}).encode(),
                    headers={'Authorization':'Bearer '+marker,'Content-Type':'application/json'})
            try:
                opener.open(request('saw-cred.unknown.api_key'),timeout=30)
                raise AssertionError('unknown marker unexpectedly permitted')
            except HTTPError as exc:
                assert exc.code==502
                assert exc.read(1024)==b'unknown or unbound credential marker\n'
                exc.close()
            receipt['unknownMarkerDenied']=True
            with opener.open(request('saw-cred.inference.api_key'),timeout=45) as response:
                body=json.load(response)
            assert body['choices'][0]['message']['content'].strip()=='SAW_PROXY_OK'
            receipt.update(realInference=True,model=body['model'],reply='SAW_PROXY_OK')
            print(json.dumps(receipt,sort_keys=True))
        finally:
            process.terminate()
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:process.kill();process.wait()


if __name__=='__main__':
    try:main()
    except Exception as exc:
        # Never emit request/response bodies or environment values on failure.
        print(json.dumps({'passed':False,'errorType':type(exc).__name__}))
        raise SystemExit(1)
