// Read only the named synthetic session. Newer images compress large events.
const {DatabaseSync} = require('node:sqlite');
const {zstdDecompressSync} = require('node:zlib');
const [nonce, session] = process.argv.slice(1);
if (!/^[a-f0-9]{20}$/.test(nonce) || !/^agent:main:portal-[a-f0-9]{16}-[a-z-]+$/.test(session))
  throw Error('invalid test nonce or session');
const db = new DatabaseSync('/sandbox/workspace/.openclaw/agents/main/agent/openclaw-agent.sqlite', {readOnly:true});
const rows = db.prepare(`SELECT t.* FROM transcript_events t
  JOIN session_nodes s ON s.current_session_id = t.session_id WHERE s.session_key = ?`).all(session);
const matches = [];
for (const row of rows) {
  const {message} = JSON.parse(row.event_json || zstdDecompressSync(row.event_zstd));
  if (message?.role !== 'assistant' || !Array.isArray(message.content)) continue;
  if (message.content.some(c => c.type === 'text' && c.text.includes(nonce))) {
    matches.push({provider: message.provider, model: message.model, responseModel: message.responseModel,
                  providerResponse: Boolean(message.responseId)});
  }
}
if (matches.length !== 1) throw Error('expected one matching assistant completion');
console.log(JSON.stringify(matches[0]));
