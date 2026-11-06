// Run with Node 24 inside the trusted archive. Snapshot the completed fixture
// turns, not later model chats: legitimate new tool attempts append audit rows.
const {DatabaseSync}=require('node:sqlite');
const {createHash}=require('node:crypto');
const prefix=process.argv[2];
if (!/^agent:main:portal-[0-9a-f]{8,16}-$/.test(prefix)) throw Error("registration-specific session prefix required");
const db=new DatabaseSync('/history/audit.db',{readOnly:true});
const fixtureTurns=new Set(['read','deny','approve'].map(turn=>prefix+turn));
// Keep exact sequence, ID and body bytes for every matching row. Later lifecycle
// turns may append records; changes to the original fixture still change its hash.
const rows=db.prepare('SELECT seq,id,body FROM records ORDER BY seq').all().filter(x=>fixtureTurns.has(JSON.parse(x.body).task?.id));
const byTurn={};
for(const row of rows){
  const event=JSON.parse(row.body);
  (byTurn[event.task.id.slice(prefix.length)]??=[]).push({tool:event.tool,decision:event.decision});
}
for(const [turn,tool,expected] of [['read','read',['allow']],['deny','exec',['approval_required','rejected']],['approve','exec',['approval_required','approved']]]){
  const decisions=(byTurn[turn]??[]).filter(e=>e.tool===tool).map(e=>e.decision);
  if (!expected.every((v,i)=>decisions.indexOf(v)>=0 && (!i || decisions.indexOf(v)>decisions.indexOf(expected[i-1]))))
    throw Error('missing decision sequence for '+turn+': '+JSON.stringify(decisions));
}
console.log(JSON.stringify({records:rows.length,sha256:createHash('sha256').update(JSON.stringify(rows)).digest('hex'),byTurn}));
