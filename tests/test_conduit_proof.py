"""
tests/test_conduit_proof.py — Tests for ConduitProof (session proof bundle export).

Verifies:
- Bundle is created as a valid .tar.gz archive
- verify.py is embedded inside the bundle
- audit_log.jsonl is inside the bundle
- manifest.json contains correct metadata
- chain_hash matches the computed hash over row_hashes
- Empty session returns failure dict
"""
import hashlib
import json
import sys
import tarfile
import tempfile
import time
import types
import unittest
from pathlib import Path


# ---------------------------------------------------------------------------
# Import conduit_proof standalone
# ---------------------------------------------------------------------------

_PROOF_PATH = Path(__file__).parent.parent / "cato" / "tools" / "conduit_proof.py"
_proof_src = _PROOF_PATH.read_text(encoding="utf-8")

_proof_mod = types.ModuleType("conduit_proof_standalone")
_proof_mod.__file__ = str(_PROOF_PATH)
exec(compile(_proof_src, str(_PROOF_PATH), "exec"), _proof_mod.__dict__)

ConduitProof = _proof_mod.ConduitProof
VERIFY_PY = _proof_mod.VERIFY_PY


# ---------------------------------------------------------------------------
# Import audit.py standalone for integration tests
# ---------------------------------------------------------------------------

_AUDIT_PATH = Path(__file__).parent.parent / "cato" / "audit.py"
_audit_src = _AUDIT_PATH.read_text(encoding="utf-8")

# Patch the relative import
_audit_src_patched = _audit_src.replace(
    "from .platform import get_data_dir",
    "def get_data_dir(): return Path.home() / '.cato_test'"
)

_audit_mod = types.ModuleType("audit_standalone")
_audit_mod.__file__ = str(_AUDIT_PATH)
exec(compile(_audit_src_patched, str(_AUDIT_PATH), "exec"), _audit_mod.__dict__)

AuditLog = _audit_mod.AuditLog


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class MockAuditLog:
    """In-memory mock that supports get_session_rows()."""
    def __init__(self, rows=None):
        self._rows = rows or []

    def get_session_rows(self, session_id):
        return [r for r in self._rows if r.get("session_id") == session_id]


def make_fake_rows(session_id="sess-001", count=3):
    """Create fake audit rows with valid row_hash structure."""
    rows = []
    prev_hash = ""
    for i in range(1, count + 1):
        ts = time.time() + i
        rh = hashlib.sha256(
            f"{i}:{session_id}:tool_call:browser.navigate:0:{ts}:{prev_hash}".encode()
        ).hexdigest()
        row = {
            "id": i,
            "session_id": session_id,
            "action_type": "tool_call",
            "tool_name": "browser.navigate",
            "inputs_json": '{"url": "https://example.com"}',
            "outputs_json": '{"title": "Example"}',
            "cost_cents": 0,
            "error": "",
            "timestamp": ts,
            "prev_hash": prev_hash,
            "row_hash": rh,
        }
        rows.append(row)
        prev_hash = rh
    return rows


# ---------------------------------------------------------------------------
# Tests: ConduitProof.export()
# ---------------------------------------------------------------------------

class TestConduitProofExport(unittest.TestCase):

    def test_export_returns_success_dict(self):
        rows = make_fake_rows("sess-001", count=2)
        audit = MockAuditLog(rows=rows)
        proof = ConduitProof(audit, "sess-001")

        with tempfile.TemporaryDirectory() as tmpdir:
            result = proof.export(output_dir=tmpdir)

        self.assertTrue(result["success"])
        self.assertIn("path", result)
        self.assertIn("action_count", result)
        self.assertIn("chain_hash", result)
        self.assertIn("bundle_name", result)

    def test_export_creates_tar_gz_file(self):
        rows = make_fake_rows("sess-002", count=3)
        audit = MockAuditLog(rows=rows)
        proof = ConduitProof(audit, "sess-002")

        with tempfile.TemporaryDirectory() as tmpdir:
            result = proof.export(output_dir=tmpdir)
            bundle_path = Path(result["path"])
            # Check existence INSIDE the context manager while the temp dir still exists
            self.assertTrue(bundle_path.exists())
            self.assertTrue(bundle_path.name.endswith(".tar.gz"))

    def test_export_bundle_is_valid_tarball(self):
        rows = make_fake_rows("sess-003", count=2)
        audit = MockAuditLog(rows=rows)
        proof = ConduitProof(audit, "sess-003")

        with tempfile.TemporaryDirectory() as tmpdir:
            result = proof.export(output_dir=tmpdir)
            bundle_path = result["path"]

            # Must be openable as a gzip tarball
            with tarfile.open(bundle_path, "r:gz") as tar:
                members = tar.getnames()

        self.assertGreater(len(members), 0)

    def test_export_bundle_contains_verify_py(self):
        rows = make_fake_rows("sess-004", count=1)
        audit = MockAuditLog(rows=rows)
        proof = ConduitProof(audit, "sess-004")

        with tempfile.TemporaryDirectory() as tmpdir:
            result = proof.export(output_dir=tmpdir)

            with tarfile.open(result["path"], "r:gz") as tar:
                member_names = tar.getnames()

        self.assertTrue(any("verify.py" in n for n in member_names))

    def test_export_bundle_contains_audit_log_jsonl(self):
        rows = make_fake_rows("sess-005", count=2)
        audit = MockAuditLog(rows=rows)
        proof = ConduitProof(audit, "sess-005")

        with tempfile.TemporaryDirectory() as tmpdir:
            result = proof.export(output_dir=tmpdir)

            with tarfile.open(result["path"], "r:gz") as tar:
                member_names = tar.getnames()

        self.assertTrue(any("audit_log.jsonl" in n for n in member_names))

    def test_export_bundle_contains_manifest_json(self):
        rows = make_fake_rows("sess-006", count=1)
        audit = MockAuditLog(rows=rows)
        proof = ConduitProof(audit, "sess-006")

        with tempfile.TemporaryDirectory() as tmpdir:
            result = proof.export(output_dir=tmpdir)

            with tarfile.open(result["path"], "r:gz") as tar:
                member_names = tar.getnames()

        self.assertTrue(any("manifest.json" in n for n in member_names))

    def test_export_action_count_matches_rows(self):
        rows = make_fake_rows("sess-007", count=5)
        audit = MockAuditLog(rows=rows)
        proof = ConduitProof(audit, "sess-007")

        with tempfile.TemporaryDirectory() as tmpdir:
            result = proof.export(output_dir=tmpdir)

        self.assertEqual(result["action_count"], 5)

    def test_export_chain_hash_computed_from_row_hashes(self):
        rows = make_fake_rows("sess-008", count=3)
        audit = MockAuditLog(rows=rows)
        proof = ConduitProof(audit, "sess-008")

        with tempfile.TemporaryDirectory() as tmpdir:
            result = proof.export(output_dir=tmpdir)

        # Manually compute expected chain hash
        combined = "".join(r["row_hash"] for r in rows)
        expected_hash = hashlib.sha256(combined.encode()).hexdigest()
        self.assertEqual(result["chain_hash"], expected_hash)

    def test_export_manifest_contains_session_id(self):
        rows = make_fake_rows("sess-009", count=2)
        audit = MockAuditLog(rows=rows)
        proof = ConduitProof(audit, "sess-009")

        with tempfile.TemporaryDirectory() as tmpdir:
            result = proof.export(output_dir=tmpdir)

            with tarfile.open(result["path"], "r:gz") as tar:
                manifest_member = next(m for m in tar.getmembers() if "manifest.json" in m.name)
                manifest_data = json.loads(tar.extractfile(manifest_member).read().decode())

        self.assertEqual(manifest_data["session_id"], "sess-009")
        self.assertIn("exported_at", manifest_data)
        self.assertIn("action_count", manifest_data)
        self.assertIn("chain_hash", manifest_data)

    def test_export_verify_py_content_is_correct(self):
        rows = make_fake_rows("sess-010", count=1)
        audit = MockAuditLog(rows=rows)
        proof = ConduitProof(audit, "sess-010")

        with tempfile.TemporaryDirectory() as tmpdir:
            result = proof.export(output_dir=tmpdir)

            with tarfile.open(result["path"], "r:gz") as tar:
                verify_member = next(m for m in tar.getmembers() if "verify.py" in m.name)
                verify_content = tar.extractfile(verify_member).read().decode()

        self.assertIn("def verify()", verify_content)
        self.assertIn("hashlib", verify_content)
        self.assertIn("VERIFIED", verify_content)
        self.assertIn("audit_log.jsonl", verify_content)

    def test_export_returns_failure_for_empty_session(self):
        audit = MockAuditLog(rows=[])
        proof = ConduitProof(audit, "empty-session")

        with tempfile.TemporaryDirectory() as tmpdir:
            result = proof.export(output_dir=tmpdir)

        self.assertFalse(result["success"])
        self.assertIn("error", result)

    def test_export_with_public_key_pem(self):
        rows = make_fake_rows("sess-011", count=1)
        audit = MockAuditLog(rows=rows)
        pem = "# Ed25519 public key: abcdef1234567890\n"
        proof = ConduitProof(audit, "sess-011", public_key_pem=pem)

        with tempfile.TemporaryDirectory() as tmpdir:
            result = proof.export(output_dir=tmpdir)

            with tarfile.open(result["path"], "r:gz") as tar:
                pk_member = next(m for m in tar.getmembers() if "public_key.pem" in m.name)
                pk_content = tar.extractfile(pk_member).read().decode()

        self.assertIn("abcdef1234567890", pk_content)

    def test_compute_chain_hash_for_empty_rows_returns_hash_of_empty(self):
        audit = MockAuditLog(rows=[])
        proof = ConduitProof(audit, "sess-x")
        result = proof._compute_chain_hash([])
        expected = hashlib.sha256(b"empty").hexdigest()
        self.assertEqual(result, expected)

    def test_bundle_filename_contains_session_prefix_and_timestamp(self):
        rows = make_fake_rows("abcdefgh-xyz", count=1)
        audit = MockAuditLog(rows=rows)
        proof = ConduitProof(audit, "abcdefgh-xyz")

        with tempfile.TemporaryDirectory() as tmpdir:
            result = proof.export(output_dir=tmpdir)

        self.assertIn("abcdefg", result["bundle_name"])  # first 8 chars of session_id
        self.assertTrue(result["bundle_name"].endswith(".tar.gz"))


# ---------------------------------------------------------------------------
# Tests: Integration with real AuditLog
# ---------------------------------------------------------------------------

class TestConduitProofWithRealAuditLog(unittest.TestCase):
    """Integration tests using the actual AuditLog (in-memory SQLite)."""

    def _make_audit_log(self, tmpdir):
        db_path = Path(tmpdir) / "test_audit.db"
        log = AuditLog(db_path=db_path)
        log.connect()
        return log

    def test_export_proof_with_real_audit_log(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            audit = self._make_audit_log(tmpdir)
            session_id = "integration-sess-001"

            # Write some rows
            audit.log(
                session_id=session_id,
                action_type="tool_call",
                tool_name="browser.navigate",
                inputs={"url": "https://example.com"},
                outputs={"title": "Example"},
                cost_cents=0,
            )
            audit.log(
                session_id=session_id,
                action_type="tool_call",
                tool_name="browser.eval",
                inputs={"js_code": "document.title", "code_hash": "abc123"},
                outputs={"result": "Example", "success": True},
                cost_cents=0,
            )

            proof = ConduitProof(audit, session_id)
            result = proof.export(output_dir=tmpdir)

            self.assertTrue(result["success"])
            self.assertEqual(result["action_count"], 2)

            # Verify bundle structure
            with tarfile.open(result["path"], "r:gz") as tar:
                names = tar.getnames()
                self.assertTrue(any("verify.py" in n for n in names))
                self.assertTrue(any("audit_log.jsonl" in n for n in names))
                self.assertTrue(any("manifest.json" in n for n in names))

            audit.close()

    def test_audit_jsonl_in_bundle_has_valid_rows(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            audit = self._make_audit_log(tmpdir)
            session_id = "integration-sess-002"

            audit.log(
                session_id=session_id,
                action_type="tool_call",
                tool_name="browser.navigate",
                inputs={"url": "https://test.com"},
                outputs={"title": "Test"},
                cost_cents=0,
            )

            proof = ConduitProof(audit, session_id)
            result = proof.export(output_dir=tmpdir)

            with tarfile.open(result["path"], "r:gz") as tar:
                jsonl_member = next(m for m in tar.getmembers() if "audit_log.jsonl" in m.name)
                jsonl_content = tar.extractfile(jsonl_member).read().decode()

            rows = [json.loads(line) for line in jsonl_content.splitlines() if line.strip()]
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["session_id"], session_id)
            self.assertIn("row_hash", rows[0])

            audit.close()


# ---------------------------------------------------------------------------
# Tests: VERIFY_PY constant
# ---------------------------------------------------------------------------

class TestVerifyPyContent(unittest.TestCase):

    def test_verify_py_is_valid_python(self):
        """The embedded verify.py must compile without syntax errors."""
        try:
            compile(VERIFY_PY, "<verify.py>", "exec")
        except SyntaxError as e:
            self.fail(f"VERIFY_PY has syntax error: {e}")

    def test_verify_py_contains_hash_chain_verification(self):
        self.assertIn("hashlib.sha256", VERIFY_PY)
        self.assertIn("row_hash", VERIFY_PY)
        self.assertIn("prev_hash", VERIFY_PY)

    def test_verify_py_has_main_guard(self):
        self.assertIn('if __name__ == "__main__"', VERIFY_PY)
        self.assertIn("verify()", VERIFY_PY)

    def test_verify_py_uses_only_stdlib(self):
        """No third-party imports — just stdlib."""
        import ast
        tree = ast.parse(VERIFY_PY)
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.add(node.module.split(".")[0])

        stdlib_only = {"json", "hashlib", "base64", "sys", "pathlib"}
        non_stdlib = imports - stdlib_only
        self.assertEqual(non_stdlib, set(), f"Non-stdlib imports in verify.py: {non_stdlib}")


if __name__ == "__main__":
    unittest.main()
