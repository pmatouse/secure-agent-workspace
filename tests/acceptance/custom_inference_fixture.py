"""Render an isolated test of OpenClaw, the real SAW proxy and a controlled HTTPS endpoint."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "kubernetes-runtime"))
from saw_kubernetes import compile_profile_files
from saw_kubernetes import provider as governed
from briefing_fixture import IMAGE as TLS_HELPER_IMAGE


def fixture_inputs():
    site = yaml.safe_load((ROOT / "examples/portal-container/glmhg.yaml").read_text())
    owner, = site["portal"]["containerSites"].values()
    image = owner["profileImageOverrides"]["data-science"]["notebook"]
    rendered = subprocess.check_output(["helm", "template", "fixture", str(ROOT/"charts/saw-bom"),
        "--set", "profiles[0]=custom-inference", "--set", "webSearch.enabled=false",
        "--set-string", "imageOverrides.notebook="+image], text=True)
    cfg = dict(namespace="saw-fixture", namespaceUID="fixture", ownerSubject="fixture-owner", mode="container",
               ownerID="b032b2e4-2cd5-47a7-8ef8-ac73e15700b1", gatewayVersion="0.1.2-rhaiv.6",
               approvedCredentialFreeProviders=[], openAIProxySecret="inference",
               proxyBindings=[{"type":"custom-inference","secret":"inference","key":"api_key","refresh":False}],
               customInferenceURL="https://models.fixture.test/v1", modelInputs={"inference.model":"fixture/model"},
               bindings={"default/notebook":{"workspace":{"claimName":"workspace-fixture","uid":"fixture-pvc","readOnly":False}}})
    return yaml.safe_load(rendered)["data"], cfg


def render(suffix, runtime_image):
    if not re.fullmatch(r"[^\s]+@sha256:[a-f0-9]{64}", runtime_image):
        raise ValueError("digest-pinned controller image required")
    if not re.fullmatch(r"[a-z0-9-]{1,20}", suffix):
        raise ValueError("unique fixture suffix required")
    files,cfg = fixture_inputs()
    plan=compile_profile_files(files,cfg)
    workspace, = plan["workspaces"]
    provider, = workspace["providers"]
    sandbox, = workspace["sandboxes"]
    spec=sandbox["spec"]
    host=governed.custom_host(plan["customInferenceURL"])
    name="custom-inference-"+suffix
    labels={"saw.redhat.com/fixture":name}
    meta={"name":name,"labels":labels}
    policy={"markerPrefix":"saw-cred","allowHosts":[host],"profiles":{},
            "bindings":[{"secret":"inference","key":"api_key","providers":["custom-inference"]}]}
    assert governed.check_policy("custom-inference",provider["credentials"],policy,cfg["customInferenceURL"])
    scripts=Path(__file__).parent
    data={"config.json":json.dumps(policy),
          "server.mjs":(scripts/"custom_inference_server.mjs").read_text(),
          "test.mjs":(scripts/"custom_inference_chat.mjs").read_text()}
    resources=[{"apiVersion":"networking.k8s.io/v1","kind":"NetworkPolicy","metadata":meta,
                "spec":{"podSelector":{"matchLabels":labels},"policyTypes":["Ingress","Egress"],"ingress":[],"egress":[]}},
               {"apiVersion":"v1","kind":"ConfigMap","metadata":meta,"immutable":True,"data":data}]
    def mount(volume,path,readonly=False):
        return {"name":volume,"mountPath":path,"readOnly":readonly}
    image=spec["template"]["image"]
    proxy=yaml.safe_load((ROOT/"charts/saw-kubernetes-proxy/values.yaml").read_text())["image"]
    security={"runAsNonRoot":True,"allowPrivilegeEscalation":False,"capabilities":{"drop":["ALL"]}}
    bootstrap="""set -eu
umask 077
openssl rand -hex 24 >/credential/api_key
printf '%s' 'https://models.fixture.test/v1' >/credential/url
for root in /broker-ca /upstream-ca; do
  openssl req -x509 -nodes -newkey rsa:2048 -days 1 -subj /CN=fixture-ca -addext basicConstraints=critical,CA:TRUE -keyout "$root/tls.key" -out "$root/tls.crt" 2>/dev/null
done
cp /broker-ca/tls.crt /public/broker.crt
cp /upstream-ca/tls.crt /public/upstream.crt
openssl req -new -nodes -newkey rsa:2048 -subj /CN=models.fixture.test -keyout /server/tls.key -out /tmp/server.csr 2>/dev/null
printf '%s\\n' 'subjectAltName=DNS:models.fixture.test' 'extendedKeyUsage=serverAuth' >/tmp/ext
openssl x509 -req -in /tmp/server.csr -CA /upstream-ca/tls.crt -CAkey /upstream-ca/tls.key -CAcreateserial -days 1 -extfile /tmp/ext -out /server/tls.crt 2>/dev/null
"""
    def env(values):
        return [{"name":k,"value":v} for k,v in values.items()]
    data["bom.json"]=json.dumps(files)
    data["bindings.json"]=json.dumps(cfg)
    data["revision"]=plan["revision"]
    bootstrap_plan = """from pathlib import Path
import json, shlex
from saw_kubernetes import compile_profile_files
checks = Path('/checks')
plan = compile_profile_files(json.loads((checks/'bom.json').read_text()), json.loads((checks/'bindings.json').read_text()))
assert plan['revision'] == (checks/'revision').read_text()
cmd = plan['workspaces'][0]['sandboxes'][0]['spec']['command'].copy()
entry = 'exec openclaw gateway run --bind loopback --port 18789'
assert cmd[2].count(entry) == 1
cmd[2] = cmd[2].replace(entry, 'exec node /checks/test.mjs')
Path('/launch/agent').write_text('exec ' + shlex.join(cmd))
print('compiledPlan=' + plan['revision'])
"""
    pod={"restartPolicy":"Never","automountServiceAccountToken":False,"activeDeadlineSeconds":900,
         "securityContext":{"seccompProfile":{"type":"RuntimeDefault"},"sysctls":[{"name":"net.ipv4.ip_unprivileged_port_start","value":"0"}]},
         "hostAliases":[{"ip":"127.0.0.1","hostnames":[host,"denied.fixture.test"]}],
         "volumes":[{"name":n,"emptyDir":{}} for n in ("credential","broker-ca","upstream-ca","server","public","workspace","launch")]
                   + [{"name":"config","configMap":{"name":name}}],
         "initContainers":[{"name":"compile","image":runtime_image,"command":["python3","-c",bootstrap_plan],"securityContext":security,
                            "volumeMounts":[mount("config","/checks",True),mount("launch","/launch")]},
                           {"name":"prepare","image":TLS_HELPER_IMAGE,"command":["sh","-ec",bootstrap],"securityContext":security,
                            "volumeMounts":[mount(v,"/"+v) for v in ("credential","broker-ca","upstream-ca","server","public")]},
                           {"name":"endpoint","image":image,"command":["node","/checks/server.mjs"],"restartPolicy":"Always",
                            "securityContext":security,"volumeMounts":[mount("config","/checks",True),mount("server","/server",True),mount("credential","/credential",True)]},
                           {"name":"broker","image":proxy,"args":["serve"],"restartPolicy":"Always","securityContext":security,
                            "env":env({"SSL_CERT_FILE":"/public/upstream.crt"}),
                            "volumeMounts":[mount("config","/etc/saw-proxy",True),mount("public","/public",True),
                                            mount("broker-ca","/var/run/saw/ca",True),mount("credential","/var/run/saw/secrets/inference",True)]}],
         "containers":[{"name":"agent","image":image,"command":["sh","/launch/agent"],"securityContext":security,
                        "env":env({**provider["credentials"],"NODE_EXTRA_CA_CERTS":"/public/broker.crt",
                                   "HTTPS_PROXY":"http://127.0.0.1:3128","HTTP_PROXY":"http://127.0.0.1:3128",
                                   "NODE_USE_ENV_PROXY":"1","NO_PROXY":"localhost,127.0.0.1","TMPDIR":"/tmp"}),
                        "volumeMounts":[mount("config","/checks",True),mount("public","/public",True),mount("workspace","/sandbox/workspace"),mount("launch","/launch",True)]}]}
    resources.append({"apiVersion":"batch/v1","kind":"Job","metadata":meta,
                      "spec":{"backoffLimit":0,"template":{"metadata":{"labels":labels},"spec":pod}}})
    return {"apiVersion":"v1","kind":"List","items":resources}


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suffix",required=True)
    parser.add_argument("--runtime-image", required=True)
    args=parser.parse_args()
    print(json.dumps(render(args.suffix, args.runtime_image)))
