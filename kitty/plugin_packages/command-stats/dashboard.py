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


import sqlite3
import time

BARS = ' ▁▂▃▄▅▆▇█'
BOLD, DIM, RESET = '\x1b[1m', '\x1b[2m', '\x1b[0m'
ACCENT, GOOD, BAD = '\x1b[38;5;45m', '\x1b[38;5;78m', '\x1b[38;5;203m'


def human(seconds):
    seconds = int(seconds)
    if seconds >= 3600:
        return f'{seconds // 3600}h{seconds % 3600 // 60:02d}m'
    if seconds >= 60:
        return f'{seconds // 60}m{seconds % 60:02d}s'
    return f'{seconds}s'


def spark(values):
    top = max(values) or 1
    return ''.join(BARS[round(v / top * 8)] for v in values)


def render(db, width):
    q = lambda sql, *a: db.execute(sql, a).fetchall()
    total, failed, spent = q('SELECT count(*), sum(exit_code != 0), sum(duration) FROM commands')[0]
    if not total:
        return [f'{BOLD}Command stats{RESET}', '', 'No commands recorded yet. Run some commands with shell integration enabled.']
    lines = [f'{BOLD}{ACCENT}⚡ Command stats{RESET}  {DIM}q quit · r refresh{RESET}', '']
    failed = failed or 0
    lines.append(f'{BOLD}{total}{RESET} commands   {BAD}{failed}{RESET} failed ({failed * 100 / total:.1f}%)   {BOLD}{human(spent or 0)}{RESET} spent running')
    lines.append('')
    lines.append(f'{BOLD}Top tools{RESET}')
    rows = q('SELECT program, count(*) c, sum(exit_code != 0), sum(duration) FROM commands GROUP BY program ORDER BY c DESC LIMIT 10')
    peak = rows[0][1] if rows else 1
    bar_width = max(10, width - 52)
    for program, count, fails, duration in rows:
        bar = '█' * max(1, round(count / peak * bar_width))
        rate = fails * 100 / count
        color = BAD if rate > 25 else GOOD
        lines.append(f'  {program[:16]:<16} {ACCENT}{bar:<{bar_width}}{RESET} {count:>6}  {color}{rate:5.1f}%{RESET} fail  {human(duration):>7}')
    lines.append('')
    hours = [0] * 24
    for hour, count in q("SELECT CAST(strftime('%H', ts, 'unixepoch', 'localtime') AS INTEGER), count(*) FROM commands GROUP BY 1"):
        hours[hour] = count
    lines.append(f'{BOLD}Busiest hours{RESET}  {ACCENT}{spark(hours)}{RESET}')
    lines.append(f'               {DIM}0     6     12    18   23{RESET}')
    now = time.time()
    days = [q('SELECT count(*) FROM commands WHERE ts BETWEEN ? AND ?', now - (i + 1) * 86400, now - i * 86400)[0][0] for i in range(13, -1, -1)]
    lines.append(f'{BOLD}Last 14 days{RESET}   {ACCENT}{spark(days)}{RESET}  {DIM}{sum(days)} commands{RESET}')
    lines.append('')
    lines.append(f'{BOLD}Slowest this week{RESET}')
    for cmdline, duration, code in q('SELECT cmdline, duration, exit_code FROM commands WHERE ts > ? ORDER BY duration DESC LIMIT 5', now - 7 * 86400):
        mark = f'{BAD}✘{RESET}' if code else f'{GOOD}✔{RESET}'
        lines.append(f'  {mark} {human(duration):>7}  {cmdline[: max(10, width - 16)]}')
    return lines


def main():
    db = sqlite3.connect(sys.argv[-1])
    with Terminal() as term:
        while True:
            width, height = term.size()
            term.draw(render(db, width)[:height])
            key = term.key(30)
            if key in ('q', KEY_ESC, KEY_CTRL_C):
                break


main()
