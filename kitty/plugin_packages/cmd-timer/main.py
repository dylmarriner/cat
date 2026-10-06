import json
import os


def register_settings(api):
    with open(os.path.join(api.package_directory, 'plugin.json'), encoding='utf-8') as f:
        for page in json.load(f)['settings']:
            api.register_settings_page(page['id'], page)


def human(seconds):
    seconds = int(round(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f'{hours}h {minutes:02d}m'
    if minutes:
        return f'{minutes}m {secs:02d}s'
    return f'{secs}s'


def message(cmdline, exit_code, duration):
    command = ' '.join(cmdline.split())
    if len(command) > 80:
        command = command[:77] + '…'
    if exit_code:
        return f'✘ Failed after {human(duration)} (exit {exit_code})', command
    return f'✔ Finished in {human(duration)}', command


def setup(api):
    register_settings(api)
    focused = [None]

    def on_finished(event):
        prefs = api.settings()['timer']
        if event.duration < prefs['min_seconds']:
            return
        if event.window_id == focused[0] and not prefs['notify_when_focused']:
            return
        title, body = message(event.cmdline, event.exit_code, event.duration)
        api.notify(title, body)

    api.subscribe('window_focused', lambda event: focused.__setitem__(0, event.window_id))
    api.subscribe('command_finished', on_finished)
