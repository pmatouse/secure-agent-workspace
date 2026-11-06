"""Exercise the exact archive reader against a real temporary SQLite database."""
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tests/acceptance/portal_audit_evidence.cjs"
PREFIX = "agent:main:portal-12345678abcdef12-"
NODE = shutil.which("node")

# Remap only the fixed archive path in this test's dependency injection. Run
# the unmodified reader with a real Node SQLite connection in read-only mode.
DRIVER = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const {DatabaseSync} = require('node:sqlite');
const [script, database, prefix] = process.argv.slice(1);
vm.runInNewContext(fs.readFileSync(script, 'utf8'), {
  process: {argv: ['node', '-', prefix]},
  console,
  require(name) {
    if (name !== 'node:sqlite') return require(name);
    return {DatabaseSync: class {
      constructor(path, options) {
        assert.equal(path, '/history/audit.db');
        assert.equal(options.readOnly, true);
        return new DatabaseSync(database, {readOnly: true});
      }
    }};
  }
}, {filename: script});
"""


@pytest.fixture
def database(tmp_path):
    if not NODE:
        pytest.skip("Node with node:sqlite is required")
    available = subprocess.run([NODE, "-e", "require('node:sqlite')"], capture_output=True)
    if available.returncode:
        pytest.skip("Node with node:sqlite is required")
    path = tmp_path / "audit.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE records (seq INTEGER PRIMARY KEY, id TEXT, body TEXT)")
        for seq, (turn, tool, decision) in enumerate([
            ("read", "read", "allow"),
            ("deny", "exec", "approval_required"),
            ("deny", "exec", "rejected"),
            ("approve", "exec", "approval_required"),
            ("approve", "exec", "approved"),
        ], 1):
            body = json.dumps({"task": {"id": PREFIX + turn}, "tool": tool,
                               "decision": decision, "details": "original bytes"})
            db.execute("INSERT INTO records VALUES (?, ?, ?)", (seq, f"event-{seq}", body))
    return path


def evidence(database, *, success=True):
    result = subprocess.run([NODE, "-e", DRIVER, str(SCRIPT), str(database), PREFIX],
                            capture_output=True, text=True)
    if success:
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)
    assert result.returncode != 0
    return result.stderr


def test_later_chat_appends_do_not_change_completed_fixture(database):
    before = evidence(database)
    assert before["records"] == 5
    with sqlite3.connect(database) as db:
        body = json.dumps({"task": {"id": PREFIX + "after-update"},
                           "tool": "exec", "decision": "deny"})
        db.execute("INSERT INTO records VALUES (6, 'later-denial', ?)", (body,))
    assert evidence(database) == before


@pytest.mark.parametrize("field", ["seq", "id", "body"])
def test_original_sequence_identity_and_body_bytes_remain_pinned(database, field):
    before = evidence(database)
    with sqlite3.connect(database) as db:
        if field == "seq":
            db.execute("UPDATE records SET seq=20 WHERE seq=1")
        elif field == "id":
            db.execute("UPDATE records SET id='replacement' WHERE seq=1")
        else:
            # Decisions are unchanged; even whitespace changes must be detected.
            db.execute("UPDATE records SET body=body || ' ' WHERE seq=1")
    after = evidence(database)
    assert after["records"] == before["records"]
    assert after["sha256"] != before["sha256"]


def test_missing_original_decision_fails_validation(database):
    with sqlite3.connect(database) as db:
        db.execute("DELETE FROM records WHERE seq=3")
    assert "missing decision sequence for deny" in evidence(database, success=False)


def test_added_original_turn_record_changes_snapshot(database):
    before = evidence(database)
    with sqlite3.connect(database) as db:
        db.execute("INSERT INTO records SELECT 6, 'extra', body FROM records WHERE seq=1")
    after = evidence(database)
    assert after["records"] == 6
    assert after["sha256"] != before["sha256"]
