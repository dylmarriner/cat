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

SCORES = os.path.join(os.environ.get('KITTY_PLUGIN_DATA', '.'), 'snake.json')
DIRECTIONS = {KEY_UP: (0, -1), 'w': (0, -1), KEY_DOWN: (0, 1), 's': (0, 1), KEY_LEFT: (-1, 0), 'a': (-1, 0), KEY_RIGHT: (1, 0), 'd': (1, 0)}


def best_score():
    try:
        with open(SCORES, encoding='utf-8') as f:
            return int(json.load(f)['best'])
    except (OSError, ValueError, KeyError, TypeError):
        return 0


def save_best(score):
    os.makedirs(os.path.dirname(SCORES) or '.', exist_ok=True)
    with open(SCORES, 'w', encoding='utf-8') as f:
        json.dump({'best': score}, f)


def play(term, best):
    width, height = term.size()
    cols, rows = max(10, (width - 2) // 2), max(6, height - 3)
    snake = [(cols // 2 - i, rows // 2) for i in range(4)]
    direction, pending = (1, 0), (1, 0)
    occupied = set(snake)
    food = random.choice([(x, y) for x in range(cols) for y in range(rows) if (x, y) not in occupied])
    score, paused = 0, False
    next_tick = time.monotonic()
    while True:
        delay = max(0.045, 0.12 - len(snake) * 0.002)
        key = term.key(max(0.0, next_tick - time.monotonic()))
        if key in ('q', KEY_ESC, KEY_CTRL_C):
            return score, 'quit'
        if key == ' ':
            paused = not paused
        if key == 'r':
            return score, 'restart'
        if key in DIRECTIONS and DIRECTIONS[key] != (-direction[0], -direction[1]):
            pending = DIRECTIONS[key]
        if time.monotonic() < next_tick or paused:
            continue
        next_tick = time.monotonic() + delay
        direction = pending
        head = (snake[0][0] + direction[0], snake[0][1] + direction[1])
        if not (0 <= head[0] < cols and 0 <= head[1] < rows) or head in snake[:-1]:
            return score, 'dead'
        snake.insert(0, head)
        if head == food:
            score += 10
            free = [(x, y) for x in range(cols) for y in range(rows) if (x, y) not in snake]
            if not free:
                return score, 'won'
            food = random.choice(free)
        else:
            snake.pop()
        grid = [['  '] * cols for _ in range(rows)]
        pulse = 160 + int(95 * abs((time.monotonic() * 2) % 2 - 1))
        grid[food[1]][food[0]] = f'\x1b[38;2;255;{pulse // 3};{pulse // 2}m●\x1b[0m '
        for i, (x, y) in enumerate(snake):
            f = i / max(1, len(snake) - 1)
            r, g, b = int(40 + 40 * f), int(230 - 120 * f), int(160 + 80 * f)
            grid[y][x] = f'\x1b[48;2;{r};{g};{b}m  \x1b[0m'
        border = '\x1b[38;5;240m'
        lines = [
            f'\x1b[1m🐍 Snake\x1b[0m  score \x1b[1;33m{score}\x1b[0m  best {max(best, score)}  \x1b[2mspace pause · r restart · q quit\x1b[0m',
            border + '┌' + '──' * cols + '┐\x1b[0m',
        ]
        lines += [border + '│\x1b[0m' + ''.join(row) + border + '│\x1b[0m' for row in grid]
        lines.append(border + '└' + '──' * cols + '┘\x1b[0m')
        term.draw(lines)


def main():
    best = best_score()
    with Terminal() as term:
        while True:
            score, outcome = play(term, best)
            if score > best:
                best = score
                save_best(best)
            if outcome == 'quit':
                return
            if outcome in ('dead', 'won'):
                message = '🏆 You filled the board!' if outcome == 'won' else '💥 Game over'
                term.draw(['', f'   \x1b[1m{message}\x1b[0m   score {score} · best {best}', '', '   \x1b[2mr to play again · q to quit\x1b[0m'])
                while (key := term.key()) not in ('r', 'q', KEY_ESC, KEY_CTRL_C):
                    pass
                if key != 'r':
                    return


main()
