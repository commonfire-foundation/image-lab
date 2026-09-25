"""Safety checks for the user-local release installer (no package downloads)."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / 'install.py'


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bundle = self.root / 'bundle'
        self.bundle.mkdir()
        names = ('image_lab-0.1.0-py3-none-any.whl',
                 'imagescope-0.1.0rc2-py3-none-any.whl',
                 'install.py', 'LICENSE', 'image-lab.svg', 'imagescope-0.1.0rc2.tar.gz')
        hashes = {}
        for name in names:
            content = name.encode()
            (self.bundle / name).write_bytes(content)
            hashes[name] = hashlib.sha256(content).hexdigest()
        self.manifest = {'schema': 2, 'app_version': '0.1.0', 'imagescope_version': '0.1.0rc2',
                         'wheels': {'image_lab': names[0], 'imagescope': names[1]},
                         'provider_source': {'archive': names[-1], 'base_ref': '333cd177d6e0c8f63beae55c8ef5c46cea202faf'},
                         'sha256': hashes}
        (self.bundle / 'release.json').write_text(json.dumps(self.manifest), encoding='utf-8')

    def run_installer(self, *flags):
        return subprocess.run([sys.executable, str(INSTALLER), '--bundle', str(self.bundle),
                               '--install-root', str(self.root / 'root'),
                               '--bin-dir', str(self.root / 'bin'),
                               '--desktop-dir', str(self.root / 'apps'), '--dry-run', *flags],
                              capture_output=True, text=True, check=False)

    def test_dry_run_checks_bundle_without_writing(self):
        result = self.run_installer()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Dry run: nothing changed.', result.stdout)
        self.assertFalse((self.root / 'root').exists())
        self.assertFalse((self.root / 'bin').exists())

    def test_checksum_failure_precedes_any_install(self):
        (self.bundle / 'LICENSE').write_text('modified', encoding='utf-8')
        result = self.run_installer()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('checksum mismatch: LICENSE', result.stderr)
        self.assertFalse((self.root / 'root').exists())

    def test_existing_command_requires_explicit_replacement(self):
        (self.root / 'bin').mkdir()
        link = self.root / 'bin' / 'image-lab'
        link.symlink_to(self.root / 'older-install' / 'image-lab')
        result = self.run_installer()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('--replace-existing', result.stderr)
        result = self.run_installer('--replace-existing')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(link.readlink(), self.root / 'older-install' / 'image-lab')
        self.assertFalse((self.root / 'root').exists())

    def test_regular_file_is_never_overwritten(self):
        (self.root / 'bin').mkdir()
        (self.root / 'bin' / 'image-lab').write_text('owned', encoding='utf-8')
        result = self.run_installer('--replace-existing')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('non-symlink', result.stderr)
        self.assertEqual((self.root / 'bin' / 'image-lab').read_text(), 'owned')


if __name__ == '__main__':
    unittest.main()
