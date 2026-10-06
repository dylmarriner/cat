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
import random
import time

SCORES = os.path.join(os.environ.get('KITTY_PLUGIN_DATA', '.'), 'typing.json')
SNIPPETS = (
    'git log --oneline --graph --decorate --all | head -n 20',
    'find . -name "*.py" -not -path "./.venv/*" | xargs wc -l | sort -n',
    'for (const [key, value] of Object.entries(config)) { console.log(key, value); }',
    'def fibonacci(n): return n if n < 2 else fibonacci(n - 1) + fibonacci(n - 2)',
    'let total: u64 = items.iter().filter(|x| x.active).map(|x| x.price).sum();',
    'docker run --rm -it -v "$PWD":/app -w /app python:3.12 python -m pytest -q',
    'with open(path, encoding="utf-8") as f: data = json.load(f)',
    'kubectl get pods -n production -o wide --sort-by=.status.startTime',
    'const response = await fetch(url, { headers: { Accept: "application/json" } });',
    'if err != nil { return fmt.Errorf("loading config %s: %w", path, err) }',
    "awk -F, '{ sum[$1] += $3 } END { for (k in sum) print k, sum[k] }' sales.csv",
    'SELECT name, count(*) FROM orders GROUP BY name HAVING count(*) > 10 ORDER BY 2 DESC;',
    'ssh -L 5432:localhost:5432 deploy@db.internal -N -o ServerAliveInterval=30',
    'match command { Some(cmd) => run(cmd)?, None => eprintln!("nothing to do") }',
    'tar --exclude=node_modules -czf backup-$(date +%F).tar.gz ~/projects',
)


def load_best():
    try:
        with open(SCORES, encoding='utf-8') as f:
            return float(json.load(f)['best'])
    except (OSError, ValueError, KeyError, TypeError):
        return 0.0


def stats(target, typed, elapsed):
    correct = sum(1 for a, b in zip(target, typed) if a == b)
    minutes = max(elapsed, 1e-6) / 60
    wpm = correct / 5 / minutes
    accuracy = correct / max(1, len(typed)) * 100
    return wpm, accuracy


def main():
    best = load_best()
    with Terminal() as term:
        while True:
            target = ' '.join(random.sample(SNIPPETS, 3))
            typed, started = '', None
            while True:
                width, height = term.size()
                elapsed = time.monotonic() - started if started else 0.0
                wpm, accuracy = stats(target, typed, elapsed) if typed else (0.0, 100.0)
                out = []
                for i, ch in enumerate(target):
                    if i < len(typed):
                        out.append(f'\x1b[32m{ch}\x1b[0m' if typed[i] == ch else f'\x1b[41;97m{ch if ch != " " else "·"}\x1b[0m')
                    elif i == len(typed):
                        out.append(f'\x1b[4;1m{ch}\x1b[0m')
                    else:
                        out.append(f'\x1b[2m{ch}\x1b[0m')
                text_lines, line, visible = [], '', 0
                for piece in out:
                    line += piece
                    visible += 1
                    if visible >= width - 4:
                        text_lines.append(line)
                        line, visible = '', 0
                text_lines.append(line)
                header = f'\x1b[1m⌨  Typing test\x1b[0m   \x1b[1;36m{wpm:5.1f}\x1b[0m wpm   {accuracy:5.1f}% accuracy   {elapsed:5.1f}s   best {best:.1f}'
                term.draw([header, '\x1b[2mTab new text · Esc quit\x1b[0m', ''] + ['  ' + l for l in text_lines])
                key = term.key(0.25 if started else None)
                if key is None:
                    continue
                if key in (KEY_ESC, KEY_CTRL_C):
                    return
                if key == '\t':
                    break
                if key == KEY_BACKSPACE:
                    typed = typed[:-1]
                elif key.isprintable():
                    started = started or time.monotonic()
                    typed += key
                if len(typed) >= len(target):
                    wpm, accuracy = stats(target, typed, time.monotonic() - started)
                    record = wpm > best and accuracy >= 90
                    if record:
                        best = wpm
                        os.makedirs(os.path.dirname(SCORES) or '.', exist_ok=True)
                        with open(SCORES, 'w', encoding='utf-8') as f:
                            json.dump({'best': best}, f)
                    term.draw(
                        [
                            '',
                            f'   \x1b[1m{"🏆 New personal best!" if record else "✔ Done"}\x1b[0m',
                            '',
                            f'   \x1b[1;36m{wpm:.1f}\x1b[0m wpm   {accuracy:.1f}% accuracy',
                            '',
                            '   \x1b[2mAny key for another round · Esc to quit\x1b[0m',
                        ]
                    )
                    if term.key() in (KEY_ESC, KEY_CTRL_C):
                        return
                    break


main()
