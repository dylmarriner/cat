import time

DELAY = 3.0


def setup(api):
    effect = api.shader_effect('busy-orbit.pipeline')
    running = {}
    focused = [None]
    state = {'timer': None}

    def tick():
        window = focused[0]
        busy = window in running and time.monotonic() - running[window] >= DELAY
        effect.set(0, 1.0 if busy else 0.0)
        if busy:
            effect.fire()  # keeps the animation alive, it stops on its own shortly after the last fire
        if not running and state['timer'] is not None:
            api.cancel_timer(state['timer'])
            state['timer'] = None

    def on_started(event):
        if event.window_id is not None:
            running[event.window_id] = time.monotonic()
            if state['timer'] is None:
                state['timer'] = api.add_timer(tick, 1.0, repeat=True)

    def on_finished(event):
        running.pop(event.window_id, None)
        tick()

    def on_focus(event):
        focused[0] = event.window_id
        tick()

    api.subscribe('command_started', on_started)
    api.subscribe('command_finished', on_finished)
    api.subscribe('window_closed', on_finished)
    api.subscribe('window_focused', on_focus)
