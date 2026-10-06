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


import re
import textwrap

BOLD, DIM, RESET = '\x1b[1m', '\x1b[2m', '\x1b[0m'


def render_markdown(text, width):
    lines, code_blocks, in_code = [], [], False
    for raw in text.splitlines():
        if raw.strip().startswith('```'):
            in_code = not in_code
            if in_code:
                code_blocks.append([])
            continue
        if in_code:
            code_blocks[-1].append(raw)
            lines.append(f'\x1b[48;5;236m\x1b[38;5;222m {raw.ljust(width - 2)[: width - 2]} {RESET}')
            continue
        heading = re.match(r'(#+)\s+(.*)', raw)
        if heading:
            lines += ['', f'{BOLD}\x1b[38;5;45m{heading.group(2)}{RESET}']
            continue
        bullet = re.match(r'(\s*)([-*]|\d+\.)\s+(.*)', raw)
        prefix, body = ('', raw)
        if bullet:
            prefix, body = bullet.group(1) + ('• ' if bullet.group(2) in '-*' else bullet.group(2) + ' '), bullet.group(3)
        wrapped = textwrap.wrap(body, max(20, width - len(prefix) - 1)) or ['']
        for i, part in enumerate(wrapped):
            part = re.sub(r'\*\*(.+?)\*\*', BOLD + r'\1' + RESET, part)
            part = re.sub(r'`([^`]+)`', '\x1b[38;5;222m' + r'\1' + RESET, part)
            lines.append((prefix if i == 0 else ' ' * len(prefix)) + part)
    return lines, ['\n'.join(b) for b in code_blocks]


def main():
    with open(sys.argv[-1], encoding='utf-8') as f:
        text = f.read()
    top = 0
    with Terminal() as term:
        while True:
            width, height = term.size()
            lines, blocks = render_markdown(text, width - 2)
            view = height - 1
            top = max(0, min(top, len(lines) - view))
            footer = f'{DIM}↑↓ j k space scroll · {"y copy code · " if blocks else ""}q close · {top + 1}-{min(len(lines), top + view)}/{len(lines)}{RESET}'
            term.draw([' ' + l for l in lines[top : top + view]] + [''] * max(0, view - len(lines[top : top + view])) + [footer])
            key = term.key()
            if key in ('q', KEY_ESC, KEY_CTRL_C):
                return
            if key == 'y' and blocks:
                write_result(blocks[0])
                return
            top += {KEY_DOWN: 1, 'j': 1, KEY_UP: -1, 'k': -1, ' ': view, KEY_PAGE_DOWN: view, KEY_PAGE_UP: -view, 'g': -(10**6), 'G': 10**6}.get(key, 0)


main()
