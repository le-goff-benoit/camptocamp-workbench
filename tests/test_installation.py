import importlib.util
import json
from pathlib import Path
from unittest.mock import Mock, patch

from test_core import Fixture


class InstallationTests(Fixture):
    def test_install_creates_a_fresh_profile_without_personal_configuration(self):
        home = self.base/'colleague'; home.mkdir()
        script = Path(__file__).resolve().parents[1]/'scripts/manage.py'
        spec = importlib.util.spec_from_file_location('workbench_install_test', script)
        module = importlib.util.module_from_spec(spec)
        with patch('pathlib.Path.home', return_value=home):
            spec.loader.exec_module(module)
            with patch.object(module, 'executable', return_value='/usr/bin/openclaw'), patch.object(module.subprocess, 'run', return_value=Mock(returncode=0)):
                module.install()
                config = json.loads((home/'.openclaw-workbench/openclaw.json').read_text())
                credential = config['gateway']['auth']['token']
                module.install()
        repeated = json.loads((home/'.openclaw-workbench/openclaw.json').read_text())
        self.assertEqual(repeated['gateway']['auth']['token'], credential)
        settings = json.loads((home/'.local/share/openclaw-workbench/settings.json').read_text())
        self.assertEqual(repeated['ui']['assistant']['name'], 'OpenClaw')
        self.assertEqual(settings['roots'], [])
        self.assertEqual(settings['library'], [])
        self.assertFalse(settings['source_sync']['enabled'])
        self.assertEqual(settings['workflow_home'], '')
        unit = (home/'.config/systemd/user/openclaw-workbench.service').read_text()
        self.assertIn('UMask=0077', unit)
        self.assertTrue((home/'.local/share/applications/openclaw-workbench.desktop').is_file())
        self.assertIn('Name=OpenClaw', (home/'.local/share/applications/openclaw-workbench.desktop').read_text())
