#!/usr/bin/env python
# License: GPL v3 Copyright: 2026, Kovid Goyal <kovid at kovidgoyal.net>

import base64
import fcntl
import json
import os
import pty
import select
import signal
import struct
import tempfile
import termios
import time
import unittest
from unittest.mock import patch

from kitty.settings import BEGIN_MARKER, END_MARKER, revert_settings, save_settings, settings_metadata, settings_ui_data


class TestSettings(unittest.TestCase):
    @unittest.skipUnless(os.name == 'posix', 'The settings kitten TUI requires a POSIX pseudo-terminal')
    def test_overlay_adjusts_and_serializes_save_result(self) -> None:
        from kitty.constants import kitten_exe

        metadata_read, metadata_write = os.pipe()
        pid, terminal = pty.fork()
        if pid == 0:
            os.close(metadata_write)
            os.dup2(metadata_read, 0)
            if metadata_read != 0:
                os.close(metadata_read)
            os.environ['TERM'] = 'xterm-kitty'
            os.environ['KITTEN_RUNNING_AS_UI'] = '1'
            executable = kitten_exe()
            os.execv(executable, [executable, 'settings'])

        os.close(metadata_read)
        status = None
        try:
            fcntl.ioctl(terminal, termios.TIOCSWINSZ, struct.pack('HHHH', 32, 100, 0, 0))
            data = {
                'settings': [
                    {
                        'name': 'font_size',
                        'group': ['Fonts'],
                        'type': 'double',
                        'value_type': 'to_font_size',
                        'default': '11.0',
                        'current': ['12.0'],
                        'source': '/tmp/kitty.conf',
                        'help': 'Font size',
                        'choices': [],
                        'restart_required': False,
                        'multiple': False,
                    }
                ],
                'source_files': ['/tmp/kitty.conf'],
            }
            os.write(metadata_write, json.dumps(data).encode())
            os.close(metadata_write)
            metadata_write = -1

            output = bytearray()
            deadline = time.monotonic() + 6
            sent_plus = sent_save = sent_da1 = False
            terminal_open = True
            result = None
            while time.monotonic() < deadline:
                ready, _, _ = select.select([terminal] if terminal_open else [], [], [], 0.1)
                if ready:
                    try:
                        output.extend(os.read(terminal, 65536))
                    except OSError:
                        terminal_open = False
                    else:
                        if b'Kitty Settings' in output and not sent_plus:
                            os.write(terminal, b'\x1b[43u')
                            sent_plus = True
                        if b'12.1' in output and not sent_save:
                            os.write(terminal, b'\x1b[115;5u')
                            sent_save = True
                        if b'\x1b[c' in output and not sent_da1:
                            os.write(terminal, b'\x1b[?1;2c')
                            sent_da1 = True
                        start = output.rfind(b'@kitty-kitten-result|')
                        if start >= 0:
                            start += len(b'@kitty-kitten-result|')
                            end = output.find(b'\x1b\\', start)
                            if end >= 0:
                                result = json.loads(base64.b85decode(output[start:end]))
                child, child_status = os.waitpid(pid, os.WNOHANG)
                if child:
                    status = child_status
                    break

            self.assertTrue(sent_plus, 'settings overlay did not render its title')
            self.assertTrue(sent_save, 'settings overlay did not apply the numeric adjustment')
            self.assertIn(b'12.0', output)
            self.assertIn(b'12.1', output)
            self.assertIn(b'Type: double', output)
            self.assertIn(b'Source: /tmp/kitty.conf', output)
            self.assertIn(b'Font size', output)
            self.assertEqual(result, {'action': 'save', 'changes': {'font_size': '12.1'}})
            if status is None:
                self.fail('settings overlay did not exit after saving')
            self.assertTrue(os.WIFEXITED(status))
            self.assertEqual(os.WEXITSTATUS(status), 0)
        finally:
            if metadata_write >= 0:
                os.close(metadata_write)
            if status is None:
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                os.waitpid(pid, 0)
            os.close(terminal)

    def test_settings_metadata_comes_from_option_definition(self) -> None:
        items = settings_metadata()
        by_name = {x['name']: x for x in items}
        self.assertEqual(by_name['font_size']['default'], '11.0')
        self.assertEqual(by_name['font_size']['value_type'], 'to_font_size')
        self.assertTrue(by_name['symbol_map']['multiple'])
        self.assertTrue(by_name['font_size']['group'])
        self.assertEqual(by_name['mouse_hide_wait']['platform_defaults']['macos'], '0.0')

    def test_settings_metadata_uses_the_active_platform_default(self) -> None:
        with patch('kitty.settings.is_macos', True):
            by_name = {x['name']: x for x in settings_metadata()}
        self.assertEqual(by_name['mouse_hide_wait']['default'], '0.0')

    def test_settings_metadata_includes_every_option(self) -> None:
        from kitty.options.definition import definition

        names = {item['name'] for item in settings_metadata()}
        self.assertEqual(names, set(definition.option_map) | set(definition.multi_option_map))
        self.assertEqual(names - set(definition.option_map), set(definition.multi_option_map))
        self.assertIn('color16', names)
        self.assertIn('color255', names)

    def test_save_settings_preserves_user_config_and_replaces_owned_block(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, 'kitty.conf')
            with open(path, 'w', encoding='utf-8') as f:
                f.write('background #123456\n# before\n')
                f.write(f'{BEGIN_MARKER}\nfont_size 12\n{END_MARKER}\n# after\n')
            save_settings(path, {'font_size': '12.5', 'symbol_map': ('U+E000 SomeFont',)})
            save_settings(path, {'font_size': '13'})
            with open(path, encoding='utf-8') as f:
                saved = f.read()
            self.assertEqual(saved.count(BEGIN_MARKER), saved.count(END_MARKER))
            self.assertEqual(saved.count(BEGIN_MARKER), 1)
            self.assertIn('background #123456', saved)
            self.assertIn('# before\n', saved)
            self.assertIn('# after\n', saved)
            self.assertIn('font_size 13', saved)
            self.assertNotIn('font_size 12.5', saved)
            self.assertIn('symbol_map U+E000 SomeFont', saved)

    def test_saved_settings_reload_and_revert_through_kitty_config_loader(self) -> None:
        from kitty.config import load_config

        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, 'kitty.conf')
            with open(path, 'w', encoding='utf-8') as f:
                f.write('background #123456\n')
            save_settings(path, {'font_size': '12.5'})

            with patch('kitty.config.effective_config_lines', []), patch('kitty.config.effective_config_sources', {}):
                loaded = load_config(path)
                self.assertEqual(loaded.font_size, 12.5)
                data = settings_ui_data(loaded.config_paths)
                by_name = {item['name']: item for item in data['settings']}
                self.assertEqual(by_name['font_size']['current'], ['12.5'])
                self.assertEqual(by_name['font_size']['source'], path)

                self.assertTrue(revert_settings(path))
                reverted = load_config(path)
                self.assertEqual(reverted.font_size, 11.0)
                from kitty.rgb import to_color

                self.assertEqual(reverted.background, to_color('#123456'))

    def test_invalid_settings_do_not_overwrite_file(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, 'kitty.conf')
            original = 'background #123456\n'
            with open(path, 'w', encoding='utf-8') as f:
                f.write(original)
            with self.assertRaises(ValueError):
                save_settings(path, {'font_size': 'not-a-number'})
            with open(path, encoding='utf-8') as f:
                self.assertEqual(f.read(), original)

    def test_empty_values_remove_overrides_without_emitting_bare_directives(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, 'kitty.conf')
            save_settings(path, {'url_excluded_characters': 'letters', 'symbol_map': ('U+E000 Font',)})
            save_settings(path, {'url_excluded_characters': '', 'symbol_map': ()})
            with open(path, encoding='utf-8') as f:
                saved = f.read()
            self.assertNotIn('url_excluded_characters', saved)
            self.assertNotIn('symbol_map', saved)
            with self.assertRaisesRegex(ValueError, 'repeated values cannot be empty'):
                save_settings(path, {'symbol_map': ('',)})
            with open(path, encoding='utf-8') as f:
                self.assertEqual(f.read(), saved)

    def test_all_option_defaults_can_be_saved(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, 'kitty.conf')
            defaults = {item['name']: item['default'] for item in settings_metadata()}
            save_settings(path, defaults)
            with open(path, encoding='utf-8') as f:
                saved = f.read()
            self.assertNotIn('\nurl_excluded_characters\n', saved)
            self.assertNotIn('\nselect_by_word_characters_forward\n', saved)

    def test_settings_ui_data_uses_effective_values_and_sources(self) -> None:
        with patch('kitty.config.effective_config_lines', ['font_size 14', 'symbol_map U+E000 Font', 'symbol_map U+E001 Font']):
            data = settings_ui_data(('/config/kitty.conf',))
        by_name = {x['name']: x for x in data['settings']}
        self.assertEqual(by_name['font_size']['current'], ['14'])
        self.assertEqual(by_name['symbol_map']['current'], ['U+E000 Font', 'U+E001 Font'])
        self.assertEqual(data['source_files'], ('/config/kitty.conf',))

    def test_revert_removes_only_the_settings_block(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, 'kitty.conf')
            original = f'font_size 11\n{BEGIN_MARKER}\nfont_size 14\n{END_MARKER}\nbackground #123456\n'
            with open(path, 'w', encoding='utf-8') as f:
                f.write(original)
            self.assertTrue(revert_settings(path))
            with open(path, encoding='utf-8') as f:
                self.assertEqual(f.read(), 'font_size 11\nbackground #123456\n')
            self.assertFalse(revert_settings(path))
