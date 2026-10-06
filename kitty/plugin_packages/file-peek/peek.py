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


import shlex
import stat

PREVIEW_BYTES = 64 * 1024


def listing(path, show_hidden, query):
    try:
        names = os.listdir(path)
    except OSError:
        return []
    entries = []
    for name in names:
        if not show_hidden and name.startswith('.'):
            continue
        if query and query.lower() not in name.lower():
            continue
        full = os.path.join(path, name)
        entries.append((not os.path.isdir(full), name.lower(), name, full))
    return [(name, full) for _, _, name, full in sorted(entries)]


def highlight(path, text):
    try:
        from pygments import highlight as hl
        from pygments.formatters import TerminalTrueColorFormatter
        from pygments.lexers import guess_lexer_for_filename
    except ImportError:
        return text.splitlines()
    try:
        lexer = guess_lexer_for_filename(path, text)
    except Exception:
        return text.splitlines()
    return hl(text, lexer, TerminalTrueColorFormatter(style='monokai')).splitlines()


def preview(full, width, height):
    try:
        st = os.stat(full)
    except OSError as err:
        return [str(err)]
    if stat.S_ISDIR(st.st_mode):
        items = listing(full, False, '')
        return [f'\x1b[1;34m📁 {len(items)} items\x1b[0m'] + [('📁 ' if os.path.isdir(f) else '   ') + n for n, f in items[:height]]
    with open(full, 'rb') as f:
        data = f.read(PREVIEW_BYTES)
    if b'\0' in data:
        return [f'\x1b[2mbinary file, {st.st_size} bytes\x1b[0m']
    text = data.decode('utf-8', 'replace').expandtabs(4)
    return highlight(full, '\n'.join(text.splitlines()[:height]))


def clip(line, width):
    out, visible, i = [], 0, 0
    while i < len(line) and visible < width:
        if line[i] == '\x1b':
            end = line.find('m', i)
            if end == -1:
                break
            out.append(line[i : end + 1])
            i = end + 1
            continue
        out.append(line[i])
        visible += 1
        i += 1
    return ''.join(out) + '\x1b[0m'


def main():
    start = os.getcwd()
    path, selected, query, hidden = start, 0, '', False
    with Terminal() as term:
        while True:
            width, height = term.size()
            entries = listing(path, hidden, query)
            selected = min(selected, max(0, len(entries) - 1))
            left_w = max(20, width // 3)
            rows = height - 2
            offset = max(0, selected - rows + 1)
            right = preview(entries[selected][1], width - left_w - 3, rows) if entries else []
            lines = [f'\x1b[1;36m{path}\x1b[0m  \x1b[2m{("filter: " + query) if query else "type to filter"}\x1b[0m']
            for r in range(rows):
                i = r + offset
                if i < len(entries):
                    name, full = entries[i]
                    label = ('📁 ' if os.path.isdir(full) else '   ') + name
                    cell = label[:left_w].ljust(left_w)
                    cell = f'\x1b[7m{cell}\x1b[0m' if i == selected else cell
                else:
                    cell = ' ' * left_w
                lines.append(cell + ' \x1b[38;5;240m│\x1b[0m ' + clip(right[r] if r < len(right) else '', width - left_w - 3))
            lines.append('\x1b[2m↑↓ move · Enter open/pick · Backspace up · . hidden · Esc close\x1b[0m')
            term.draw(lines[:height])
            key = term.key()
            if key in (KEY_ESC, KEY_CTRL_C):
                return
            if key == KEY_UP:
                selected = max(0, selected - 1)
            elif key == KEY_DOWN:
                selected = min(len(entries) - 1, selected + 1)
            elif key in (KEY_PAGE_UP, KEY_PAGE_DOWN):
                selected = max(0, min(len(entries) - 1, selected + (rows if key == KEY_PAGE_DOWN else -rows)))
            elif key == KEY_ENTER and entries:
                full = entries[selected][1]
                if os.path.isdir(full):
                    path, selected, query = full, 0, ''
                else:
                    write_result(shlex.quote(os.path.relpath(full, start)))
                    return
            elif key in (KEY_BACKSPACE, KEY_LEFT):
                if query:
                    query = query[:-1]
                else:
                    path, selected = os.path.dirname(path) or path, 0
            elif key == '.' and not query:
                hidden = not hidden
            elif key and key.isprintable():
                query, selected = query + key, 0


main()
