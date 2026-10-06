import re


def count_matches(pattern, text):
    return sum(1 for _ in pattern.finditer(text))


def setup(api):
    effect = api.shader_effect('screen-watcher.pipeline')
    watches = {}
    state = {'timer': None}

    def poll():
        for window_id, watch in tuple(watches.items()):
            try:
                count = count_matches(watch['pattern'], api.read_screen(window_id))
            except Exception:
                watches.pop(window_id, None)
                continue
            if count > watch['count']:
                api.notify('🔔 Screen watcher matched', watch['pattern'].pattern)
                api.set_tab_title(f'🔔 {watch["pattern"].pattern[:20]}', window_id=window_id)
                effect.fire()
            watch['count'] = count
        if not watches and state['timer'] is not None:
            api.cancel_timer(state['timer'])
            state['timer'] = None

    def watch(context, _args):
        window_id = context.current_window_id

        def start(text):
            if not text.strip() or window_id is None:
                return
            pattern = re.compile(text.strip(), re.IGNORECASE)
            watches[window_id] = {'pattern': pattern, 'count': count_matches(pattern, api.read_screen(window_id))}
            api.set_tab_title(f'👀 {pattern.pattern[:20]}', window_id=window_id)
            if state['timer'] is None:
                state['timer'] = api.add_timer(poll, 1.5, repeat=True)

        context.prompt('Watch screen for (regular expression)', start)

    def unwatch(context, _args):
        if watches.pop(context.current_window_id, None) is not None:
            context.set_tab_title('')

    api.register_command('watch', watch, 'Get notified when text appears in this window')
    api.register_command('unwatch', unwatch, 'Stop watching this window')
    api.contribute_ui('Watch screen for text', 'watch')
    api.contribute_ui('Stop watching screen', 'unwatch')
