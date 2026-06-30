import importlib.util
import json
import pathlib
import sys
import tempfile
import unittest
from datetime import datetime


SCRIPTS_DIR = pathlib.Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

MODULE_PATH = SCRIPTS_DIR / "workflow_checkpoints.py"
SPEC = importlib.util.spec_from_file_location("workflow_checkpoints", MODULE_PATH)
workflow_checkpoints = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = workflow_checkpoints
SPEC.loader.exec_module(workflow_checkpoints)


class WorkflowCheckpointsTest(unittest.TestCase):
    def test_audit_seeds_and_marks_missed_checkpoints_overdue(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "workflow-checkpoints.csv"

            audit = workflow_checkpoints.audit_day(
                "2026-06-24",
                path=path,
                now=datetime(2026, 6, 24, 17, 0),
            )

            self.assertEqual(audit["counts"]["overdue"], len(workflow_checkpoints.DEFAULT_CHECKPOINTS))
            self.assertEqual(audit["counts"]["done"], 0)
            self.assertTrue(path.exists())

    def test_mark_checkpoint_keeps_evidence_for_late_review(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "workflow-checkpoints.csv"

            row = workflow_checkpoints.mark_checkpoint(
                "2026-06-24",
                "morning_review",
                evidence="交易总表!AM9:AM16",
                notes="补做验证",
                completed_at="2026-06-24T17:05:00",
                path=path,
            )

            self.assertEqual(row["status"], "done")
            self.assertEqual(row["evidence"], "交易总表!AM9:AM16")
            self.assertIn("补做", row["notes"])

    def test_import_pipeline_records_marks_existing_stage_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = pathlib.Path(tmpdir)
            run_root = tmp / "pipeline-runs"
            checkpoint_path = tmp / "workflow-checkpoints.csv"
            stage_path = run_root / "2026-06-24" / "open.json"
            stage_path.parent.mkdir(parents=True)
            stage_path.write_text(json.dumps({"ok": True}), encoding="utf-8")

            marked = workflow_checkpoints.import_pipeline_records(
                "2026-06-24",
                root=run_root,
                path=checkpoint_path,
            )

            self.assertEqual(len(marked), 1)
            self.assertEqual(marked[0]["checkpoint"], "open_snapshot")
            self.assertEqual(marked[0]["status"], "done")


if __name__ == "__main__":
    unittest.main()
