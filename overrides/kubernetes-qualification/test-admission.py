"""Read-only admission smoke: dry-run Pod requests; no Pods are persisted."""
import copy,json,subprocess
ns='saw-k8s-test'
policy='saw-saw-k8s-test-runtime'
pod={'apiVersion':'v1','kind':'Pod','metadata':{'name':'saw-admission-smoke','namespace':ns},'spec':{'automountServiceAccountToken':False,'serviceAccountName':'default','securityContext':{'runAsNonRoot':True,'seccompProfile':{'type':'RuntimeDefault'}},'containers':[{'name':'probe','image':'registry.access.redhat.com/ubi9/python-311@sha256:7b6cb58d3ff034df7b300800bd89a469d9bd2f739d43250d76b9c9e805307ab5','command':['true'],'securityContext':{'allowPrivilegeEscalation':False,'capabilities':{'drop':['ALL']}}}]}}
results=[]
for role in (None,'workload','supervisor'):
 d=copy.deepcopy(pod)
 if role:d['metadata']['labels']={'openshell.ai/boundary-role':role,'openshell.ai/gateway-id':'saw-k8s-test'}
 r=subprocess.run(['oc','create','--dry-run=server','-f','-','-ojson'],input=json.dumps(d),text=True,capture_output=True)
 if role:
  assert r.returncode and policy in r.stderr and 'must preserve the approved ServiceAccount' in r.stderr, 'expected runtime identity policy denial'
 else:
  assert r.returncode==0, 'unrelated restricted Pod unexpectedly rejected'
 results.append({'role':role or 'ordinary','result':'rejected-runtime-identity' if role else 'admitted','dryRun':True})
# Reserve the labels trusted by proxy and governance ingress. Even correct labels
# and an owner reference do not authorize an arbitrary creator.
gateway=copy.deepcopy(pod)
gateway['metadata']['labels']={'app.kubernetes.io/instance':ns,'openshell.pattern/role':'gateway'}
def dryrun(obj,identity=()):
 return subprocess.run(['oc',*identity,'create','--dry-run=server','-f','-','-ojson'],input=json.dumps(obj),text=True,capture_output=True)
r=dryrun(gateway)
assert r.returncode and policy in r.stderr and 'Gateway identity requires' in r.stderr
results.append({'role':'forged-gateway-label','result':'rejected-gateway-identity','dryRun':True})
gateway['spec']['serviceAccountName']=ns+'-gateway'
uid=subprocess.check_output(['oc','get','statefulset',ns+'-gateway','-n',ns,'-o','jsonpath={.metadata.uid}'],text=True)
gateway['metadata']['ownerReferences']=[{'apiVersion':'apps/v1','kind':'StatefulSet','name':ns+'-gateway','uid':uid,'controller':True}]
r=dryrun(gateway)
assert r.returncode and policy in r.stderr and 'Only the Kubernetes StatefulSet controller' in r.stderr
results.append({'role':'forged-gateway-owner','result':'rejected-creator','dryRun':True})
r=dryrun(gateway,('--as=system:serviceaccount:kube-system:statefulset-controller','--as-group=system:serviceaccounts','--as-group=system:serviceaccounts:kube-system','--as-group=system:authenticated'))
assert r.returncode==0, 'legitimate StatefulSet controller dry-run unexpectedly rejected'
results.append({'role':'gateway-statefulset-controller','result':'admitted','dryRun':True})
print(json.dumps({'scope':'runtime/gateway identity admission only; no CNI or actual sandbox Pod proof','results':results}))
