// Runs after the generated startup command verified both read-only trees.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {spawn, spawnSync, execFileSync} from 'node:child_process';
import {createInterface} from 'node:readline';
const plugin = 'daily-briefing';
function cli(...args) {
  return JSON.parse(execFileSync('openclaw',args,{encoding:'utf8',maxBuffer:16*1024*1024,timeout:120000}));
}
const inspect = cli('plugins','inspect',plugin,'--runtime','--json');
assert.equal(inspect.plugin.status,'loaded');
assert.equal(inspect.plugin.rootDir,'/sandbox/harness');
const servers = ['slack-reader','gmail-reader','briefing-writer'];
assert.deepEqual(inspect.mcpServers.filter(s=>!s.unsupported).map(s=>s.name).sort(), [...servers].sort());
assert.ok(cli('skills','list','--json').skills.some(s=>s.name===plugin && s.eligible));
console.log(JSON.stringify({bundle:plugin,skill:true,registered:servers}));
const source = JSON.parse(fs.readFileSync(process.env.OPENCLAW_CONFIG_PATH)).mcp.servers;
const api=spawn(process.execPath,['/checks/apis.mjs'],{stdio:['ignore','pipe','inherit']});
try {
  const lines=createInterface({input:api.stdout});
  const [port]=await new Promise(resolve=>lines.once('line',v=>resolve([Number(v)])));
  assert.ok(port>0 && port<=65535);
  function call(name, tool, args={}, override={}) {
    const spec=source[name];
    const env=Object.fromEntries(Object.entries(spec.env).map(([k,v])=>[k,v.replace(/\$\{(\w+)\}/g,(_,key)=>process.env[key]||'')]));
    Object.assign(env,{PATH:process.env.PATH,HOME:process.env.HOME,
      SLACK_API_URL:'http://127.0.0.1:'+port+'/slack',GMAIL_API_URL:'http://127.0.0.1:'+port+'/gmail'},override);
    const input=[{id:1,method:'initialize',params:{protocolVersion:'2025-06-18'}},{id:2,method:'tools/list'},
                 {id:3,method:'tools/call',params:{name:tool,arguments:args}}]
                 .map(m=>JSON.stringify({...m,jsonrpc:'2.0'})).join('\n')+'\n';
    const run=spawnSync(spec.command,spec.args,{env,input,encoding:'utf8',timeout:30000});
    assert.equal(run.status,0,run.stderr);
    const results=run.stdout.trim().split('\n').map(JSON.parse);
    assert.ok(results.find(m=>m.id===2).result.tools.some(t=>t.name===tool));
    return results.find(m=>m.id===3).result;
  }
  for (const [server,variable] of [['slack-reader','SLACK_BOT_TOKEN'],['gmail-reader','GMAIL_ACCESS_TOKEN']]) {
    const denied=call(server,'new_messages',{},{[variable]:'invalid-fixture-token'});
    assert.equal(denied.isError,true);
    assert.match(denied.content[0].text,/HTTP 401/);
  }
  const read = sourceName => {
    const result=call(sourceName+'-reader','new_messages');
    assert.ok(!result.isError);
    return JSON.parse(result.content[0].text).items;
  };
  const slack=read('slack'), gmail=read('gmail');
  assert.ok(JSON.stringify(slack).includes('Can you review the PR today?'));
  assert.ok(JSON.stringify(gmail).includes('"subject":"Q3"'));
  const markdown='# Daily briefing\n\n'+slack[0].text+'\n'+gmail[0].subject;
  const saved=call('briefing-writer','save_briefing',{markdown});
  assert.ok(!saved.isError);
  assert.equal(fs.readFileSync(JSON.parse(saved.content[0].text).file,'utf8'),markdown);
  console.log(JSON.stringify({slackItems:slack.length,gmailItems:gmail.length,briefingSaved:true,denied:['slack','gmail']}));
  // New cursors for the independent agent conversation, leaving the direct-reader
  // result intact. Only test configuration points at synthetic loopback endpoints.
  const configPath=process.env.OPENCLAW_CONFIG_PATH;
  const config=JSON.parse(fs.readFileSync(configPath));
  const llm=spawn(process.execPath,['/checks/model.mjs'],{stdio:['ignore','pipe','inherit']});
  try {
    const out=createInterface({input:llm.stdout});
    const modelPort=await new Promise(resolve=>out.once('line',v=>resolve(Number(v))));
    out.on('line',line=>console.log(line));
    assert.ok(modelPort>0 && modelPort<=65535);
    config.models.providers.nvidia.baseUrl='http://127.0.0.1:'+modelPort+'/v1';
    config.mcp.servers['slack-reader'].env.SLACK_API_URL='http://127.0.0.1:'+port+'/slack';
    config.mcp.servers['gmail-reader'].env.GMAIL_API_URL='http://127.0.0.1:'+port+'/gmail';
    for (const scenario of ['allow','deny-slack','deny-gmail']) {
      for (const spec of Object.values(config.mcp.servers)) spec.env.BRIEFING_DIR='/sandbox/briefing/'+scenario;
      fs.writeFileSync(configPath,JSON.stringify(config),{mode:0o600});
      const env={...process.env};
      if (scenario==='deny-slack') env.SLACK_BOT_TOKEN='invalid-fixture-token';
      if (scenario==='deny-gmail') env.GMAIL_ACCESS_TOKEN='invalid-fixture-token';
      const agent=spawn('openclaw',['agent','--local','--agent','main','--session-id','briefing-'+scenario,
        '--message','Use the daily-briefing Slack and Gmail tools. Give me one item from each source or report its denial.','--json'],
        {env,stdio:['ignore','pipe','inherit']});
      let response='';agent.stdout.on('data',c=>response+=c);
      const code=await new Promise(resolve=>agent.once('exit',resolve));
      assert.equal(code,0,response.slice(-600));
      const expected='Slack: '+(scenario==='deny-slack'?'access denied (HTTP 401)':'Can you review the PR today?')+
        ' Gmail: '+(scenario==='deny-gmail'?'access denied (HTTP 401)':'Q3');
      assert.ok(response.includes(expected),response.slice(0,300));
      console.log(JSON.stringify({openClawChat:true,fixtureModel:true,scenario,reply:expected}));
    }
  } finally {llm.kill();}
} finally {
  api.kill();
}
