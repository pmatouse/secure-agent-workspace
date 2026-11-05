// Run with the stock OpenClaw image and the shared gate projected read-only.
import assert from "node:assert/strict";
import fs from "node:fs";
import { execFileSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import { handleBeforeToolCall } from "/sandbox/.saw/trusted/plugin/index.js";
import { AUDIT_PATH, POLICY_PATH, IDENTITY_PATH } from "/sandbox/.saw/trusted/plugin/tool-gate.mjs";

const identity = JSON.parse(fs.readFileSync(IDENTITY_PATH));
const config = {plugins: {allow: ["saw-tool-gate"], load: {paths: ["/sandbox/.saw/trusted/plugin"]},
                          entries: {"saw-tool-gate": {enabled: true}}}};
fs.writeFileSync(process.env.OPENCLAW_CONFIG_PATH, JSON.stringify(config), {mode: 0o600});
const listed = JSON.parse(execFileSync("openclaw", ["plugins", "list", "--json"], {encoding: "utf8"}));
const gate = listed.plugins.find(p => p.id === "saw-tool-gate");
assert.equal(gate?.enabled, true);
assert.equal(gate?.status, "loaded");
assert.equal(gate?.rootDir, fs.realpathSync("/sandbox/.saw/trusted/plugin"));
const mount = fs.readFileSync("/proc/self/mountinfo", "utf8").split("\n")
  .map(line => line.split(" ")).find(row => row[4] === "/sandbox/.saw/trusted");
assert(mount?.[5].split(",").includes("ro"));
assert.throws(() => fs.openSync(POLICY_PATH, "r+"), e => ["EACCES", "EROFS"].includes(e.code));
const ctx = {sessionKey: randomUUID()};
function call(toolName, params = {}) {
  return handleBeforeToolCall({toolName, params}, ctx);
}
assert.equal(call("read"), undefined);
assert.equal(call("saw-denied-tool").block, true);
const held = call("exec", {command: "git push origin main"});
assert.equal(held.requireApproval.pluginId, "saw-tool-gate");
held.requireApproval.onResolution("timeout");
const rows = fs.readFileSync(AUDIT_PATH, "utf8").trim().split("\n")
  .map(line => JSON.parse(line)).filter(row => row.task?.id === ctx.sessionKey);
assert.deepEqual(rows.map(row => row.decision), ["allow", "deny", "approval_required", "rejected"]);
assert(rows.every(row => row.user.subject === identity.subject && row.workspace === identity.workspace
                         && row.sandbox === identity.sandbox));
console.log(JSON.stringify({imagePluginLoaded: true, policyReadOnly: true,
                            decisions: rows.map(row => row.decision)}));
