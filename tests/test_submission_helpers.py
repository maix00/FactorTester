import unittest
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


_MODULE_PATH = Path(__file__).resolve().parents[1] / "server/modules/shared/submission_ids.py"
_SPEC = spec_from_file_location("submission_ids_for_test", _MODULE_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
make_submission_id = _MODULE.make_submission_id


class TestSubmissionId(unittest.TestCase):
    def test_preserves_explicit_id(self):
        self.assertEqual(make_submission_id(1234567890), "1234567890")
        self.assertEqual(make_submission_id("custom-id"), "custom-id")

    def test_generates_unique_ids_when_missing(self):
        generated = {make_submission_id(None) for _ in range(5)}

        self.assertEqual(len(generated), 5)
        self.assertNotIn("FactorTester", generated)

    def test_treats_blank_as_missing(self):
        generated = make_submission_id("   ")

        self.assertTrue(generated)
        self.assertNotEqual(generated, "   ")


if __name__ == '__main__':
    unittest.main()
