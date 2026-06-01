from __future__ import annotations

import unittest

from qcoder.engines.feature_extraction.features.glossary_v0 import (
    FEATURE_GLOSSARY_V0,
    glossary_unknown_keys,
)
from qcoder.engines.feature_extraction.features.schema_v0 import FEATURE_NAMES_V0


class TestFeatureGlossary(unittest.TestCase):
    def test_all_schema_features_have_glossary_entry(self) -> None:
        missing = [name for name in FEATURE_NAMES_V0 if name not in FEATURE_GLOSSARY_V0]
        self.assertEqual(missing, [])

    def test_no_unknown_glossary_keys(self) -> None:
        self.assertEqual(glossary_unknown_keys(), set())


if __name__ == "__main__":
    unittest.main()

