"""Safety and attribution tests for the opt-in STARTRACE-5 bridge."""
import json
import tempfile
import unittest
from pathlib import Path

from phitribrain.startrace_bridge import parse_receipt, render_witness_note, main


def example():
    return {
        "schema": "gmed-startrace-5:research-receipt:v1",
        "verdict": "ILLUSTRATIVE_PHYSICS_ONLY",
        "generatedAt": "2026-11-06T12:00:00Z",
        "model": "simplified instantaneous geometry",
        "historicalIdentificationConfirmed": False,
        "skyPathReproduced": False,
        "independentVerification": False,
        "inputs": {"distanceAu": 0.0026},
        "calculated": {"requiredSpeedKmS": 24.5},
        "evidence": [{
            "id": "matney-orbit",
            "category": "scientific-model",
            "status": "published-hypothesis",
            "statement": "An orbit is proposed, not measured.",
            "limitation": "Observations do not determine a unique orbit.",
            "source": "Matney 2025, page 395",
            "url": "https://doi.org/10.64150/193njt",
        }],
    }


def raw(value):
    return json.dumps(value, sort_keys=True).encode("utf-8")


class StartraceBridgeTest(unittest.TestCase):
    def test_accepts_illustrative_receipt_and_renders_attribution(self):
        data = raw(example())
        parsed = parse_receipt(data)
        note = render_witness_note(parsed, data)
        self.assertIn("SHA-256", note)
        self.assertIn("published-hypothesis", note)
        self.assertIn("> An orbit is proposed, not measured.", note)
        self.assertIn("not a fact-check", note)
        self.assertNotIn("confirmed comet", note)

    def test_refuses_forged_verification_flags(self):
        for key in ("historicalIdentificationConfirmed", "skyPathReproduced", "independentVerification"):
            value = example()
            value[key] = True
            with self.subTest(key=key):
                with self.assertRaises(ValueError):
                    parse_receipt(raw(value))

    def test_refuses_missing_boundary(self):
        value = example()
        del value["skyPathReproduced"]
        with self.assertRaises(ValueError):
            parse_receipt(raw(value))

    def test_refuses_wrong_schema_and_status(self):
        value = example()
        value["schema"] = "fake"
        with self.assertRaises(ValueError):
            parse_receipt(raw(value))
        value = example()
        value["evidence"][0]["status"] = "verified-truth"
        with self.assertRaises(ValueError):
            parse_receipt(raw(value))

    def test_refuses_untrusted_link_and_duplicate_source_id(self):
        value = example()
        value["evidence"][0]["url"] = "http://untrusted.example"
        with self.assertRaises(ValueError):
            parse_receipt(raw(value))
        value = example()
        value["evidence"].append(dict(value["evidence"][0]))
        with self.assertRaises(ValueError):
            parse_receipt(raw(value))

    def test_rejects_malformed_and_large_input(self):
        for payload in (b"", b"{", b"[]", b"\xff", b"a" * (1_048_576 + 1)):
            with self.subTest(payload=payload[:10]):
                with self.assertRaises(ValueError):
                    parse_receipt(payload)

    def test_preview_writes_only_explicit_new_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            input_path = Path(tmp) / "research.json"
            output_path = Path(tmp) / "source.md"
            input_path.write_bytes(raw(example()))
            self.assertEqual(main([str(input_path), "--output", str(output_path)]), 0)
            self.assertIn("matney-orbit", output_path.read_text(encoding="utf-8"))
            self.assertEqual(main([str(input_path), "--output", str(output_path)]), 1)
            self.assertEqual(input_path.read_bytes(), raw(example()))


if __name__ == "__main__":
    unittest.main()
