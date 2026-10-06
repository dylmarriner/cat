import os
import select
import shutil
import sys
import termios
import tty

KEY_UP, KEY_DOWN, KEY_RIGHT, KEY_LEFT = '\x1b[A', '\x1b[B', '\x1b[C', '\x1b[D'
KEY_ENTER, KEY_ESC, KEY_BACKSPACE, KEY_CTRL_C = '\r', '\x1b', '\x7f', '\x03'
KEY_PAGE_UP, KEY_PAGE_DOWN = '\x1b[5~', '\x1b[6~'


class Terminal:
    """Raw mode, alternate screen and keyboard reading for a full screen overlay."""

    def __enter__(self):
        self.fd = sys.stdin.fileno()
        self.saved = termios.tcgetattr(self.fd)
        tty.setraw(self.fd)
        self.write('\x1b[?1049h\x1b[?25l\x1b[H\x1b[2J')
        return self

    def __exit__(self, *exc):
        self.write('\x1b[0m\x1b[?25h\x1b[?1049l')
        termios.tcsetattr(self.fd, termios.TCSADRAIN, self.saved)

    @staticmethod
    def write(text):
        sys.stdout.write(text)
        sys.stdout.flush()

    @staticmethod
    def size():
        s = shutil.get_terminal_size()
        return s.columns, s.lines

    def key(self, timeout=None):
        ready, _, _ = select.select([self.fd], [], [], timeout)
        if not ready:
            return None
        return os.read(self.fd, 256).decode('utf-8', 'replace')

    def draw(self, lines):
        """Replace the screen with lines, which may contain SGR escapes."""
        self.write('\x1b[H' + '\x1b[K\r\n'.join(lines) + '\x1b[K\x1b[J')


def write_result(text):
    path = os.environ.get('KITTY_PLUGIN_RESULT')
    if path:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(text)


import colorsys

FORMATS = ('hex', 'rgb', 'hsl')


def rgb_of(h, s, l):
    return tuple(round(c * 255) for c in colorsys.hls_to_rgb(h % 1.0, l, s))


def fmt(kind, h, s, l):
    r, g, b = rgb_of(h, s, l)
    if kind == 'hex':
        return f'#{r:02x}{g:02x}{b:02x}'
    if kind == 'rgb':
        return f'rgb({r}, {g}, {b})'
    return f'hsl({round(h % 1.0 * 360)}, {round(s * 100)}%, {round(l * 100)}%)'


def bg(h, s, l):
    return '\x1b[48;2;{};{};{}m'.format(*rgb_of(h, s, l))


def main():
    h, s, l, kind = 0.58, 0.75, 0.55, 0
    with Terminal() as term:
        while True:
            width, height = term.size()
            strip_w = max(20, width - 4)
            lines = ['\x1b[1m🎨 Color picker\x1b[0m  \x1b[2m←→ hue · ↑↓ lightness · [ ] saturation · Tab format · Enter copy\x1b[0m', '']
            hue_strip = ''.join(bg(i / strip_w, 1, 0.5) + ' ' for i in range(strip_w)) + '\x1b[0m'
            marker = ' ' * int(h % 1.0 * strip_w) + '▲'
            lines += ['  ' + hue_strip, '  ' + marker, '']
            swatch_h = max(3, min(8, height - 16))
            for _ in range(swatch_h):
                lines.append('  ' + bg(h, s, l) + ' ' * (strip_w // 2) + '\x1b[0m  ' + bg(h + 0.5, s, l) + ' ' * (strip_w // 4) + '\x1b[0m')
            lines.append('  ' + ' ' * (strip_w // 2 - 6) + '\x1b[2mselected\x1b[0m' + ' ' * 6 + '\x1b[2mcomplement\x1b[0m')
            lines.append('')
            harmony = ''.join(bg(h + d, s, l) + '      ' for d in (-1 / 6, -1 / 12, 0, 1 / 12, 1 / 6, 1 / 3, 2 / 3)) + '\x1b[0m'
            lines.append('  ' + harmony + '  \x1b[2manalogous · triadic\x1b[0m')
            shades = ''.join(bg(h, s, x / 10) + '    ' for x in range(1, 10)) + '\x1b[0m'
            lines.append('  ' + shades + '  \x1b[2mshades\x1b[0m')
            lines.append('')
            for i, k in enumerate(FORMATS):
                pointer = '\x1b[1;36m▶\x1b[0m' if i == kind else ' '
                lines.append(f'  {pointer} {fmt(k, h, s, l)}')
            term.draw(lines[:height])
            key = term.key()
            if key in (KEY_ESC, KEY_CTRL_C, 'q'):
                return
            if key == KEY_ENTER:
                write_result(fmt(FORMATS[kind], h, s, l))
                return
            step = {
                KEY_LEFT: ('h', -1 / 120),
                KEY_RIGHT: ('h', 1 / 120),
                'h': ('h', -1 / 24),
                'H': ('h', 1 / 24),
                KEY_DOWN: ('l', -0.02),
                KEY_UP: ('l', 0.02),
                'L': ('l', 0.1),
                'l': ('l', -0.1),
                '[': ('s', -0.02),
                ']': ('s', 0.02),
                's': ('s', -0.1),
                'S': ('s', 0.1),
            }.get(key)
            if step:
                name, delta = step
                if name == 'h':
                    h = (h + delta) % 1.0
                elif name == 'l':
                    l = min(1.0, max(0.0, l + delta))
                else:
                    s = min(1.0, max(0.0, s + delta))
            elif key == '\t':
                kind = (kind + 1) % len(FORMATS)


main()
