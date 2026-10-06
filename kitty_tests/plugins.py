#!/usr/bin/env python
# License: GPL v3 Copyright: 2026, Kovid Goyal <kovid at kovidgoyal.net>

import io
import json
import os
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path
from threading import Event, get_ident
from unittest.mock import patch
from urllib.request import Request

from kitty.plugins import PluginError, PluginEvent, PluginManager, PluginManifest, _HTTPSRedirectHandler
from tools.package_utils import package_source_ignore

ALL_CAPABILITIES = frozenset(
    {'commands', 'events', 'settings', 'key_mappings', 'ui', 'terminal', 'screen', 'scroll', 'clipboard', 'window', 'tabs', 'launch', 'url'}
)


class TestPlugins(unittest.TestCase):
    def test_default_catalog_points_to_published_cat_index(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            manager = PluginManager(td)
            self.assertEqual(manager.catalog_url(), 'https://raw.githubusercontent.com/dylmarriner/cat/plugin-catalog/catalog.json')

    def test_boss_plugin_chooser_returns_selected_value(self) -> None:
        from kitty.boss import Boss

        class FakeBoss:
            def choose_entry(self, title, entries, callback):
                self.args = title, list(entries)
                self.callback = callback

        fake, results = FakeBoss(), []
        Boss._choose_plugin_entry(fake, 1, 'Pick', (('7', 'work'), ('9', 'play')), results.append)  # type: ignore[arg-type]
        self.assertEqual(fake.args, ('Pick', [('7', 'work'), ('9', 'play')]))
        fake.callback('9')
        fake.callback(None)
        self.assertEqual(results, ['9', ''])

    def test_https_redirect_handler_rejects_insecure_targets_before_following(self) -> None:
        handler = _HTTPSRedirectHandler()
        request = Request('https://example.org/catalog.json')
        with self.assertRaisesRegex(PluginError, 'insecure URL'):
            handler.redirect_request(request, io.BytesIO(), 302, 'Found', {}, 'http://127.0.0.1/internal')
        redirected = handler.redirect_request(request, io.BytesIO(), 302, 'Found', {}, 'https://cdn.example.org/catalog.json')
        self.assertIsNotNone(redirected)

    def test_source_package_filter_handles_kittens_tree(self) -> None:
        root = Path(__file__).resolve().parents[1]
        self.assertEqual(
            package_source_ignore(str(root / 'kittens'), ['main.py', 'README.rst', 'LICENSE']),
            ['README.rst'],
        )

    def test_catalog_network_work_runs_off_the_ui_thread(self) -> None:
        from kitty.boss import Boss

        boss = Boss.__new__(Boss)
        boss.shutting_down = False
        scheduled = []
        worker_started, release_worker, callback_finished = Event(), Event(), Event()
        result: list[tuple[Exception | None, int, int]] = []
        ui_thread = get_ident()

        def timer(callback, interval, repeats):
            scheduled.append(callback)
            return 7

        def download() -> int:
            worker_started.set()
            release_worker.wait(2)
            return get_ident()

        def finished(error: Exception | None, worker_thread: int) -> None:
            result.append((error, worker_thread, get_ident()))
            callback_finished.set()

        with patch('kitty.boss.add_timer', side_effect=timer), patch('kitty.boss.remove_timer') as remove_timer:
            boss._run_plugin_network_task(download, finished)
            self.assertTrue(worker_started.wait(1))
            self.assertEqual(result, [])
            release_worker.set()
            for _ in range(100):
                scheduled[0](7)
                if callback_finished.wait(0.01):
                    break

        self.assertTrue(callback_finished.is_set())
        self.assertEqual(result[0][0], None)
        self.assertNotEqual(result[0][1], ui_thread)
        self.assertEqual(result[0][2], ui_thread)
        remove_timer.assert_called_once_with(7)

    def test_source_package_includes_plugin_manifests_and_catalog_data(self) -> None:
        root = Path(__file__).resolve().parents[1] / 'kitty'
        with tempfile.TemporaryDirectory() as td:
            package_dir = Path(td) / 'plugin_packages'
            shutil.copytree(root / 'plugin_packages', package_dir, ignore=package_source_ignore)
            self.assertTrue((package_dir / 'catalog.json').is_file())
            self.assertTrue((package_dir / 'smart-scroll' / 'plugin.json').is_file())
            self.assertTrue((package_dir / 'smart-scroll' / 'README.rst').is_file())
            self.assertTrue((package_dir / 'smart-scroll' / 'LICENSE').is_file())
            with patch.object(PluginManager, 'bundled_plugins_directory', return_value=package_dir):
                ids = tuple(x['id'] for x in PluginManager(td).bundled_plugins())
                self.assertEqual(len(ids), 28)
                self.assertEqual(ids, tuple(sorted(x.name for x in package_dir.iterdir() if x.is_dir())))

    @staticmethod
    def enable_plugin(manager: PluginManager, grants: frozenset[str], plugin_id: str = 'sample-plugin') -> None:
        digest = manager.plugin_info(plugin_id)['content_digest']
        manager.enable(plugin_id, grants, confirmed=True, expected_digest=digest)

    def create_plugin(self, parent: str, *, api_versions: list[int] | None = None, capabilities: list[str] | None = None) -> str:
        directory = os.path.join(parent, 'sample-plugin')
        os.mkdir(directory)
        with open(os.path.join(directory, 'plugin.json'), 'w', encoding='utf-8') as f:
            json.dump(
                {
                    'id': 'sample-plugin',
                    'name': 'Sample Plugin',
                    'version': '1.2.3',
                    'api_versions': api_versions or [1],
                    'entry_point': 'main.py',
                    'capabilities': capabilities or sorted(ALL_CAPABILITIES),
                    'settings': [
                        {
                            'id': 'general',
                            'title': 'General',
                            'fields': [
                                {'key': 'name', 'label': 'Name', 'type': 'string'},
                                {'key': 'retries', 'label': 'Retries', 'type': 'integer', 'default': 3},
                                {'key': 'scale', 'label': 'Scale', 'type': 'float', 'default': 0.5},
                                {'key': 'enabled', 'label': 'Enabled', 'type': 'boolean', 'default': False},
                                {'key': 'mode', 'label': 'Mode', 'type': 'choice', 'choices': ['auto', 'manual'], 'default': 'auto'},
                            ],
                        }
                    ],
                },
                f,
            )
        with open(os.path.join(directory, 'main.py'), 'w', encoding='utf-8') as f:
            f.write("""
calls = []
def on_focus(event):
    calls.append((event.name, event.window_id))
def run(api, args):
    calls.append(tuple(args))
    if args == ('window-api',):
        calls.append(api.current_window_id)
        api.send_key('shift+up')
        api.scroll_window('scroll_page_up')
def cleanup():
    calls.append('cleanup')
def setup(api):
    api.register_command('hello', run, 'Say hello')
    api.register_settings_page('general', {'title': 'General', 'fields': [
        {'key': 'name', 'label': 'Name', 'type': 'string'},
        {'key': 'retries', 'label': 'Retries', 'type': 'integer', 'default': 3},
        {'key': 'scale', 'label': 'Scale', 'type': 'float', 'default': 0.5},
        {'key': 'enabled', 'label': 'Enabled', 'type': 'boolean', 'default': False},
        {'key': 'mode', 'label': 'Mode', 'type': 'choice', 'choices': ['auto', 'manual'], 'default': 'auto'},
    ]})
    api.add_key_mapping('ctrl+alt+h', 'hello', 'world')
    api.subscribe('window_focused', on_focus)
    api.contribute_ui('Say hello', 'hello')
    api.on_disable(cleanup)
""")
        return directory

    def test_manifest_and_plugin_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plugins_dir = os.path.join(td, 'plugins')
            os.mkdir(plugins_dir)
            directory = self.create_plugin(plugins_dir)
            manifest = PluginManifest.read(directory)
            self.assertEqual(manifest.plugin_id, 'sample-plugin')
            sent: list[tuple[int, str]] = []
            scrolled: list[tuple[int, str]] = []
            keys: list[tuple[int, tuple[str, ...]]] = []
            manager = PluginManager(
                td,
                screen_reader=lambda window_id: f'screen-{window_id}',
                terminal_writer=lambda window_id, text: sent.append((window_id, text)),
                scroll_handler=lambda window_id, action: scrolled.append((window_id, action)),
                key_writer=lambda window_id, key_names: keys.append((window_id, key_names)),
            )
            manager.load(directory, manifest.capabilities)
            manager.run_command('sample-plugin', 'hello', ('world',))
            context = manager.loaded['sample-plugin'].context
            self.assertIsNotNone(context)
            assert context is not None
            self.assertEqual(context.read_screen(42), 'screen-42')
            context.send_text(42, 'input')
            self.assertIsNone(context.current_window_id)
            manager.run_command('sample-plugin', 'hello', ('window-api',), window_id=42)
            self.assertIsNone(context.current_window_id)
            with self.assertRaisesRegex(PluginError, 'Unsupported plugin scroll action'):
                context.scroll_window('reset_config', 42)
            self.assertEqual(sent, [(42, 'input')])
            self.assertEqual(keys, [(42, ('shift+up',))])
            self.assertEqual(scrolled, [(42, 'scroll_page_up')])
            manager.emit(PluginEvent('window_focused', 42, 7, 'Terminal'))
            self.assertEqual(manager.commands()[0].name, 'hello')
            self.assertEqual(manager.settings_pages()[0]['title'], 'General')
            manager.update_settings(
                'sample-plugin',
                {
                    'general': {
                        'name': 'Kitty',
                        'retries': '5',
                        'scale': '0.75',
                        'enabled': 'true',
                        'mode': 'manual',
                    }
                },
            )
            current = {x['key']: x['current'] for x in manager.settings_pages()[0]['fields']}
            self.assertEqual(current, {'name': 'Kitty', 'retries': 5, 'scale': 0.75, 'enabled': True, 'mode': 'manual'})
            with self.assertRaisesRegex(PluginError, 'Invalid plugin setting general:retries'):
                manager.update_settings('sample-plugin', {'general': {'retries': 'five'}})
            self.assertEqual(manager.key_mappings()[0][1:], ('ctrl+alt+h', 'hello', ('world',)))
            self.assertEqual(manager.ui_contributions(), (('sample-plugin', 'Say hello', 'hello'),))
            self.assertEqual(manager.loaded['sample-plugin'].module.calls, [('world',), ('window-api',), 42, ('window_focused', 42)])
            loaded = manager.loaded['sample-plugin']
            manager.disable('sample-plugin')
            self.assertIn('cleanup', loaded.module.calls)
            self.assertEqual(manager.commands(), ())
            self.assertEqual(manager.loaded, {})

    def test_plugin_ui_and_terminal_integrations_validate_and_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plugins_dir = os.path.join(td, 'plugins')
            os.mkdir(plugins_dir)
            directory = self.create_plugin(plugins_dir, capabilities=sorted(ALL_CAPABILITIES))
            prompts = []
            choices = []
            opened_urls = []
            launched = []
            clipboard = ['copied']
            manager = PluginManager(
                td,
                prompt_handler=lambda window_id, title, initial, callback: prompts.append((window_id, title, initial, callback)),
                choice_handler=lambda window_id, title, entries, callback: choices.append((window_id, title, entries, callback)),
                clipboard_reader=lambda: clipboard[0],
                clipboard_writer=lambda value: clipboard.__setitem__(0, value),
                window_reader=lambda window_id: {'id': window_id, 'cwd': '/tmp'},
                tabs_reader=lambda window_id: ({'id': 7, 'title': 'work'},),
                tab_focuser=lambda window_id, tab_id: tab_id == 7,
                launcher=lambda window_id, command, cwd, title, _type, _env: launched.append((window_id, command, cwd, title)),
                url_opener=lambda window_id, url: opened_urls.append((window_id, url)),
            )
            manifest = PluginManifest.read(directory)
            manager.load(directory, manifest.capabilities)
            context = manager.loaded['sample-plugin'].context
            assert context is not None
            context._window_id = 42
            prompt_result, choice_result = [], []
            context.prompt('Find file', prompt_result.append, 'draft')
            context.choose('Pick tab', [('7', 'work')], choice_result.append)
            self.assertEqual((prompts[0][0], prompts[0][1], prompts[0][2]), (42, 'Find file', 'draft'))
            self.assertEqual((choices[0][0], choices[0][1], choices[0][2]), (42, 'Pick tab', (('7', 'work'),)))
            prompts[0][3]('report.txt')
            choices[0][3]('7')
            self.assertEqual(prompt_result, ['report.txt'])
            self.assertEqual(choice_result, ['7'])
            self.assertEqual(context.clipboard(), 'copied')
            self.assertEqual(context.clipboard('result'), 'result')
            self.assertEqual(context.window_info(), {'id': 42, 'cwd': '/tmp'})
            self.assertEqual(context.tabs(), ({'id': 7, 'title': 'work'},))
            context.focus_tab(7)
            context.launch(('git', 'status', ''), '/tmp', 'Git')
            self.assertEqual(launched, [(42, ('git', 'status', ''), '/tmp', 'Git')])
            context.open_url('https://example.org/help')
            self.assertEqual(opened_urls, [(42, 'https://example.org/help')])
            for url in ('http://example.org', 'https://user@example.org', 'https://example.org\n@127.0.0.1'):
                with self.subTest(url=url), self.assertRaises(PluginError):
                    context.open_url(url)
            with self.assertRaises(PluginError):
                context.launch(())
            manager.disable('sample-plugin')
            prompts[0][3]('after disable')
            self.assertEqual(prompt_result, ['report.txt'])

    def test_plugin_requires_explicit_capability_grants(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plugins_dir = os.path.join(td, 'plugins')
            os.mkdir(plugins_dir)
            directory = self.create_plugin(plugins_dir)
            with self.assertRaisesRegex(PluginError, 'ungranted capabilities'):
                PluginManager(td).load(directory, frozenset({'commands'}))

    def test_scroll_api_restricts_actions_and_requires_capability(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plugins_dir = os.path.join(td, 'plugins')
            os.mkdir(plugins_dir)
            directory = self.create_plugin(plugins_dir, capabilities=sorted(ALL_CAPABILITIES - {'scroll'}))
            manager = PluginManager(td, scroll_handler=lambda _window_id, _action: None)
            manifest = PluginManifest.read(directory)
            manager.load(directory, manifest.capabilities)
            context = manager.loaded['sample-plugin'].context
            assert context is not None
            with self.assertRaisesRegex(PluginError, "did not request 'scroll'"):
                context.scroll_window('scroll_home', 42)

    def test_smart_scroll_port_handles_both_screen_modes(self) -> None:
        source = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'kitty', 'plugin_packages', 'smart-scroll')
        with tempfile.TemporaryDirectory() as td:
            plugins_dir = os.path.join(td, 'plugins')
            os.mkdir(plugins_dir)
            shutil.copytree(source, os.path.join(plugins_dir, 'smart-scroll'))
            actions: list[tuple[int, str]] = []
            keys: list[tuple[int, tuple[str, ...]]] = []
            alternate_screen = False
            manager = PluginManager(
                td,
                scroll_handler=lambda window_id, action: (actions.append((window_id, action)), alternate_screen)[1],
                key_writer=lambda window_id, key_names: keys.append((window_id, key_names)),
            )
            self.enable_plugin(manager, frozenset({'commands', 'key_mappings', 'scroll', 'terminal'}), 'smart-scroll')
            self.assertEqual(len(manager.key_mappings()), 6)
            manager.run_command('smart-scroll', 'smart_scroll', ('scroll_line_up', 'ctrl+alt+up'), window_id=19)
            self.assertEqual(actions, [(19, 'scroll_line_up')])
            self.assertEqual(keys, [])
            alternate_screen = True
            manager.run_command('smart-scroll', 'smart_scroll', ('scroll_page_down', 'ctrl+alt+page_down'), window_id=19)
            self.assertEqual(actions[-1], (19, 'scroll_page_down'))
            self.assertEqual(keys, [(19, ('ctrl+alt+page_down',))])

    def test_tab_switcher_uses_native_tab_api_and_chooser(self) -> None:
        source = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'kitty', 'plugin_packages', 'tab-switcher')
        with tempfile.TemporaryDirectory() as td:
            plugins_dir = os.path.join(td, 'plugins')
            os.mkdir(plugins_dir)
            shutil.copytree(source, os.path.join(plugins_dir, 'tab-switcher'))
            chooser = []
            focused = []
            manager = PluginManager(
                td,
                tabs_reader=lambda _window_id: ({'id': 12, 'title': 'api', 'is_active': False},),
                tab_focuser=lambda _window_id, tab_id: (focused.append(tab_id), True)[1],
                choice_handler=lambda window_id, title, entries, callback: chooser.append((window_id, title, entries, callback)),
            )
            manifest = PluginManifest.read(os.path.join(plugins_dir, 'tab-switcher'))
            manager.load(os.path.join(plugins_dir, 'tab-switcher'), manifest.capabilities)
            manager.run_command('tab-switcher', 'switch', (), window_id=42)
            self.assertEqual(chooser[0][:3], (42, 'Switch tab', (('12', 'api'),)))
            chooser[0][3]('12')
            self.assertEqual(focused, [12], manager.errors)

    def test_worktree_switcher_parses_paths_and_launches_without_shell_interpolation(self) -> None:
        source = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'kitty', 'plugin_packages', 'worktree-switcher')
        with tempfile.TemporaryDirectory() as td:
            plugins_dir = os.path.join(td, 'plugins')
            os.mkdir(plugins_dir)
            shutil.copytree(source, os.path.join(plugins_dir, 'worktree-switcher'))
            chooser = []
            launches = []
            manager = PluginManager(
                td,
                window_reader=lambda window_id: {'id': window_id, 'cwd': '/tmp/project'},
                launcher=lambda window_id, command, cwd, title, _type, _env: launches.append((window_id, command, cwd, title)),
                choice_handler=lambda window_id, title, entries, callback: chooser.append((entries, callback)),
            )
            package = os.path.join(plugins_dir, 'worktree-switcher')
            manifest = PluginManifest.read(package)
            manager.load(package, manifest.capabilities)
            module = manager.loaded['worktree-switcher'].module
            output = 'worktree /tmp/project\0HEAD abc\0branch refs/heads/main\0\0worktree /tmp/feature;touch pwned\0HEAD def\0branch refs/heads/feature\0\0'
            with patch.object(module.subprocess, 'run', return_value=type('Result', (), {'stdout': output})()) as run:
                manager.run_command('worktree-switcher', 'switch', (), window_id=42)
            run.assert_called_once_with(
                ['git', '-C', '/tmp/project', 'worktree', 'list', '--porcelain', '-z'],
                capture_output=True,
                check=True,
                text=True,
                timeout=5,
            )
            self.assertEqual(chooser[0][0][1], ('/tmp/feature;touch pwned', 'feature — /tmp/feature;touch pwned'))
            chooser[0][1]('/tmp/feature;touch pwned')
            self.assertEqual(launches, [(42, (os.environ.get('SHELL') or os.environ.get('COMSPEC') or '/bin/sh',), '/tmp/feature;touch pwned', 'feature')])

    def test_bundled_plugin_install_is_atomic_and_does_not_execute_code(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            manager = PluginManager(td)
            catalog = manager.bundled_plugins()
            self.assertEqual(len(catalog), 28)
            smart_scroll = next(x for x in catalog if x['id'] == 'smart-scroll')
            self.assertEqual(smart_scroll['source_url'], 'https://github.com/yurikhan/kitty-smart-scroll')
            self.assertEqual(smart_scroll['license'], 'GPL-3.0-or-later')
            installed = manager.install_bundled_plugin('smart-scroll')
            self.assertTrue(installed['approval_required'])
            self.assertEqual(manager.loaded, {})
            self.assertEqual(tuple(x['id'] for x in manager.available_plugins()), ('smart-scroll',))
            with self.assertRaisesRegex(PluginError, 'already installed'):
                manager.install_bundled_plugin('smart-scroll')

    def test_bundled_catalog_rejects_modified_package_files(self) -> None:
        source = PluginManager.bundled_plugins_directory()
        with tempfile.TemporaryDirectory() as td:
            shutil.copytree(source / 'smart-scroll', Path(td) / 'smart-scroll')
            shutil.copy2(source / 'catalog.json', Path(td) / 'catalog.json')
            with patch.object(PluginManager, 'bundled_plugins_directory', return_value=Path(td)):
                manager = PluginManager(Path(td) / 'config')
                self.assertEqual(len(manager.bundled_plugins()), 1)
                with open(Path(td) / 'smart-scroll' / 'main.py', 'a', encoding='utf-8') as f:
                    f.write('\n# changed after catalog digest\n')
                self.assertEqual(manager.bundled_plugins(), ())
                self.assertIn('digest does not match', manager.errors['smart-scroll'])

    def test_remote_catalog_installs_only_the_pinned_compatible_release(self) -> None:
        plugin_id = 'remote-sample'
        manifest = {
            'id': plugin_id,
            'name': 'Remote sample',
            'version': '1.0.0',
            'api_versions': [1],
            'entry_point': 'main.py',
            'capabilities': ['commands'],
            'source_url': 'https://example.org/remote-sample',
            'license': 'MIT',
            'settings': [],
        }
        source = b'def run(api, args):\n    api.config_directory\n\ndef setup(api):\n    api.register_command("hello", run, "Say hello")\n'
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, 'w') as zf:
            zf.writestr(f'{plugin_id}/plugin.json', json.dumps(manifest))
            zf.writestr(f'{plugin_id}/main.py', source)
        archive_data = archive.getvalue()
        import hashlib

        archive_sha256 = hashlib.sha256(archive_data).hexdigest()
        catalog = json.dumps(
            {
                'schema_version': 1,
                'plugins': [
                    {
                        **{k: manifest[k] for k in ('id', 'name', 'version', 'api_versions', 'capabilities', 'source_url', 'license')},
                        'description': 'A test package.',
                        'release_url': 'https://example.org/releases/remote-sample.zip',
                        'archive_sha256': archive_sha256,
                    }
                ],
            }
        ).encode()

        class Response(io.BytesIO):
            def __init__(self, data: bytes, url: str):
                super().__init__(data)
                self.url = url
                self.headers = {'Content-Length': str(len(data))}

            def geturl(self) -> str:
                return self.url

        with tempfile.TemporaryDirectory() as td:
            manager = PluginManager(td)
            manager.set_catalog_url('https://example.org/catalog.json')
            responses = [
                Response(catalog, 'https://example.org/catalog.json'),
                Response(archive_data + b'tampered', 'https://example.org/releases/remote-sample.zip'),
                Response(archive_data, 'https://example.org/releases/remote-sample.zip'),
            ]
            with patch('kitty.plugins._open_https_url', side_effect=responses):
                self.assertTrue(manager.fetch_remote_catalog()[0]['compatible'])
                with self.assertRaisesRegex(PluginError, 'changed after the installation review'):
                    manager.install_remote_plugin(plugin_id, '0' * 64)
                with self.assertRaisesRegex(PluginError, 'archive SHA-256'):
                    manager.install_remote_plugin(plugin_id, archive_sha256)
                self.assertFalse(os.path.exists(os.path.join(td, 'plugins', plugin_id)))
                installed = manager.install_remote_plugin(plugin_id, archive_sha256)
            self.assertFalse(installed['enabled'])
            self.assertEqual(manager.loaded, {})
            manager.enable(plugin_id, frozenset({'commands'}), confirmed=True, expected_digest=installed['content_digest'])
            manager.run_command(plugin_id, 'hello', ())

    def test_remote_update_keeps_old_files_when_registry_commit_fails(self) -> None:
        plugin_id = 'remote-sample'

        def release(version: str) -> tuple[dict[str, object], bytes, str]:
            manifest: dict[str, object] = {
                'id': plugin_id,
                'name': 'Remote sample',
                'version': version,
                'api_versions': [1],
                'entry_point': 'main.py',
                'capabilities': ['commands'],
                'source_url': 'https://example.org/remote-sample',
                'license': 'MIT',
                'settings': [],
            }
            archive = io.BytesIO()
            with zipfile.ZipFile(archive, 'w') as zf:
                zf.writestr(f'{plugin_id}/plugin.json', json.dumps(manifest))
                zf.writestr(f'{plugin_id}/main.py', 'def setup(api):\n    pass\n')
            data = archive.getvalue()
            import hashlib

            digest = hashlib.sha256(data).hexdigest()
            entry: dict[str, object] = {
                **{k: manifest[k] for k in ('id', 'name', 'version', 'api_versions', 'capabilities', 'source_url', 'license')},
                'description': 'A test package.',
                'release_url': f'https://example.org/releases/{version}.zip',
                'archive_sha256': digest,
            }
            return entry, data, digest

        class Response(io.BytesIO):
            def __init__(self, data: bytes, url: str):
                super().__init__(data)
                self.url = url
                self.headers = {'Content-Length': str(len(data))}

            def geturl(self) -> str:
                return self.url

        with tempfile.TemporaryDirectory() as td:
            manager = PluginManager(td)
            catalog_url = 'https://example.org/catalog.json'
            manager.set_catalog_url(catalog_url)
            first, first_archive, first_digest = release('1.0.0')
            first_catalog = json.dumps({'schema_version': 1, 'plugins': [first]}).encode()
            with patch(
                'kitty.plugins._open_https_url',
                side_effect=[
                    Response(first_catalog, catalog_url),
                    Response(first_archive, str(first['release_url'])),
                ],
            ):
                manager.fetch_remote_catalog()
                installed = manager.install_remote_plugin(plugin_id, first_digest)
            manager.enable(plugin_id, frozenset({'commands'}), confirmed=True, expected_digest=installed['content_digest'])

            second, second_archive, second_digest = release('2.0.0')
            second_catalog = json.dumps({'schema_version': 1, 'plugins': [second]}).encode()
            manager.set_catalog_url(catalog_url)
            with (
                patch(
                    'kitty.plugins._open_https_url',
                    side_effect=[
                        Response(second_catalog, catalog_url),
                        Response(second_archive, str(second['release_url'])),
                    ],
                ),
                patch.object(manager, '_write_state', side_effect=OSError('simulated registry failure')),
            ):
                manager.fetch_remote_catalog()
                with self.assertRaisesRegex(OSError, 'simulated registry failure'):
                    manager.update_remote_plugin(plugin_id, second_digest)
            self.assertEqual(manager.plugin_info(plugin_id)['version'], '1.0.0')
            self.assertIn(plugin_id, manager.loaded)

            manager.set_catalog_url(catalog_url)
            with patch(
                'kitty.plugins._open_https_url',
                side_effect=[
                    Response(second_catalog, catalog_url),
                    Response(second_archive, str(second['release_url'])),
                ],
            ):
                manager.fetch_remote_catalog()
                updated = manager.update_remote_plugin(plugin_id, second_digest)
            self.assertEqual(updated['version'], '2.0.0')
            info = manager.plugin_info(plugin_id)
            self.assertFalse(info['enabled'])
            self.assertTrue(info['approval_required'])
            self.assertNotIn(plugin_id, manager.loaded)
            self.assertFalse(tuple((Path(td) / 'plugins').glob('.kitty-plugin-install-*')))

    def test_remote_archive_rejects_parent_paths(self) -> None:
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, 'w') as zf:
            zf.writestr('../plugin.json', '{}')
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(PluginError, 'unsafe archive path'):
                PluginManager._extract_plugin_archive(archive.getvalue(), Path(td))

    def test_uninstall_disables_and_removes_plugin_settings_and_registry(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plugins_dir = os.path.join(td, 'plugins')
            os.mkdir(plugins_dir)
            self.create_plugin(plugins_dir)
            manager = PluginManager(td)
            self.enable_plugin(manager, ALL_CAPABILITIES)
            loaded = manager.loaded['sample-plugin']
            manager.update_settings('sample-plugin', {'general': {'name': 'keep no data'}})
            manager.uninstall_plugin('sample-plugin')
            self.assertIn('cleanup', loaded.module.calls)
            self.assertEqual(manager.loaded, {})
            self.assertFalse(os.path.exists(os.path.join(plugins_dir, 'sample-plugin')))
            self.assertFalse(os.path.exists(os.path.join(plugins_dir, 'settings', 'sample-plugin.json')))
            with open(os.path.join(plugins_dir, 'plugins.json'), encoding='utf-8') as f:
                self.assertNotIn('sample-plugin', json.load(f)['plugins'])

    def test_incompatible_api_version_is_rejected_before_import(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plugins_dir = os.path.join(td, 'plugins')
            os.mkdir(plugins_dir)
            directory = self.create_plugin(plugins_dir, api_versions=[99])
            manager = PluginManager(td)
            with self.assertRaisesRegex(PluginError, 'supports API versions'):
                manager.load(directory, ALL_CAPABILITIES)
            self.assertEqual(manager.loaded, {})

    def test_enabled_registry_loads_only_explicitly_enabled_plugins(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plugins_dir = os.path.join(td, 'plugins')
            os.mkdir(plugins_dir)
            self.create_plugin(plugins_dir)
            grants = sorted(ALL_CAPABILITIES)
            manager = PluginManager(td)
            self.enable_plugin(manager, frozenset(grants))
            manager = PluginManager(td)
            manager.load_enabled()
            self.assertIn('sample-plugin', manager.loaded)
            manager.disable_plugin('sample-plugin')
            manager = PluginManager(td)
            manager.load_enabled()
            self.assertEqual(manager.loaded, {})

    def test_enable_requires_confirmation_and_persists_disable(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plugins_dir = os.path.join(td, 'plugins')
            os.mkdir(plugins_dir)
            self.create_plugin(plugins_dir)
            grants = ALL_CAPABILITIES
            manager = PluginManager(td)
            with self.assertRaisesRegex(PluginError, 'explicit code-execution confirmation'):
                manager.enable('sample-plugin', grants)
            self.assertEqual(manager.loaded, {})
            self.enable_plugin(manager, grants)
            self.assertIn('sample-plugin', manager.loaded)
            manager.disable_plugin('sample-plugin')
            with open(os.path.join(plugins_dir, 'plugins.json'), encoding='utf-8') as f:
                state = json.load(f)
            self.assertFalse(state['plugins']['sample-plugin']['enabled'])
            self.assertEqual(manager.loaded, {})

    def test_changed_source_requires_reconfirmation_and_does_not_execute(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plugins_dir = os.path.join(td, 'plugins')
            os.mkdir(plugins_dir)
            directory = self.create_plugin(plugins_dir)
            grants = ALL_CAPABILITIES
            manager = PluginManager(td)
            self.enable_plugin(manager, grants)
            approved_digest = manager.plugin_info('sample-plugin')['content_digest']
            with open(os.path.join(directory, 'main.py'), 'a', encoding='utf-8') as f:
                f.write('\nexecuted_after_update = True\n')
            manager = PluginManager(td)
            with self.assertRaisesRegex(PluginError, 'changed during approval'):
                manager.enable('sample-plugin', grants, confirmed=True, expected_digest=approved_digest)
            manager.load_enabled()
            self.assertEqual(manager.loaded, {})
            self.assertIn('changed since approval', manager.errors['sample-plugin'])

    def test_new_standalone_bytecode_requires_reconfirmation(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plugins_dir = os.path.join(td, 'plugins')
            os.mkdir(plugins_dir)
            directory = self.create_plugin(plugins_dir)
            manager = PluginManager(td)
            self.enable_plugin(manager, ALL_CAPABILITIES)
            with open(os.path.join(directory, 'payload.pyc'), 'wb') as f:
                f.write(b'code that was not part of the approval')
            manager = PluginManager(td)
            manager.load_enabled()
            self.assertEqual(manager.loaded, {})
            self.assertIn('changed since approval', manager.errors['sample-plugin'])
