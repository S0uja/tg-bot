import json
import unittest
from pathlib import Path


class ReferenceSheetWorkflowTest(unittest.TestCase):
    def test_reference_sheet_is_single_person_body_reference(self):
        data = json.loads((Path(__file__).parents[1] / "workflows" / "reference_sheet_api.json").read_text(encoding="utf-8"))
        positive = data["2"]["inputs"]["text"]
        self.assertIn("single adult woman", positive)
        self.assertIn("one person only", positive)
        self.assertEqual(data["4"]["inputs"]["width"], 512)
        self.assertEqual(data["4"]["inputs"]["height"], 768)
        self.assertEqual(data["7"]["inputs"]["input_faces_index"], "0")
