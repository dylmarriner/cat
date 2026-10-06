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


import subprocess

BOLD, DIM, RESET = '\x1b[1m', '\x1b[2m', '\x1b[0m'
GREEN, RED, YELLOW, CYAN, MAGENTA = '\x1b[32m', '\x1b[31m', '\x1b[33m', '\x1b[36m', '\x1b[35m'


def git(*args):
    return subprocess.run(['git', *args], capture_output=True, text=True, timeout=10).stdout


def numstat(*args):
    stats = {}
    for line in git('diff', '--numstat', *args).splitlines():
        added, removed, path = line.split('\t', 2)
        stats[path] = (added, removed)
    return stats


def render(width, height):
    if subprocess.run(['git', 'rev-parse'], capture_output=True).returncode:
        return [f'{RED}Not inside a Git repository: {os.getcwd()}{RESET}', '', 'Press q to close.']
    lines = []
    status = git('status', '--porcelain=v2', '--branch', '--untracked-files=normal').splitlines()
    head = {l.split(' ', 2)[1]: l.split(' ', 2)[2] for l in status if l.startswith('# ') and l.count(' ') >= 2}
    branch = head.get('branch.head', '?')
    top = os.path.basename(git('rev-parse', '--show-toplevel').strip())
    title = f'{BOLD}{CYAN}⎇  {top}{RESET} on {BOLD}{MAGENTA}{branch}{RESET}'
    if 'branch.upstream' in head:
        ahead, behind = head.get('branch.ab', '+0 -0').split()
        title += f'  {DIM}→ {head["branch.upstream"]}{RESET}  {GREEN}↑{ahead[1:]}{RESET} {RED}↓{behind[1:]}{RESET}'
    stashes = len(git('stash', 'list').splitlines())
    if stashes:
        title += f'  {YELLOW}⚑ {stashes} stash{"es" if stashes > 1 else ""}{RESET}'
    lines += [title, f'{DIM}r refresh · q close{RESET}', '']
    staged_stats, unstaged_stats = numstat('--cached'), numstat()
    staged, changed, untracked, conflicts = [], [], [], []
    for line in status:
        if line.startswith(('1 ', '2 ')):
            xy, path = line.split(' ')[1], line.split(' ', 8)[-1].split('\t')[0]
            if xy[0] != '.':
                staged.append((xy[0], path))
            if xy[1] != '.':
                changed.append((xy[1], path))
        elif line.startswith('u '):
            conflicts.append(line.split(' ', 10)[-1])
        elif line.startswith('? '):
            untracked.append(line[2:])

    def section(name, color, items, stats):
        if not items:
            return
        lines.append(f'{BOLD}{color}{name} ({len(items)}){RESET}')
        for code, path in items[:12]:
            a, r = stats.get(path, ('', ''))
            delta = f'  {GREEN}+{a}{RESET} {RED}-{r}{RESET}' if a else ''
            lines.append(f'  {color}{code}{RESET} {path}{delta}')
        if len(items) > 12:
            lines.append(f'  {DIM}… {len(items) - 12} more{RESET}')
        lines.append('')

    section('Conflicts', RED, [('U', p) for p in conflicts], {})
    section('Staged', GREEN, staged, staged_stats)
    section('Changed', YELLOW, changed, unstaged_stats)
    section('Untracked', DIM, [('?', p) for p in untracked], {})
    if not (staged or changed or untracked or conflicts):
        lines += [f'{GREEN}✔ Working tree clean{RESET}', '']
    lines.append(f'{BOLD}History{RESET}')
    graph = git(
        'log',
        '--graph',
        '--color=always',
        '--date=relative',
        f'-n{max(5, height - len(lines) - 1)}',
        '--format=%C(yellow)%h%Creset %C(auto)%d%Creset %s %C(dim)· %an, %ar%Creset',
    )
    lines += [l[: width * 3] for l in graph.splitlines()]
    return lines


def main():
    with Terminal() as term:
        while True:
            width, height = term.size()
            term.draw(render(width, height)[:height])
            key = term.key(10)
            if key in ('q', KEY_ESC, KEY_CTRL_C):
                break


main()
