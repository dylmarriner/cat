import datetime

# hour -> (background, foreground, cursor, selection_background)
KEYFRAMES = (
    (0.0, ('#0b1020', '#c8d3f5', '#82aaff', '#2d3f76')),
    (5.5, ('#1a1426', '#e6d5f2', '#ff9eaf', '#4a3360')),
    (8.0, ('#1d2330', '#f2efe6', '#ffd479', '#3b4a63')),
    (13.0, ('#20262e', '#f4f6f7', '#7fdbca', '#3a4a5a')),
    (18.5, ('#261a14', '#f6e2c8', '#ff9e64', '#5a3b2a')),
    (21.0, ('#141226', '#d6d0f0', '#bb9af7', '#36305e')),
    (24.0, ('#0b1020', '#c8d3f5', '#82aaff', '#2d3f76')),
)
KEYS = ('background', 'foreground', 'cursor', 'selection_background')


def mix(a, b, f):
    ca = [int(a[i : i + 2], 16) for i in (1, 3, 5)]
    cb = [int(b[i : i + 2], 16) for i in (1, 3, 5)]
    return '#' + ''.join(f'{round(x + (y - x) * f):02x}' for x, y in zip(ca, cb))


def palette(hour):
    hour %= 24.0
    for (h0, c0), (h1, c1) in zip(KEYFRAMES, KEYFRAMES[1:]):
        if h0 <= hour <= h1:
            f = (hour - h0) / (h1 - h0)
            f = f * f * (3 - 2 * f)
            return {k: mix(a, b, f) for k, a, b in zip(KEYS, c0, c1)}
    raise ValueError(hour)


def setup(api):
    state = {'timer': None, 'preview': None}

    def now_hour():
        n = datetime.datetime.now()
        return n.hour + n.minute / 60.0

    def apply(hour):
        api.set_colors(palette(hour), all_windows=True)

    def resume(context=None, _args=()):
        if state['timer'] is None:
            state['timer'] = api.add_timer(lambda: apply(now_hour()), 60.0, repeat=True)
        apply(now_hour())

    def pause(context=None, _args=()):
        for key in ('timer', 'preview'):
            if state[key] is not None:
                api.cancel_timer(state[key])
                state[key] = None
        api.reset_colors(all_windows=True)

    def preview(context, _args):
        step = [0]
        if state['preview'] is not None:
            api.cancel_timer(state['preview'])

        def frame():
            step[0] += 1
            apply(step[0] * 0.25)
            if step[0] >= 96:
                api.cancel_timer(state['preview'])
                state['preview'] = None
                apply(now_hour())

        state['preview'] = api.add_timer(frame, 0.125, repeat=True)

    api.register_command('resume', resume, 'Follow the time of day with terminal colors')
    api.register_command('pause', pause, 'Restore normal colors')
    api.register_command('preview', preview, 'Watch a full day of colors in 12 seconds')
    api.contribute_ui('Daylight: preview a day', 'preview')
    api.contribute_ui('Daylight: pause', 'pause')
    api.contribute_ui('Daylight: resume', 'resume')
    api.add_timer(resume, 0.5)
    api.on_disable(lambda: api.reset_colors(all_windows=True))
