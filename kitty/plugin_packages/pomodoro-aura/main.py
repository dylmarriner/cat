import json
import os
import time

FOCUS, BREAK = 1.0, 2.0


def register_settings(api):
    with open(os.path.join(api.package_directory, 'plugin.json'), encoding='utf-8') as f:
        for page in json.load(f)['settings']:
            api.register_settings_page(page['id'], page)


def setup(api):
    register_settings(api)
    effect = api.shader_effect('pomodoro-aura.pipeline')
    effect.show(False)
    state = {'phase': 0.0, 'ends_at': 0.0, 'length': 1.0, 'timer': None, 'sessions': 0}

    def durations():
        values = api.settings()['timer']
        return max(1, values['focus_minutes']) * 60.0, max(1, values['break_minutes']) * 60.0

    def begin(phase):
        focus, rest = durations()
        state['phase'] = phase
        state['length'] = focus if phase == FOCUS else rest
        state['ends_at'] = time.monotonic() + state['length']
        effect.show(True)
        tick()

    def tick():
        if not state['phase']:
            effect.set(0, 0)
            effect.show(False)
            return
        remaining = state['ends_at'] - time.monotonic()
        if remaining <= 0:
            if state['phase'] == FOCUS:
                state['sessions'] += 1
                api.notify('🍅 Focus session done', f'Take a break. Sessions today: {state["sessions"]}')
                begin(BREAK)
            else:
                api.notify('☕ Break over', 'Back to focus')
                begin(FOCUS)
            return
        effect.set(0, state['phase'], 1.0 - remaining / state['length'])

    def start(context, _args):
        if state['timer'] is None:
            state['timer'] = api.add_timer(tick, 1.0, repeat=True)
        begin(FOCUS)

    def stop(context, _args):
        if state['timer'] is not None:
            api.cancel_timer(state['timer'])
            state['timer'] = None
        state['phase'] = 0.0
        tick()

    def skip(context, _args):
        if state['phase']:
            state['ends_at'] = time.monotonic()
            tick()

    api.register_command('start', start, 'Start a focus session')
    api.register_command('stop', stop, 'Stop the pomodoro timer')
    api.register_command('skip', skip, 'Skip to the next pomodoro phase')
    api.contribute_ui('Pomodoro: start focus', 'start')
    api.contribute_ui('Pomodoro: stop', 'stop')
    api.contribute_ui('Pomodoro: skip phase', 'skip')
