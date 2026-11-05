// Deterministic loopback model for a tool-dispatch test. Facts in the final reply
// must come from real tool output, which the runner checks against fixture data.
import http from 'node:http';
import {randomUUID} from 'node:crypto';
const sources=['slack-reader__new_messages','gmail-reader__new_messages'];
function completion(body) {
  const tools=body.tools?.map(t=>t.function?.name) || [];
  const prior=body.messages.filter(m=>m.role==='tool');
  let args={}, name, content;
  const requested=body.messages.flatMap(m=>m.tool_calls??[]).map(c=>c.function);
  const target=sources.find(t=>!requested.some(c=>c.name===t || (c.name==='tool_call' && c.arguments.includes(t))));
  if (target && tools.includes(target)) name=target;
  else if (target && tools.includes('tool_search') && !requested.some(c=>c.name==='tool_search' && c.arguments.includes(target))) {
    name='tool_search'; args={query:target};
  } else if (target && tools.includes('tool_call')) {
    name='tool_call'; args={name:target,arguments:{}};
  } else if (target) throw Error('no dispatch for '+target+'; offered '+tools.join(','));
  else {
    const output=JSON.stringify(prior);
    const slack=output.match(/Can you review the PR today\?/)?.[0];
    const mail=output.match(/\bQ3\b/)?.[0];
    const denied=output.includes('HTTP 401');
    if ((!slack || !mail) && !denied) throw Error('expected source item or explicit access denial');
    if (!slack && !mail) throw Error('both sources unavailable in one-source-denial case');
    content='Slack: '+(slack??'access denied (HTTP 401)')+' Gmail: '+(mail??'access denied (HTTP 401)');

  }
  const call=name ? {id:'call_'+randomUUID(),type:'function',function:{name,arguments:JSON.stringify(args)}} : null;
  console.log(JSON.stringify({phase:call?'tool':'reply',tool:call?.function.name}));
  return {call,content};
}
const server=http.createServer(async(req,res)=>{
  try {
    if(req.method!=='POST'||!req.url.endsWith('/chat/completions')) {res.writeHead(404);res.end();return;}
    let raw=''; for await (const c of req) {raw+=c;if(raw.length>4e6) throw Error('fixture input too large');}
    const body=JSON.parse(raw), {call,content}=completion(body);
    const id='chatcmpl-'+randomUUID(), base={id,created:Math.floor(Date.now()/1000),model:body.model};
    if (!body.stream) {
      res.writeHead(200,{'Content-Type':'application/json'});
      res.end(JSON.stringify({...base,object:'chat.completion',choices:[{index:0,message:{role:'assistant',content:content??null,...(call&&{tool_calls:[call]})},finish_reason:call?'tool_calls':'stop'}]}));return;
    }
    res.writeHead(200,{'Content-Type':'text/event-stream'});
    const chunk=(delta,finish_reason)=>res.write('data: '+JSON.stringify({...base,object:'chat.completion.chunk',choices:[{index:0,delta,finish_reason}]})+'\n\n');
    chunk({role:'assistant',...(call?{tool_calls:[{index:0,...call}]}:{content})},null);
    chunk({},call?'tool_calls':'stop');res.end('data: [DONE]\n\n');
  } catch(e) {console.error(e.message);res.writeHead(422);res.end('fixture assertion failed');}
});
server.listen(0,'127.0.0.1',()=>console.log(server.address().port));
