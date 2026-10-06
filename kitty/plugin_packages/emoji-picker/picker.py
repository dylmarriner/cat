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


import json
import unicodedata

RANGES = ((0x1F300, 0x1F5FF), (0x1F600, 0x1F64F), (0x1F680, 0x1F6FF), (0x1F900, 0x1F9FF), (0x1FA70, 0x1FAFF), (0x2600, 0x26FF), (0x2700, 0x27BF))
RECENTS = os.path.join(os.environ.get('KITTY_PLUGIN_DATA', '.'), 'recent-emoji.json')
CELL = 4


def all_emoji():
    ans = []
    for start, end in RANGES:
        for cp in range(start, end + 1):
            ch = chr(cp)
            name = unicodedata.name(ch, '')
            if name and unicodedata.category(ch) == 'So':
                ans.append((ch, name.lower()))
    return ans


def load_recents():
    try:
        with open(RECENTS, encoding='utf-8') as f:
            return [x for x in json.load(f) if isinstance(x, str)]
    except (OSError, ValueError):
        return []


def search(emoji, recents, query):
    words = query.lower().split()
    matches = [e for e in emoji if all(w in e[1] for w in words)]
    rank = {ch: i for i, ch in enumerate(recents)}

    def key(e):
        name_words = e[1].split()
        whole_words = sum(w in name_words for w in words)
        return rank.get(e[0], len(rank)), -whole_words, len(name_words), e[1]

    return sorted(matches, key=key)


def main():
    emoji = all_emoji()
    recents = load_recents()
    query, selected = '', 0
    with Terminal() as term:
        while True:
            width, height = term.size()
            columns = max(1, (width - 2) // CELL)
            matches = search(emoji, recents, query)
            selected = min(selected, max(0, len(matches) - 1))
            rows = max(1, height - 4)
            first_row = max(0, selected // columns - rows + 1)
            lines = [f'\x1b[1m🔍 {query}\x1b[0m\x1b[2m▏ {len(matches)} emoji · arrows move · Enter insert · Esc cancel\x1b[0m', '']
            for r in range(first_row, first_row + rows):
                cells = []
                for c in range(columns):
                    i = r * columns + c
                    if i >= len(matches):
                        break
                    ch = matches[i][0]
                    cells.append(f'\x1b[7m {ch} \x1b[0m' if i == selected else f' {ch} ')
                lines.append(' '.join(cells))
            name = matches[selected][1] if matches else 'no match'
            lines = lines[: height - 1] + [''] * max(0, height - 1 - len(lines)) + [f'\x1b[36m{name}\x1b[0m']
            term.draw(lines)
            key = term.key()
            if key in (KEY_ESC, KEY_CTRL_C):
                return
            if key == KEY_ENTER and matches:
                ch = matches[selected][0]
                os.makedirs(os.path.dirname(RECENTS) or '.', exist_ok=True)
                with open(RECENTS, 'w', encoding='utf-8') as f:
                    json.dump([ch] + [x for x in recents if x != ch][:40], f)
                write_result(ch)
                return
            moves = {KEY_LEFT: -1, KEY_RIGHT: 1, KEY_UP: -columns, KEY_DOWN: columns}
            if key in moves:
                selected = max(0, min(len(matches) - 1, selected + moves[key]))
            elif key == KEY_BACKSPACE:
                query, selected = query[:-1], 0
            elif key and key.isprintable():
                query, selected = query + key, 0


main()
