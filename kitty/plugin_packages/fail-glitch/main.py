def severity(exit_code):
    if not exit_code:
        return 0.0
    if exit_code == 130:
        return 0.35
    if exit_code > 128:
        return 1.0
    return 0.7


def setup(api):
    effect = api.shader_effect('fail-glitch.pipeline')
    count = [0]

    def on_finished(event):
        strength = severity(event.exit_code)
        if strength:
            count[0] += 1
            effect.set(0, strength, count[0] * 17.0)
            effect.fire()

    api.subscribe('command_finished', on_finished)
