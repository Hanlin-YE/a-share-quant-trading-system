import importlib.util
import json
import pathlib
import sys
import tempfile
import unittest


SCRIPTS_DIR = pathlib.Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

MODULE_PATH = SCRIPTS_DIR / "pipeline_review.py"
SPEC = importlib.util.spec_from_file_location("pipeline_review", MODULE_PATH)
pipeline_review = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = pipeline_review
SPEC.loader.exec_module(pipeline_review)


class PipelineReviewTest(unittest.TestCase):
    def write_stage(self, root, run_date, stage, payload):
        path = root / run_date / f"{stage}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")

    def test_missing_records_bucket(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            review = pipeline_review.review_pipeline_day("2026-06-11", root=pathlib.Path(tmpdir))

        self.assertEqual(review["failure_bucket"], "missing_pipeline_records")
        self.assertFalse(review["ok"])

    def test_cache_failure_bucket_from_preopen(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir)
            self.write_stage(
                root,
                "2026-06-11",
                "preopen",
                {"ok": False, "cache_health": {"ok": False}},
            )
            review = pipeline_review.review_pipeline_day("2026-06-11", root=root)

        self.assertEqual(review["failure_bucket"], "data_cache_unhealthy")
        self.assertIn("行情缓存", review["next_action"])

    def test_pipeline_ok_with_all_stages_present(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir)
            for stage in pipeline_review.STAGES:
                self.write_stage(root, "2026-06-11", stage, {"ok": True})
            review = pipeline_review.review_pipeline_day("2026-06-11", root=root)

        self.assertTrue(review["ok"])
        self.assertEqual(review["failure_bucket"], "pipeline_ok")
        self.assertEqual(review["missing_stages"], [])

    def test_latest_run_date_before_or_on_ignores_future_dates(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir)
            self.write_stage(root, "2026-06-10", "preopen", {"ok": True})
            self.write_stage(root, "2026-06-12", "preopen", {"ok": True})

            latest = pipeline_review.latest_run_date_before_or_on("2026-06-11", root=root)

        self.assertEqual(latest, "2026-06-10")

    def test_render_review_includes_next_action(self):
        text = pipeline_review.render_review(
            {
                "run_date": "2026-06-11",
                "failure_bucket": "pipeline_ok",
                "stage_status": {"preopen": "ok"},
                "order_count": 0,
                "next_action": "继续观察",
            }
        )

        self.assertIn("继续观察", text)


if __name__ == "__main__":
    unittest.main()
