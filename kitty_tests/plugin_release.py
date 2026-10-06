#!/usr/bin/env python

import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from kitty.plugins import PluginManager
from tools.plugin_release import build_release, merge_catalogs


class TestPluginRelease(unittest.TestCase):
    def test_release_archive_and_catalog_are_reproducible_and_pinned(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            first_archive, first_catalog = build_release('dylmarriner/cat', 'plugin-smart-scroll-v1.0.0', root / 'first')
            second_archive, _ = build_release('dylmarriner/cat', 'plugin-smart-scroll-v1.0.0', root / 'second')
            self.assertEqual(first_archive.read_bytes(), second_archive.read_bytes())
            index = json.loads(first_catalog.read_text(encoding='utf-8'))
            entry = index['plugins'][0]
            self.assertEqual(entry['release_url'], 'https://github.com/dylmarriner/cat/releases/download/plugin-smart-scroll-v1.0.0/smart-scroll.zip')
            self.assertEqual(entry['archive_sha256'], hashlib.sha256(first_archive.read_bytes()).hexdigest())
            with zipfile.ZipFile(first_archive) as archive:
                self.assertEqual(set(archive.namelist()), {'plugin.json', 'main.py', 'README.rst', 'LICENSE'})
                manifest = json.loads(archive.read('plugin.json'))
                self.assertEqual(manifest['version'], entry['version'])
                self.assertEqual(archive.read('LICENSE'), (Path(__file__).resolve().parents[1] / 'kitty/plugin_packages/smart-scroll/LICENSE').read_bytes())

    def test_release_rejects_unmatched_tag_or_repository(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(ValueError, 'tag must match'):
                build_release('dylmarriner/cat', 'plugin-smart-scroll-v9.9.9', Path(td))
            with self.assertRaisesRegex(ValueError, 'owner/name'):
                build_release('https://github.com/dylmarriner/cat', 'plugin-smart-scroll-v1.0.0', Path(td))

    def test_built_release_installs_through_remote_catalog_host(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            archive_path, catalog_path = build_release('dylmarriner/cat', 'plugin-smart-scroll-v1.0.0', Path(td) / 'release')
            manager = PluginManager(Path(td) / 'config')
            catalog_url = 'https://example.org/catalog.json'
            manager.set_catalog_url(catalog_url)
            manager.load_remote_catalog(catalog_url, catalog_path.read_bytes())
            catalog_entry = manager.cached_remote_catalog_plugin('smart-scroll')
            installed = manager.install_remote_plugin('smart-scroll', catalog_entry['archive_sha256'], archive_path.read_bytes())
            self.assertTrue(installed['approval_required'])
            self.assertFalse(installed['enabled'])
            manager.enable('smart-scroll', frozenset(catalog_entry['capabilities']), confirmed=True, expected_digest=installed['content_digest'])
            self.assertEqual({x[0] for x in manager.key_mappings()}, {'smart-scroll'})
            self.assertTrue(manager.key_mappings())

    def test_release_builder_selects_package_and_its_license_from_tag(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            package_root = root / 'packages'
            package = package_root / 'example-tools'
            package.mkdir(parents=True)
            (package / 'plugin.json').write_text(
                json.dumps(
                    {
                        'id': 'example-tools',
                        'name': 'Example tools',
                        'version': '1.2.3',
                        'api_versions': [1],
                        'entry_point': 'main.py',
                        'capabilities': ['commands'],
                        'source_url': 'https://github.com/example/tools',
                        'license': 'MIT',
                        'settings': [],
                    }
                ),
                encoding='utf-8',
            )
            (package / 'main.py').write_text('def setup(api):\n    pass\n', encoding='utf-8')
            (package / 'LICENSE').write_text('Example MIT license text\n', encoding='utf-8')
            (package_root / 'catalog.json').write_text(
                json.dumps(
                    {
                        'schema_version': 1,
                        'plugins': [
                            {
                                'id': 'example-tools',
                                'name': 'Example tools',
                                'version': '1.2.3',
                                'description': 'Example package',
                                'api_versions': [1],
                                'capabilities': ['commands'],
                                'source_url': 'https://github.com/example/tools',
                                'license': 'MIT',
                                'package': 'example-tools',
                                'sha256': PluginManager._content_digest(package),
                            }
                        ],
                    }
                ),
                encoding='utf-8',
            )
            with patch('tools.plugin_release.PACKAGE_ROOT', package_root):
                archive_path, catalog_path = build_release('dylmarriner/cat', 'plugin-example-tools-v1.2.3', root / 'release')
            with zipfile.ZipFile(archive_path) as archive:
                self.assertEqual(archive.read('LICENSE'), b'Example MIT license text\n')
            entry = json.loads(catalog_path.read_text(encoding='utf-8'))['plugins'][0]
            self.assertEqual(entry['id'], 'example-tools')
            self.assertEqual(entry['license'], 'MIT')

    def test_catalog_merge_preserves_plugins_replaces_versions_and_rejects_downgrades(self) -> None:
        old_scroll = {
            'id': 'smart-scroll',
            'name': 'Smart scroll',
            'version': '0.9.0',
            'release_url': 'https://example.org/old.zip',
            'archive_sha256': '0' * 64,
        }
        other = {'id': 'other-plugin', 'name': 'Other', 'version': '2.0.0', 'release_url': 'https://example.org/other.zip', 'archive_sha256': '1' * 64}
        release = {
            'id': 'smart-scroll',
            'name': 'Smart scroll',
            'version': '1.0.0',
            'release_url': 'https://example.org/new.zip',
            'archive_sha256': '2' * 64,
        }
        old_catalog = json.dumps({'schema_version': 1, 'plugins': [old_scroll, other]}).encode()
        new_catalog = json.dumps({'schema_version': 1, 'plugins': [release]}).encode()
        merged = json.loads(merge_catalogs(old_catalog, new_catalog))
        self.assertEqual([x['id'] for x in merged['plugins']], ['other-plugin', 'smart-scroll'])
        self.assertEqual(merged['plugins'][1]['version'], '1.0.0')
        with self.assertRaisesRegex(ValueError, 'would downgrade'):
            merge_catalogs(json.dumps({'schema_version': 1, 'plugins': [{**old_scroll, 'version': '2.0.0'}]}).encode(), new_catalog)
        with self.assertRaisesRegex(ValueError, 'conflicts with the published archive digest'):
            merge_catalogs(json.dumps({'schema_version': 1, 'plugins': [{**release, 'archive_sha256': '3' * 64}]}).encode(), new_catalog)
