"""Run Python QA with no personal workflow, catalog, source library or project roots.

Path.home is isolated in this Python process; environment variables and the real
user home are never changed. Provider calls use the existing synthetic fixtures.
"""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT/'tests'))
with tempfile.TemporaryDirectory(prefix='workbench-portable-') as directory:
    with patch('pathlib.Path.home', return_value=Path(directory)):
        suite = unittest.defaultTestLoader.discover(str(ROOT/'tests'))
        result = unittest.TextTestRunner(verbosity=2).run(suite)
raise SystemExit(0 if result.wasSuccessful() else 1)
