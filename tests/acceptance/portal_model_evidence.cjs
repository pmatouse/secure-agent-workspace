// Print only the model metadata of the specific synthetic completion.
const fs = require('node:fs');
const path = require('node:path');
const nonce = process.argv[1];
if (!/^[a-f0-9]{20}$/.test(nonce)) throw Error('invalid test nonce');
const dir = '/sandbox/workspace/.openclaw/agents/main/sessions';
const matches = [];
for (const entry of fs.readdirSync(dir, {withFileTypes:true})) {
  if (!entry.isFile() || !entry.name.endsWith('.jsonl')) continue;
  for (const line of fs.readFileSync(path.join(dir,entry.name),'utf8').split('\n').filter(Boolean)) {
    const {message} = JSON.parse(line);
    if (message?.role !== 'assistant' || !Array.isArray(message.content)) continue;
    if (message.content.some(c => c.type === 'text' && c.text.includes(nonce)))
      matches.push({provider: message.provider, model: message.model});
  }
}
if (matches.length !== 1) throw Error('expected one matching assistant completion');
console.log(JSON.stringify(matches[0]));
