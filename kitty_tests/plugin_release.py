#!/usr/bin/env python

import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from kitty.plugins import PluginManager
from tools.plugin_release import build_release


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
