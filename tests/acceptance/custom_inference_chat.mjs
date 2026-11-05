import assert from 'node:assert/strict';
import {createHash,randomBytes} from 'node:crypto';
import {readFileSync,existsSync} from 'node:fs';
import {request} from 'node:http';
import {spawnSync} from 'node:child_process';
const cfg=JSON.parse(readFileSync(process.env.OPENCLAW_CONFIG_PATH,'utf8'));
const provider=cfg.models.providers['custom-inference'];
assert.equal(provider.baseUrl,'https://models.fixture.test/v1');
assert.equal(provider.timeoutSeconds,300);
assert.equal(cfg.agents.defaults.model.primary,'custom-inference/fixture/model');
assert.equal(provider.apiKey,'${CUSTOM_INFERENCE_API_KEY}');
assert.ok(!existsSync('/credential/api_key') && !existsSync('/var/run/saw/secrets/inference/api_key'));
const denied=await new Promise((resolve,reject)=>{
  const r=request({hostname:'127.0.0.1',port:3128,method:'CONNECT',path:'denied.fixture.test:443',headers:{host:'denied.fixture.test:443'}});
  r.on('connect',(res,s)=>{s.destroy();resolve(res.statusCode);});r.on('error',reject);r.end();
});
assert.equal(denied,403);
const nonce='fixture-'+randomBytes(12).toString('hex');
const turn=spawnSync('openclaw',['agent','--local','--agent','main','--session-id',nonce,'--message','Verify challenge '+nonce,'--json'],
  {encoding:'utf8',timeout:180000,maxBuffer:8e6});
assert.equal(turn.status,0,(turn.stderr||'').slice(-700));
const expected='verified-'+createHash('sha256').update(nonce).digest('hex').slice(0,24);
assert.ok(turn.stdout.includes(expected),'missing authenticated endpoint reply');
console.log(JSON.stringify({chat:true,model:provider.models[0].id,timeoutSeconds:provider.timeoutSeconds,unapprovedConnect:denied,rawKeyMounted:false}));
