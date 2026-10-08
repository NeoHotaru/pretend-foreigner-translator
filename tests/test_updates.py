import hashlib
import io
import sys
import tempfile
import threading
import unittest
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import translator_core as C
C.use_sandbox_config(str(Path(tempfile.gettempdir()) / 'pft_sandbox_update_tests'))
assert C.is_sandboxed()
import app_updates as U

PAYLOAD = b'local update fixture\x00\x01'
SHA = hashlib.sha256(PAYLOAD).hexdigest()
VERSION = '1.1.2'
NAME = 'pretend-foreigner-setup-%s.exe' % VERSION
URL = 'https://github.com/%s/releases/download/v%s/%s' % (C.REPO_SLUG, VERSION, NAME)

def release():
    return dict(tag_name='v'+VERSION, draft=False, prerelease=False, assets=[dict(
        name=NAME, state='uploaded', browser_download_url=URL,
        size=len(PAYLOAD), digest='sha256:'+SHA)])

class UpdateTests(unittest.TestCase):
    def setUp(self):
        base = Path(__file__).resolve().parents[1] / 'artifacts' / 'update-refresh'
        self.directory = tempfile.TemporaryDirectory(prefix='pft_sandbox_update_', dir=base)
        assert Path(self.directory.name).resolve().is_relative_to(base.resolve())
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.info = U.parse_release(release(), '1.1.1')

    def test_new_release_selects_exact_installer(self):
        self.assertEqual((self.info.version, self.info.filename, self.info.sha256), (VERSION, NAME, SHA))

    def test_current_version_never_downloads(self):
        self.assertIsNone(U.parse_release(release(), VERSION))

    def test_older_version_never_downloads(self):
        self.assertIsNone(U.parse_release(release(), '2.0.0'))

    def test_drafts_and_prereleases_are_ignored(self):
        for field in ('draft','prerelease'):
            data = release(); data[field] = True
            self.assertIsNone(U.parse_release(data, '1.0.5'))

    def test_unexpected_asset_url_is_rejected(self):
        data = release(); data['assets'][0]['browser_download_url'] = 'https://example.com/setup.exe'
        with self.assertRaises(U.UpdateError): U.parse_release(data, '1.0.5')

    def test_missing_installer_is_rejected(self):
        data = release(); data['assets'] = []
        with self.assertRaises(U.UpdateError): U.parse_release(data, '1.0.5')

    def test_missing_checksum_is_rejected(self):
        data = release(); data['assets'][0].pop('digest')
        with self.assertRaises(U.UpdateError): U.parse_release(data, '1.0.5')

    def test_incomplete_asset_is_rejected(self):
        data = release(); data['assets'][0]['state'] = 'new'
        with self.assertRaises(U.UpdateError): U.parse_release(data, '1.0.5')

    def test_invalid_version_and_size_are_rejected(self):
        for value in ('v1.1.2-preview','garbage'):
            data = release(); data['tag_name'] = value
            with self.assertRaises(U.UpdateError): U.parse_release(data, '1.0.5')
        data = release(); data['assets'][0]['size'] = 0
        with self.assertRaises(U.UpdateError): U.parse_release(data, '1.0.5')

    def download(self, data=PAYLOAD, **kwargs):
        return U.download_update(self.info, cache=self.root, opener=lambda *a, **k: io.BytesIO(data), **kwargs)

    def test_verified_download_replaces_part_atomically(self):
        progress = []
        path = self.download(progress=lambda n,total: progress.append((n,total)))
        self.assertEqual(path.read_bytes(), PAYLOAD)
        self.assertEqual(progress[-1], (len(PAYLOAD), len(PAYLOAD)))
        self.assertFalse((self.root/(NAME+'.part')).exists())

    def test_cache_is_reused_only_after_verification(self):
        path = self.download()
        calls = []
        result = U.download_update(self.info, cache=self.root, opener=lambda *a,**k: calls.append(1))
        self.assertEqual(result, path)
        self.assertFalse(calls)

    def test_corrupt_cache_is_replaced(self):
        (self.root/NAME).write_bytes(b'bad cache')
        self.assertEqual(self.download().read_bytes(), PAYLOAD)

    def test_size_and_checksum_mismatch_never_produce_executable(self):
        for data in (b'x', b'x'*len(PAYLOAD), PAYLOAD+b'x'):
            with self.assertRaises(U.UpdateError): self.download(data)
            self.assertFalse((self.root/NAME).exists())
            self.assertFalse((self.root/(NAME+'.part')).exists())

    def test_cancel_discards_partial_file(self):
        cancel = threading.Event()
        with self.assertRaises(U.DownloadCancelled):
            self.download(cancel=cancel, progress=lambda *a: cancel.set())
        self.assertFalse((self.root/NAME).exists())
        self.assertFalse((self.root/(NAME+'.part')).exists())

    def test_network_failure_discards_partial_file(self):
        def fail(*args, **kwargs): raise OSError('local fixture failure')
        with self.assertRaises(U.UpdateError):
            U.download_update(self.info, cache=self.root, opener=fail)
        self.assertFalse((self.root/(NAME+'.part')).exists())

    def test_filename_cannot_escape_cache(self):
        bad = replace(self.info, filename='../setup.exe')
        with self.assertRaises(U.UpdateError): U.download_update(bad, cache=self.root)

    def test_source_and_portable_do_not_overwrite_installed_app(self):
        exe = self.root/'portable'/'pretend-foreigner.exe'
        self.assertIsNone(U.installed_directory(exe, frozen=False, registered=[exe.parent]))
        self.assertIsNone(U.installed_directory(exe, frozen=True, registered=[self.root/'installed']))

    def test_installer_targets_running_install_directory(self):
        package = self.download()
        installed = self.root/'an installed app'
        exe = installed/'pretend-foreigner.exe'
        commands = []
        U.launch_installer(self.info, package, executable=exe, frozen=True,
                           registered=[installed], parent_pid=123,
                           runner=lambda args,**kwargs: commands.append((args,kwargs)))
        args, kwargs = commands[0]
        self.assertIn('/DIR='+str(installed.resolve()), args)
        self.assertIn('/PFTPID=123', args)
        self.assertIn('/PFTUPDATE=1', args)
        self.assertIn('/NORESTART', args)
        self.assertIn('/NOCLOSEAPPLICATIONS', args)
        self.assertEqual(kwargs['cwd'], str(package.parent))

    def test_package_is_reverified_at_launch(self):
        package = self.download(); package.write_bytes(b'changed after download')
        calls = []
        installed = self.root/'installed'
        with self.assertRaises(U.UpdateError):
            U.launch_installer(self.info, package, executable=installed/'pretend-foreigner.exe',
                frozen=True, registered=[installed], runner=lambda *a,**k: calls.append(1))
        self.assertFalse(calls)

    def test_launch_failure_keeps_package_for_retry(self):
        package = self.download(); installed = self.root/'installed'
        def fail(*args, **kwargs): raise OSError('cannot start')
        with self.assertRaises(U.UpdateError):
            U.launch_installer(self.info, package, executable=installed/'pretend-foreigner.exe',
                               frozen=True, registered=[installed], runner=fail)
        self.assertTrue(package.exists())

if __name__ == '__main__':
    unittest.main(verbosity=2)
