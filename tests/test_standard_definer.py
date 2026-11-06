"""Definition Genesis regression tests."""
import json
import tempfile
import unittest
from pathlib import Path
from phitribrain.standard_definer import (
    SCHEMA, draft, validate_record, compare, fingerprint, read_record, main,
)


def fixture():
    item = draft("physics.dimension", "Dimension", "physics", "spacetime models")
    item["definition"] = "An independent coordinate in a specified model."
    item["epistemic_status"] = "hypothesis"
    item["alternatives"] = [{
        "label": "Extra dimensions",
        "definition": "A model with additional compact coordinates.",
        "status": "speculative",
        "distinguishing_test": "Identify reproducible observable consequences."
    }]
    return item


class DefinitionTests(unittest.TestCase):
    def test_candidate_valid_but_unverified(self):
        result = validate_record(fixture())
        self.assertTrue(result["valid"], result["errors"])
        self.assertTrue(result["warnings"])

    def test_draft_not_complete(self):
        self.assertFalse(validate_record(draft(
            "physics.dimension", "Dimension", "physics", "spacetime models"))["valid"])

    def test_unknown_field_and_missing_required_fail(self):
        item = fixture()
        item["AI_certified"] = True
        self.assertFalse(validate_record(item)["valid"])
        del item["AI_certified"]
        del item["domain"]
        self.assertFalse(validate_record(item)["valid"])

    def test_never_self_approve(self):
        item = fixture()
        item["review_state"] = "approved"
        self.assertFalse(validate_record(item)["valid"])

    def test_model_supported_requires_source_attribution(self):
        item = fixture()
        item["epistemic_status"] = "model_supported"
        self.assertFalse(validate_record(item)["valid"])
        item["evidence"] = [{
            "source_id": "src_1", "claim_id": "clm_1",
            "quote": "Source asserts a statement.", "stance": "supports"
        }]
        result = validate_record(item)
        self.assertTrue(result["valid"], result["errors"])
        self.assertIn("unverified", result["warnings"][0])

    def test_comparison_never_claims_contradiction(self):
        a, b = fixture(), fixture()
        b["definition"] = "Another description."
        self.assertEqual(compare(a, b)["outcome"], "competing_wording_requires_review")
        b["context"] = "machine learning"
        self.assertEqual(compare(a, b)["outcome"], "different_contexts")
        b["concept_id"] = "math.dimension"
        self.assertEqual(compare(a, b)["outcome"], "different_concepts")

    def test_digest_stable_and_sensitive(self):
        a = fixture()
        b = json.loads(json.dumps(a, sort_keys=True))
        self.assertEqual(fingerprint(a), fingerprint(b))
        b["revision"] = 2
        self.assertNotEqual(fingerprint(a), fingerprint(b))

    def test_revision_bool_and_unknown_status_rejected(self):
        item = fixture()
        item["revision"] = True
        self.assertFalse(validate_record(item)["valid"])
        item["revision"] = 1
        item["epistemic_status"] = "VERIFIED_BY_AI"
        self.assertFalse(validate_record(item)["valid"])

    def test_bad_relation_and_self_link(self):
        item = fixture()
        item["relations"] = [{"type": "related_to", "target_id": "physics.dimension", "why": "self"}]
        self.assertFalse(validate_record(item)["valid"])
        item["relations"][0]["target_id"] = "physics.spacetime"
        item["relations"][0]["type"] = "made_up"
        self.assertFalse(validate_record(item)["valid"])

    def test_duplicate_json_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / "dup.json"
            p.write_text('{"x":1,"x":2}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "duplicate"):
                read_record(p)

    def test_record_size_bound(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / "large.json"
            p.write_bytes(b" " * 262145)
            with self.assertRaisesRegex(ValueError, "exceeds"):
                read_record(p)

    def test_cli_smoke(self):
        with tempfile.TemporaryDirectory() as temp:
            left, right = Path(temp) / "left.json", Path(temp) / "right.json"
            left.write_text(json.dumps(fixture()), encoding="utf-8")
            right.write_text(json.dumps(fixture()), encoding="utf-8")
            self.assertEqual(main(["validate", str(left)]), 0)
            self.assertEqual(main(["compare", str(left), str(right)]), 0)
            left.write_text('{"bad":1}', encoding="utf-8")
            self.assertEqual(main(["validate", str(left)]), 2)

    def test_invalid_unhashable_status_values_fail_cleanly(self):
        item = fixture()
        item["epistemic_status"] = []
        self.assertFalse(validate_record(item)["valid"])
        item["epistemic_status"] = "draft"
        item["alternatives"][0]["status"] = {}
        self.assertFalse(validate_record(item)["valid"])
        item["alternatives"][0]["status"] = "speculative"
        item["evidence"] = [{
            "source_id": "s", "claim_id": "c", "quote": "q", "stance": []
        }]
        self.assertFalse(validate_record(item)["valid"])
        item["evidence"] = []
        item["relations"] = [{"type": [], "target_id": "math.point", "why": "r"}]
        self.assertFalse(validate_record(item)["valid"])

    def test_nonfinite_json_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / "nan.json"
            p.write_text('{"value": NaN}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "nonfinite"):
                read_record(p)

    def test_schema_identifier(self):
        self.assertEqual(SCHEMA, "phi369.standard-definition.v0.1")


if __name__ == "__main__":
    unittest.main()
