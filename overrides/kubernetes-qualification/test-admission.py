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
print(json.dumps({'scope':'runtime identity admission only; no CNI or positive runtime Pod proof','results':results}))
