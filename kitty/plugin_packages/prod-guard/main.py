import json
import os
import re


def register_settings(api):
    with open(os.path.join(api.package_directory, 'plugin.json'), encoding='utf-8') as f:
        for page in json.load(f)['settings']:
            api.register_settings_page(page['id'], page)


def danger_pattern(api):
    return re.compile(api.settings()['guard']['pattern'], re.IGNORECASE)


def setup(api):
    register_settings(api)
    effect = api.shader_effect('prod-guard.pipeline')
    effect.show(False)
    dangerous = set()
    active = [None]

    def refresh():
        danger = active[0] in dangerous
        effect.set(0, 1.0 if danger else 0.0)
        effect.show(danger)

    def on_started(event):
        if event.window_id is not None and danger_pattern(api).search(event.cmdline):
            dangerous.add(event.window_id)
            api.set_colors({'background': '#2a0606', 'cursor': '#ff3b3b', 'selection_background': '#6b1010'}, window_id=event.window_id)
            refresh()

    def on_finished(event):
        if event.window_id in dangerous:
            dangerous.discard(event.window_id)
            try:
                api.reset_colors(window_id=event.window_id)
            except Exception:
                pass  # window already gone
            refresh()

    def on_focus(event):
        active[0] = event.window_id
        refresh()

    api.subscribe('command_started', on_started)
    api.subscribe('command_finished', on_finished)
    api.subscribe('window_closed', on_finished)
    api.subscribe('window_focused', on_focus)
