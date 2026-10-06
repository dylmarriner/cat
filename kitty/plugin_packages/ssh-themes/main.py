import colorsys
import hashlib
import os

PROGRAMS = {'ssh', 'mosh', 'autossh', 'et'}
OPTIONS_WITH_VALUES = set('BbcDEeFIiJLlmOoPpQRSWw')


def ssh_host(cmdline):
    words = cmdline.split()
    if len(words) > 1 and os.path.basename(words[0]) == 'kitten' and words[1] == 'ssh':
        words = words[1:]
    if not words or os.path.basename(words[0]) not in PROGRAMS:
        return None
    skip = False
    for word in words[1:]:
        if skip:
            skip = False
            continue
        if word == '--':
            continue
        if word.startswith('-'):
            skip = len(word) == 2 and word[1] in OPTIONS_WITH_VALUES
            continue
        return word.split('@')[-1]
    return None


def hsl(hue, saturation, lightness):
    r, g, b = colorsys.hls_to_rgb(hue, lightness, saturation)
    return f'#{round(r * 255):02x}{round(g * 255):02x}{round(b * 255):02x}'


def theme(host):
    hue = int(hashlib.sha1(host.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
    return {
        'background': hsl(hue, 0.45, 0.08),
        'cursor': hsl(hue, 0.85, 0.65),
        'selection_background': hsl(hue, 0.45, 0.28),
        'active_border_color': hsl(hue, 0.85, 0.6),
    }


def setup(api):
    themed = set()

    def on_started(event):
        host = ssh_host(event.cmdline)
        if host and event.window_id is not None:
            api.set_colors(theme(host), window_id=event.window_id)
            themed.add(event.window_id)

    def on_finished(event):
        if event.window_id in themed:
            themed.discard(event.window_id)
            try:
                api.reset_colors(window_id=event.window_id)
            except Exception:
                pass  # the window is gone

    api.subscribe('command_started', on_started)
    api.subscribe('command_finished', on_finished)
    api.subscribe('window_closed', on_finished)
