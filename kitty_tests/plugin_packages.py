#!/usr/bin/env python
# License: GPL v3 Copyright: 2026, Kovid Goyal <kovid at kovidgoyal.net>

"""Behavior of the plugins bundled in kitty/plugin_packages, run against a fake host."""

import json
import os
import shutil
import sqlite3
import tempfile
import unittest
from collections import defaultdict
from pathlib import Path
from typing import Any

from kitty.plugins import PluginError, PluginEvent, PluginManager, PluginManifest

PACKAGES = PluginManager.bundled_plugins_directory()
NUM_BUNDLED = 28


class FakeHost:
    """Records every host call a plugin makes and lets tests drive timers and events."""

    def __init__(self, config_dir: str):
        self.calls: dict[str, list[Any]] = defaultdict(list)
        self.screen = ''
        self.clip = ''
        self.cwd = config_dir
        self.timers: dict[int, Any] = {}
        self.params: dict[int, tuple[float, ...]] = {}
        self.pipelines: tuple[str, ...] = ()
        self.visible: dict[int, bool] = {}
        self.next_window_id = 1000
        self.manager = PluginManager(
            config_dir,
            screen_reader=lambda window_id: self.screen,
            terminal_writer=lambda window_id, text: self.calls['text'].append((window_id, text)),
            key_writer=lambda window_id, keys: self.calls['keys'].append((window_id, keys)),
            prompt_handler=lambda window_id, title, initial, callback: self.calls['prompt'].append((title, callback)),
            choice_handler=lambda window_id, title, entries, callback: self.calls['choose'].append((title, entries, callback)),
            clipboard_reader=lambda: self.clip,
            clipboard_writer=lambda text: self.calls['clipboard'].append(text),
            window_reader=lambda window_id: {'id': window_id, 'title': 'shell', 'cwd': self.cwd, 'tab_id': 1, 'process': 'zsh'},
            tabs_reader=lambda window_id: (),
            tab_focuser=lambda window_id, tab_id: True,
            launcher=self.launch,
            url_opener=lambda window_id, url: self.calls['url'].append(url),
            notifier=lambda title, body: self.calls['notify'].append((title, body)),
            tab_title_setter=lambda window_id, title: self.calls['tab_title'].append((window_id, title)),
            color_setter=lambda window_id, colors: self.calls['colors'].append((window_id, colors)),
            opacity_setter=lambda window_id, opacity: self.calls['opacity'].append((window_id, opacity)),
            timer_adder=self.add_timer,
            timer_remover=lambda timer_id: self.timers.pop(timer_id, None),
            background_runner=self.run_now,
            shader_pipelines_setter=lambda paths: setattr(self, 'pipelines', paths),
            shader_param_setter=lambda index, values: self.params.__setitem__(index, values),
            shader_signal_firer=lambda channel: self.calls['signal'].append(channel),
            shader_visibility_setter=lambda channel, visible: self.visible.__setitem__(channel, visible),
        )
        self.plugins_dir = os.path.join(config_dir, 'plugins')
        shutil.copytree(PACKAGES, self.plugins_dir, ignore=shutil.ignore_patterns('catalog.json', '__pycache__'))

    def launch(self, window_id, command, cwd, title, launch_type, env):
        self.next_window_id += 1
        self.calls['launch'].append({'id': self.next_window_id, 'command': command, 'cwd': cwd, 'title': title, 'type': launch_type, 'env': env})
        return self.next_window_id

    def add_timer(self, callback, interval, repeat):
        timer_id = len(self.calls['timer_ids']) + 1
        self.calls['timer_ids'].append(timer_id)
        self.timers[timer_id] = (callback, interval, repeat)
        return timer_id

    def fire_timers(self) -> None:
        for timer_id, (callback, _, repeat) in tuple(self.timers.items()):
            if not repeat:
                self.timers.pop(timer_id, None)
            callback(timer_id)

    @staticmethod
    def run_now(task, done):
        try:
            value = task()
        except Exception as err:
            done(err, None)
        else:
            done(None, value)

    def load(self, *plugin_ids: str) -> None:
        for plugin_id in plugin_ids or sorted(os.listdir(self.plugins_dir)):
            package = os.path.join(self.plugins_dir, plugin_id)
            self.manager.load(package, PluginManifest.read(package).capabilities)

    def module(self, plugin_id: str) -> Any:
        if plugin_id not in self.manager.loaded:
            self.load(plugin_id)
        return self.manager.loaded[plugin_id].module

    def context(self, plugin_id: str) -> Any:
        self.module(plugin_id)
        return self.manager.loaded[plugin_id].context

    def wait_for(self, condition: Any, timeout: float = 10) -> None:
        import time

        end = time.monotonic() + timeout
        while not condition():
            if time.monotonic() > end:
                raise TimeoutError('condition not reached')
            self.fire_timers()
            time.sleep(0.01)

    def emit(self, name: str, window_id: int | None = 1, **kw: Any) -> None:
        self.manager.emit(PluginEvent(name, window_id, 1, 'shell', **kw))

    def run(self, plugin_id: str, command: str, *args: str, window_id: int = 1) -> None:
        self.module(plugin_id)
        self.manager.run_command(plugin_id, command, args, window_id=window_id)

    def channel(self, plugin_id: str) -> int:
        return next(c for c, e in self.manager._shader_effects.items() if e.plugin_id == plugin_id)


def load_script(path: Path) -> dict[str, Any]:
    """Execute an overlay app script without running its main loop."""
    source = path.read_text(encoding='utf-8').rstrip()
    assert source.endswith('main()'), path
    namespace: dict[str, Any] = {'__name__': 'plugin_app'}
    exec(compile(source[: -len('main()')], str(path), 'exec'), namespace)
    return namespace


class TestBundledPlugins(unittest.TestCase):
    def setUp(self) -> None:
        self.tdir = tempfile.mkdtemp()
        self.host = FakeHost(self.tdir)

    def tearDown(self) -> None:
        self.host.manager.shutdown()
        shutil.rmtree(self.tdir)

    def test_every_bundled_plugin_loads_and_cleans_up(self) -> None:
        h = self.host
        h.load()
        self.assertEqual(len(h.manager.loaded), NUM_BUNDLED, h.manager.errors)
        for loaded in h.manager.loaded.values():
            self.assertTrue(loaded.commands or loaded.cleanups or h.manager._callbacks, loaded.manifest.plugin_id)
            for _label, command in loaded.ui_contributions:
                self.assertIn(command, loaded.commands)
        self.assertEqual(len(h.pipelines), 9)
        for channel, path in enumerate(h.pipelines):
            text = Path(path).read_text()
            self.assertTrue(text.startswith(f'var int PLUGIN_CHANNEL = {channel}\n'))
            self.assertNotIn('@SIGNAL@', text)
            self.assertEqual(text.count('startgroup'), text.count(f'plugin_channel {channel}'))
            self.assertTrue(any(name.endswith('.slang') for name in os.listdir(os.path.dirname(path))))
        self.assertTrue(h.timers)
        h.manager.shutdown()
        self.assertEqual(h.pipelines, ())
        self.assertTrue(all(h.visible.values()), 'released channels must not stay hidden')
        self.assertEqual(h.timers, {})
        self.assertEqual(h.manager._shader_effects, {})

    def test_new_host_apis_require_their_capabilities(self) -> None:
        context = self.host.context('cmd-timer')
        for call in (
            lambda: context.set_colors({'background': '#000000'}),
            lambda: context.shader_effect('x.pipeline'),
            lambda: context.add_timer(lambda: None, 1),
            lambda: context.run_in_background(lambda: None),
            lambda: context.set_tab_title('x'),
        ):
            with self.assertRaisesRegex(PluginError, 'did not request'):
                call()
        self.assertEqual(context.settings(), {'timer': {'min_seconds': 10, 'notify_when_focused': False}})
        appearance = self.host.context('ssh-themes')
        with self.assertRaises(PluginError):
            appearance.set_colors({'background\nmalicious': '#000'}, window_id=1)

    def test_shader_effects_escape_package_paths(self) -> None:
        context = self.host.context('fail-glitch')
        for bad in ('../prod-guard/prod-guard.pipeline', '/etc/passwd.pipeline', 'main.py'):
            with self.assertRaises((PluginError, FileNotFoundError)):
                context.shader_effect(bad)

    def test_fail_glitch_scales_with_exit_code(self) -> None:
        h = self.host
        severity = h.module('fail-glitch').severity
        self.assertEqual((severity(0), severity(130), severity(1), severity(139)), (0.0, 0.35, 0.7, 1.0))
        channel = h.channel('fail-glitch')
        h.emit('command_finished', exit_code=0, cmdline='true')
        self.assertEqual(h.calls['signal'], [])
        h.emit('command_finished', exit_code=139, cmdline='./crash')
        self.assertEqual(h.calls['signal'], [channel])
        self.assertEqual(h.params[2 * channel][0], 1.0)

    def test_streak_fireworks_milestones_and_reset(self) -> None:
        h = self.host
        module = h.module('streak-fireworks')
        self.assertEqual([n for n in range(1, 301) if module.is_milestone(n)], [5, 10, 25, 50, 100, 200, 300])
        for _ in range(5):
            h.emit('command_finished', exit_code=0, cmdline='ls')
        self.assertEqual(len(h.calls['signal']), 1)
        self.assertIn('5 command streak', h.calls['notify'][0][0])
        h.emit('command_finished', exit_code=1, cmdline='false')
        h.run('streak-fireworks', 'status')
        self.assertEqual(h.calls['notify'][-1], ('Streak: 0', 'Best streak: 5'))

    def test_pomodoro_drives_its_shader_from_a_timer(self) -> None:
        h = self.host
        h.load('pomodoro-aura')
        channel = h.channel('pomodoro-aura')
        self.assertFalse(h.visible[channel])
        h.run('pomodoro-aura', 'start')
        self.assertTrue(h.visible[channel])
        self.assertEqual(h.params[2 * channel][0], 1.0)
        self.assertEqual(len(h.timers), 1)
        h.run('pomodoro-aura', 'skip')
        self.assertEqual(h.params[2 * channel][0], 2.0)
        self.assertIn('Focus session done', h.calls['notify'][0][0])
        h.run('pomodoro-aura', 'stop')
        self.assertEqual(h.params[2 * channel][0], 0.0)
        self.assertFalse(h.visible[channel])
        self.assertEqual(h.timers, {})

    def test_daylight_palette_is_continuous(self) -> None:
        h = self.host
        palette = h.module('daylight-themes').palette
        self.assertEqual(palette(0)['background'], '#0b1020')
        self.assertEqual(palette(24), palette(0))
        self.assertEqual(palette(13)['background'], '#20262e')
        for hour in range(0, 240):
            self.assertRegex(palette(hour / 10)['foreground'], r'^#[0-9a-f]{6}$')
        h.fire_timers()
        self.assertTrue(h.calls['colors'])
        self.assertIsNone(h.calls['colors'][-1][0])  # applied to all windows

    def test_prod_guard_marks_dangerous_windows(self) -> None:
        h = self.host
        h.load('prod-guard')
        channel = h.channel('prod-guard')
        self.assertFalse(h.visible[channel])
        h.emit('window_focused', 5)
        h.emit('command_started', 5, cmdline='ssh deploy@prod-db-1')
        self.assertTrue(h.visible[channel])
        self.assertEqual(h.calls['colors'][-1][0], 5)
        self.assertEqual(h.params[2 * channel][0], 1.0)
        h.emit('command_started', 6, cmdline='ssh staging-db')
        self.assertEqual(len(h.calls['colors']), 1)
        h.emit('command_finished', 5, cmdline='ssh deploy@prod-db-1', exit_code=0)
        self.assertEqual(h.calls['colors'][-1], (5, None))
        self.assertEqual(h.params[2 * channel][0], 0.0)
        self.assertFalse(h.visible[channel])

    def test_warp_and_heatwave_parameters(self) -> None:
        h = self.host
        h.load('warp-screensaver', 'load-heatwave')
        warp = h.channel('warp-screensaver')
        self.assertTrue(h.visible[warp])
        h.run('warp-screensaver', 'toggle')
        self.assertFalse(h.visible[warp])
        self.assertLessEqual(h.module('load-heatwave').load_ratio(), 1000)

    def test_git_mood_classifies_repository_state(self) -> None:
        classify = self.host.module('git-mood').classify
        self.assertEqual(classify('# branch.head main\n# branch.ab +0 -0\n'), 'clean')
        self.assertEqual(classify('# branch.head main\n1 .M N... 100644 100644 100644 a b x.py\n'), 'dirty')
        self.assertEqual(classify('# branch.head main\nu UU N... 1 2 3 4 a b c f.py\n1 .M x\n'), 'conflict')
        self.assertEqual(classify('# branch.head main\n# branch.ab +2 -0\n'), 'ahead')
        self.assertEqual(classify('# branch.head (detached)\n'), 'detached')

    def test_busy_orbit_tracks_running_commands(self) -> None:
        h = self.host
        h.load('busy-orbit')
        h.emit('window_focused', 1)
        h.emit('command_started', 1, cmdline='sleep 100')
        self.assertEqual(len(h.timers), 1)
        h.emit('command_finished', 1, cmdline='sleep 100', exit_code=0)
        self.assertEqual(h.timers, {})

    def test_cmd_timer_notifies_for_long_commands_elsewhere(self) -> None:
        h = self.host
        module = h.module('cmd-timer')
        self.assertEqual(module.human(3725), '1h 02m')
        h.emit('window_focused', 1)
        h.emit('command_finished', 2, cmdline='make -j8', exit_code=2, duration=95.0)
        h.emit('command_finished', 2, cmdline='ls', exit_code=0, duration=0.2)
        h.emit('command_finished', 1, cmdline='cargo build', exit_code=0, duration=60.0)
        self.assertEqual(h.calls['notify'], [('✘ Failed after 1m 35s (exit 2)', 'make -j8')])

    def test_auto_tab_titles(self) -> None:
        h = self.host
        running_title = h.module('auto-tab-titles').running_title
        self.assertEqual(running_title('sudo -E python3 manage.py runserver'), '🐍 python3 manage.py')
        self.assertEqual(running_title('ssh -A ops@bastion'), '🌐 bastion')
        self.assertEqual(running_title('FOO=1 cargo build --release'), '🦀 cargo build')
        h.emit('command_started', 3, cmdline='docker compose up')
        self.assertEqual(h.calls['tab_title'][-1], (3, '🐳 docker compose'))
        h.emit('command_finished', 3, cmdline='docker compose up', exit_code=0)
        h.wait_for(lambda: h.calls['tab_title'][-1][1].startswith('📁'))

    def test_ssh_themes(self) -> None:
        h = self.host
        module = h.module('ssh-themes')
        self.assertEqual(module.ssh_host('ssh -p 2222 -i ~/.ssh/key deploy@web1 uptime'), 'web1')
        self.assertEqual(module.ssh_host('kitten ssh box'), 'box')
        self.assertIsNone(module.ssh_host('sshfs a:b c'))
        self.assertEqual(module.theme('web1'), module.theme('web1'))
        self.assertNotEqual(module.theme('web1'), module.theme('web2'))
        h.emit('command_started', 4, cmdline='ssh web1')
        h.emit('window_closed', 4)
        self.assertEqual([c[0] for c in h.calls['colors']], [4, 4])
        self.assertIsNone(h.calls['colors'][-1][1])

    def test_command_stats_records_and_renders(self) -> None:
        h = self.host
        module = h.module('command-stats')
        self.assertEqual(module.program_of('FOO=1 sudo git push'), 'git')
        h.emit('command_finished', 1, cmdline='git push', exit_code=1, duration=2.5)
        h.emit('command_finished', 1, cmdline='ls', exit_code=0, duration=0.1)
        path = os.path.join(h.manager.plugins_directory, 'data', 'command-stats', 'commands.sqlite')
        dashboard = load_script(Path(h.plugins_dir) / 'command-stats' / 'dashboard.py')
        lines = '\n'.join(dashboard['render'](sqlite3.connect(path), 100))
        self.assertIn('2\x1b[0m commands', lines)
        self.assertIn('git push', lines)
        h.run('command-stats', 'dashboard')
        self.assertEqual(h.calls['launch'][-1]['type'], 'overlay')
        self.assertEqual(h.calls['launch'][-1]['command'][1:], ('+launch', os.path.join(h.plugins_dir, 'command-stats', 'dashboard.py'), path))

    def test_reopen_closed_restores_the_directory(self) -> None:
        h = self.host
        h.cwd = '/srv/app'
        h.emit('command_started', 3, cmdline='ls')
        h.module('reopen-closed')
        h.emit('command_started', 3, cmdline='ls')
        h.emit('window_closed', 3)
        h.run('reopen-closed', 'reopen')
        self.assertEqual(h.calls['launch'][-1]['cwd'], '/srv/app')

    def test_screen_watcher_notifies_on_new_matches(self) -> None:
        h = self.host
        h.screen = 'building...'
        h.run('screen-watcher', 'watch', window_id=2)
        h.calls['prompt'][-1][1]('error')
        h.fire_timers()
        self.assertEqual(h.calls['notify'], [])
        h.screen = 'building...\nERROR: boom'
        h.fire_timers()
        self.assertEqual(len(h.calls['notify']), 1)
        self.assertEqual(h.calls['signal'], [h.channel('screen-watcher')])
        h.fire_timers()
        self.assertEqual(len(h.calls['notify']), 1)

    def test_overlay_app_results_reach_the_plugin(self) -> None:
        h = self.host
        h.run('emoji-picker', 'pick', window_id=7)
        launched = h.calls['launch'][-1]
        self.assertEqual(launched['type'], 'overlay')
        with open(launched['env']['KITTY_PLUGIN_RESULT'], 'w', encoding='utf-8') as f:
            f.write('🔥')
        h.emit('window_closed', launched['id'])
        self.assertEqual(h.calls['text'], [(7, '🔥')])
        self.assertFalse(os.path.exists(launched['env']['KITTY_PLUGIN_RESULT']))
        h.emit('window_closed', launched['id'])
        self.assertEqual(len(h.calls['text']), 1)

    def test_overlay_app_logic(self) -> None:
        apps = Path(self.host.plugins_dir)
        picker = load_script(apps / 'emoji-picker' / 'picker.py')
        emoji = picker['all_emoji']()
        self.assertGreater(len(emoji), 1000)
        hits = picker['search'](emoji, [], 'fire')
        self.assertEqual(hits[0][0], '🔥')
        colors = load_script(apps / 'color-picker' / 'picker.py')
        self.assertEqual(colors['fmt']('hex', 0, 1, 0.5), '#ff0000')
        self.assertEqual(colors['fmt']('hsl', 0.5, 0.5, 0.5), 'hsl(180, 50%, 50%)')
        typing = load_script(apps / 'typing-test' / 'typing.py')
        wpm, accuracy = typing['stats']('hello world', 'hello world', 6.0)
        self.assertAlmostEqual(wpm, 22.0)
        self.assertEqual(accuracy, 100.0)
        pager = load_script(apps / 'ai-explain' / 'pager.py')
        lines, blocks = pager['render_markdown']('# Cause\nThe **file** is missing.\n```sh\ntouch x\n```\n', 60)
        self.assertEqual(blocks, ['touch x'])
        self.assertIn('Cause', '\n'.join(lines))
        for script in ('sysmon-hud/hud.py', 'git-dashboard/dashboard.py', 'snake/snake.py', 'file-peek/peek.py'):
            self.assertIn('main', load_script(apps / script))

    def test_ai_plugins_type_commands_without_running_them(self) -> None:
        h = self.host
        command = h.module('ai-command')
        self.assertEqual(command.single_command('```bash\n$ ls -la\necho two\n```'), 'ls -la')
        prompts = []
        command.ask_claude = lambda api, system, prompt, done, max_tokens=4000: prompts.append(prompt) or done(None, 'git reset --soft HEAD~1')
        h.run('ai-command', 'ask', window_id=3)
        h.calls['prompt'][-1][1]('undo my last commit')
        self.assertEqual(h.calls['text'], [(3, 'git reset --soft HEAD~1')])
        self.assertIn('Request: undo my last commit', prompts[0])
        self.assertEqual(h.calls['keys'], [])

        fix = h.module('ai-fix')
        h.run('ai-fix', 'fix', window_id=4)
        self.assertEqual(h.calls['notify'][-1][0], 'Nothing to fix')
        fix.ask_claude = lambda api, system, prompt, done, max_tokens=4000: done(None, 'git status')
        h.emit('command_finished', 4, cmdline='git stauts', exit_code=1)
        h.run('ai-fix', 'fix', window_id=4)
        self.assertEqual(h.calls['text'][-1], (4, 'git status'))

        explain = h.module('ai-explain')
        explain.ask_claude = lambda api, system, prompt, done, max_tokens=4000: done(None, '# Cause\nTypo')
        h.screen = 'git: stauts is not a git command'
        h.run('ai-explain', 'explain', window_id=4)
        self.assertTrue(h.calls['launch'][-1]['command'][2].endswith('pager.py'))
        answer = Path(h.calls['launch'][-1]['command'][3]).read_text()
        self.assertEqual(answer, '# Cause\nTypo')

    def test_ai_errors_are_reported_not_raised_into_kitty(self) -> None:
        h = self.host
        module = h.module('ai-command')

        def fail(api, system, prompt, done, max_tokens=4000):
            done(RuntimeError('no credentials'), None)

        module.ask_claude = fail
        h.run('ai-command', 'ask', window_id=3)
        h.calls['prompt'][-1][1]('anything')
        self.assertIn('no credentials', h.manager.errors['ai-command'])

    def test_reopen_closed_chooser_survives_list_changes(self) -> None:
        h = self.host
        h.load('reopen-closed')
        for window_id, cwd in ((1, '/a'), (2, '/b')):
            h.cwd = cwd
            h.emit('command_started', window_id, cmdline='ls')
            h.emit('window_closed', window_id)
        h.run('reopen-closed', 'choose')
        _title, entries, picked = h.calls['choose'][-1]
        target = next(value for value, label in entries if label.startswith('/a'))
        h.cwd = '/c'
        h.emit('command_started', 3, cmdline='ls')
        h.emit('window_closed', 3)
        picked(target)
        self.assertEqual(h.calls['launch'][-1]['cwd'], '/a')

    def test_failed_setup_releases_timers(self) -> None:
        h = self.host
        package = Path(h.plugins_dir) / 'cmd-timer'
        manifest = json.loads((package / 'plugin.json').read_text())
        manifest['capabilities'].append('timers')
        (package / 'plugin.json').write_text(json.dumps(manifest))
        (package / 'main.py').write_text('def setup(api):\n    api.add_timer(lambda: None, 1, repeat=True)\n    raise RuntimeError("boom")\n')
        with self.assertRaisesRegex(RuntimeError, 'boom'):
            h.load('cmd-timer')
        self.assertEqual(h.timers, {})

    def test_git_helpers_ignore_unreliable_exit_codes(self) -> None:
        # inside kitty every child is reaped by kitty, so subprocess reports 0 even for failures
        failed = type('Result', (), {'returncode': 0, 'stdout': '', 'stderr': 'fatal: not a git repository'})()
        titles, mood = self.host.module('auto-tab-titles'), self.host.module('git-mood')
        self.assertEqual(titles.idle_title('/tmp', failed.stdout), '📁 tmp')
        self.assertEqual(titles.idle_title('/x', '/srv/app\nmain\n'), 'app ⎇ main')
        self.assertIsNone(mood.mood_of(failed.stdout))
        self.assertEqual(mood.mood_of('# branch.oid abc\n# branch.head main\n'), 'clean')


class TestPluginShaderChannels(unittest.TestCase):
    def test_channel_events_and_parameters_are_bounded(self) -> None:
        from kitty.fast_data_types import fire_plugin_shader_signal, set_plugin_shader_channel_visible, set_plugin_shader_param
        from kitty.plugins import NUM_PLUGIN_SHADER_CHANNELS
        from kitty.shaders.slang import parse_animation_events, parse_pipeline_definition

        last = NUM_PLUGIN_SHADER_CHANNELS - 1
        self.assertEqual(parse_animation_events(f'plugin-signal-0|plugin-signal-{last}'), ('plugin-signal-0', f'plugin-signal-{last}'))
        with self.assertRaises(Exception):
            parse_animation_events(f'plugin-signal-{last + 1}')
        set_plugin_shader_param(2 * last + 1, 1, 2, 3, 4)
        fire_plugin_shader_signal(last)
        with self.assertRaises(IndexError):
            set_plugin_shader_param(2 * NUM_PLUGIN_SHADER_CHANNELS, 0, 0, 0, 0)
        with self.assertRaises(IndexError):
            fire_plugin_shader_signal(NUM_PLUGIN_SHADER_CHANNELS)
        set_plugin_shader_param(2 * last + 1, 0, 0, 0, 0)
        set_plugin_shader_channel_visible(last, False)
        set_plugin_shader_channel_visible(last, True)
        with self.assertRaises(IndexError):
            set_plugin_shader_channel_visible(NUM_PLUGIN_SHADER_CHANNELS, True)
        group = parse_pipeline_definition(['startgroup', f'plugin_channel {last}', 'shaders x', 'endgroup'], 'x')['groups'][0]
        self.assertEqual(group['plugin_channel'], last)
        with self.assertRaises(ValueError):
            parse_pipeline_definition(['startgroup', f'plugin_channel {last + 1}', 'endgroup'], 'x')


class TestPluginColorParsing(unittest.TestCase):
    def test_boss_turns_plugin_colors_into_a_color_spec(self) -> None:
        from unittest.mock import patch

        from kitty.boss import Boss

        boss = Boss.__new__(Boss)
        boss.window_id_map = {5: object()}
        with patch('kitty.colors.patch_colors') as patch_colors:
            boss._set_plugin_colors(5, {'background': '#101820', 'cursor': '#ff0000'})
        spec = patch_colors.call_args[0][0]
        self.assertEqual(spec, {'background': 0x101820, 'cursor': 0xFF0000})
        self.assertEqual(patch_colors.call_args[1]['windows'], (boss.window_id_map[5],))


class TestPluginActions(unittest.TestCase):
    def test_plugin_actions_with_arguments_parse(self) -> None:
        from kitty.options.utils import parse_key_action

        self.assertEqual(tuple(parse_key_action("plugin_command web-search search 'a b'")), ('plugin_command', ('web-search', 'search', 'a b')))
        for action in ('enable_plugin', 'disable_plugin', 'uninstall_plugin', 'install_bundled_plugin', 'install_catalog_plugin', 'update_catalog_plugin'):
            self.assertEqual(tuple(parse_key_action(f'{action} snake')), (action, ('snake',)))


class TestClaudeBackend(unittest.TestCase):
    def setUp(self) -> None:
        self.tdir = tempfile.mkdtemp()
        self.host = FakeHost(self.tdir)

    def tearDown(self) -> None:
        self.host.manager.shutdown()
        shutil.rmtree(self.tdir)

    def test_cli_command_is_isolated(self) -> None:
        module = self.host.module('ai-command')
        command = module.cli_command('/bin/claude', 'SYS')
        self.assertEqual(command[:2], ['/bin/claude', '-p'])
        for flag in ('--no-session-persistence', '--strict-mcp-config'):
            self.assertIn(flag, command)
        self.assertEqual(command[command.index('--output-format') + 1], 'json')
        self.assertEqual(command[command.index('--tools') + 1], '')
        self.assertEqual(command[command.index('--setting-sources') + 1], 'local')
        self.assertEqual(command[command.index('--system-prompt') + 1], 'SYS')
        self.assertEqual(module.parse_cli_output('{"is_error": false, "result": " ls \\n"}', ''), 'ls')
        for bad in ('{"is_error": true, "result": "Not logged in"}', 'garbage', '[]', '{"result": ""}'):
            with self.assertRaises(RuntimeError):
                module.parse_cli_output(bad, 'stderr text')

    def test_ask_runs_the_cli_without_blocking(self) -> None:
        from unittest.mock import patch

        fake = os.path.join(self.tdir, 'claude')
        with open(fake, 'w') as f:
            f.write('#!/bin/sh\nread prompt\nprintf \'{"is_error": false, "result": "echo %s"}\' "$prompt"\n')
        os.chmod(fake, 0o755)
        h = self.host
        module = h.module('ai-command')
        answers: list[Any] = []
        with patch.object(module, 'claude_cli', return_value=fake), patch.dict(os.environ, {'CLAUDECODE': '1'}):
            module.ask_claude(h.context('ai-command'), 'SYS', 'hello\n', lambda error, answer: answers.append((error, answer)))
        h.wait_for(lambda: answers)
        self.assertEqual(answers, [(None, 'echo hello')])


class TestRunProcess(unittest.TestCase):
    def test_output_input_and_timeout(self) -> None:
        tdir = tempfile.mkdtemp()
        h = FakeHost(tdir)
        try:
            context = h.context('git-mood')
            results: list[Any] = []
            context.run_process(['sh', '-c', 'cat; echo oops >&2'], lambda error, result: results.append((error, result)), input='in put')
            h.wait_for(lambda: results)
            error, result = results[0]
            self.assertIsNone(error)
            self.assertEqual((result.stdout, result.stderr), ('in put', 'oops\n'))
            self.assertFalse(hasattr(result, 'returncode'))
            context.run_process(['sleep', '5'], lambda error, result: results.append((error, result)), timeout=0.2)
            h.wait_for(lambda: len(results) > 1)
            self.assertIsInstance(results[1][0], TimeoutError)
            context.run_process(['/nonexistent/program'], lambda error, result: results.append((error, result)))
            self.assertIsInstance(results[2][0], OSError)
            self.assertEqual(h.manager.loaded['git-mood'].timers, set())
            with self.assertRaises(PluginError):
                h.context('snake').run_process(['true'], lambda error, result: None)
        finally:
            h.manager.shutdown()
            shutil.rmtree(tdir)
