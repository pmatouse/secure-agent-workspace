// Runs through the stock workspace CLI as the sandbox user. The local CLI
// password stays in the sandbox; only the authenticated UI identity is trusted.
const fs = require("node:fs");
const crypto = require("node:crypto");
const [origin, owner] = process.argv.slice(1);
if (!/^https:\/\/[a-z0-9.-]+$/.test(origin) || !/^[a-z0-9-]+$/.test(owner))
  throw new Error("invalid site UI binding");
const file = "/sandbox/workspace/.openclaw/openclaw.json";
const data = JSON.parse(fs.readFileSync(file, "utf8"));
const gw = data.gateway;
if (!gw || gw.bind !== "loopback" || gw.port !== 18789)
  throw new Error("unexpected OpenClaw listener");
const password = gw.auth.password || gw.auth.token;
if (typeof password !== "string" || !/^[a-f0-9]{64}$/.test(password))
  throw new Error("local gateway credential unavailable");
const before = JSON.stringify(gw);
gw.trustedProxies = ["127.0.0.1/32", "::1/128"];
gw.controlUi = {...gw.controlUi, allowedOrigins:[origin]};
gw.auth = {mode:"trusted-proxy", password, trustedProxy:{
  userHeader:"x-forwarded-email", allowUsers:[owner], allowLoopback:true,
  deviceAutoApprove:{enabled:true, scopes:["operator.read","operator.write"]}
}};
if (JSON.stringify(gw) !== before) {
  const tmp = file + "." + crypto.randomUUID();
  fs.writeFileSync(tmp, JSON.stringify(data), {flag:"wx",mode:0o600});
  fs.renameSync(tmp, file);
  console.log("Owner browser policy applied");
}
