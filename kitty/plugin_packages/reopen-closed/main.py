import os
import time

LIMIT = 20


def setup(api):
    known = {}
    closed = []

    def remember(event):
        if event.window_id is None:
            return
        try:
            info = api.window_info(event.window_id)
        except Exception:
            return
        if info.get('cwd'):
            known[event.window_id] = {'cwd': info['cwd'], 'title': info.get('title', ''), 'closed_at': 0.0}

    def on_focus(event):
        if event.window_id in known:
            remember(event)

    def on_closed(event):
        entry = known.pop(event.window_id, None)
        if entry is not None:
            entry['closed_at'] = time.time()
            closed.insert(0, entry)
            del closed[LIMIT:]

    def open_entry(context, entry):
        shell = os.environ.get('SHELL') or '/bin/sh'
        context.launch([shell], cwd=entry['cwd'], tab_title=os.path.basename(entry['cwd']) or entry['cwd'])

    def reopen(context, _args):
        if closed:
            open_entry(context, closed.pop(0))

    def choose(context, _args):
        if not closed:
            return
        now = time.time()
        entries = [(repr(e['closed_at']), f'{e["cwd"]}  ·  {int((now - e["closed_at"]) // 60)}m ago  ·  {e["title"][:40]}') for e in closed]

        def picked(value):
            # look the entry up again, shells may have closed while the chooser was open
            entry = next((e for e in closed if repr(e['closed_at']) == value), None)
            if entry is not None:
                closed.remove(entry)
                open_entry(context, entry)

        context.choose('Reopen closed shell', entries, picked)

    api.subscribe('command_started', remember)
    api.subscribe('command_finished', remember)
    api.subscribe('window_focused', on_focus)
    api.subscribe('window_closed', on_closed)
    api.register_command('reopen', reopen, 'Reopen the most recently closed shell')
    api.register_command('choose', choose, 'Choose a recently closed shell to reopen')
    api.contribute_ui('Reopen closed shell', 'reopen')
    api.contribute_ui('Reopen closed shell…', 'choose')
