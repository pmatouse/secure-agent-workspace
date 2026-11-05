// Never log credentials or prompt bodies; respond only to an authenticated synthetic test turn.
import {readFileSync} from 'node:fs';
import https from 'node:https';
import {createHash} from 'node:crypto';
const key = readFileSync('/credential/api_key','utf8').trim();
https.createServer({cert:readFileSync('/server/tls.crt'),key:readFileSync('/server/tls.key')},async(req,res)=>{
  if(req.method!=='POST'||req.url!=='/v1/chat/completions'||req.headers.host.split(':')[0]!=='models.fixture.test'){
    res.writeHead(404);res.end();return;
  }
  if(req.headers.authorization!=='Bearer '+key){res.writeHead(401);res.end();return;}
  let raw='';for await(const c of req){raw+=c;if(raw.length>4e6){res.writeHead(413);res.end();return;}}
  const body=JSON.parse(raw);
  const nonce=JSON.stringify(body.messages.filter(m=>m.role==='user')).match(/fixture-[a-f0-9]{24}/)?.[0];
  if(!nonce||body.model!=='fixture/model'){res.writeHead(400);res.end();return;}
  const base={id:'chatcmpl-'+nonce,model:body.model,created:Math.floor(Date.now()/1000)};
  const content='verified-'+createHash('sha256').update(nonce).digest('hex').slice(0,24);
  console.log(JSON.stringify({authorized:true,model:body.model,stream:Boolean(body.stream)}));
  if(body.stream){
    res.writeHead(200,{'content-type':'text/event-stream'});
    for(const [delta,finish_reason] of [[{role:'assistant',content},null],[{},'stop']])
      res.write('data: '+JSON.stringify({...base,object:'chat.completion.chunk',choices:[{index:0,delta,finish_reason}]})+'\n\n');
    res.end('data: [DONE]\n\n');
  }else{
    res.writeHead(200,{'content-type':'application/json'});res.end(JSON.stringify({...base,object:'chat.completion',
      choices:[{index:0,message:{role:'assistant',content},finish_reason:'stop'}]}));
  }
}).listen(443,'127.0.0.1');
