import os

THRESHOLD = 0.7


def load_ratio():
    return os.getloadavg()[0] / max(1, os.cpu_count() or 1)


def setup(api):
    effect = api.shader_effect('load-heatwave.pipeline')

    def tick():
        ratio = load_ratio()
        hot = ratio >= THRESHOLD
        effect.set(0, min(ratio, 2.0) if hot else 0.0)
        if hot:
            effect.fire()  # keeps the animation running, it ends shortly after the last fire

    api.add_timer(tick, 2.0, repeat=True)
