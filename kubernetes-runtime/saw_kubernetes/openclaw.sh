set -eu
umask 077
export HOME=/sandbox/workspace OPENCLAW_HOME=/sandbox/workspace
export OPENCLAW_CONFIG_PATH=/sandbox/workspace/.openclaw/openclaw.json
export TMPDIR=/sandbox/workspace/.openclaw/state SQLITE_TMPDIR=/sandbox/workspace/.openclaw/state
mkdir -p "$TMPDIR"
# Only the stock gateway's injected placeholder is visible here. Keep its
# environment reference in the config so the supervisor can rotate it.
node - "$1" <<'JS'
const fs = require('node:fs');
const crypto = require('node:crypto');
const model = process.argv[2];
const config = {
  gateway: {mode: 'local', bind: 'loopback', port: 18789,
            auth: {mode: 'token', token: crypto.randomBytes(32).toString('hex')}},
  models: {providers: {openai: {baseUrl: 'https://api.openai.com/v1',
    api: 'openai-completions', apiKey: '${OPENAI_API_KEY}',
    models: [{id: model, name: model}]}}},
  agents: {defaults: {model: {primary: 'openai/' + model},
    workspace: '/sandbox/workspace/project'}},
  tools: {deny: ['*']}
};
const target = process.env.OPENCLAW_CONFIG_PATH;
const tmp = target + '.' + crypto.randomUUID();
fs.writeFileSync(tmp, JSON.stringify(config), {flag: 'wx', mode: 0o600});
fs.renameSync(tmp, target);
JS
exec openclaw gateway run --bind loopback --port 18789
