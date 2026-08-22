from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

from foundstore_preferences import FoundstorePreferences


class FoundstorePreferenceTests(unittest.TestCase):
    def test_preferences_survive_a_local_reload(self) -> None:
        with tempfile.TemporaryDirectory() as config_home, patch.dict(os.environ, {"XDG_CONFIG_HOME": config_home}):
            expected = FoundstorePreferences(theme="light", accent="oceano", view_mode="compact", grid_columns=5)
            expected.save()
            self.assertEqual(FoundstorePreferences.load(), expected)


if __name__ == "__main__":
    unittest.main()
