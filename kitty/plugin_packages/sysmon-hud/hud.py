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


import time

BOLD, DIM, RESET = '\x1b[1m', '\x1b[2m', '\x1b[0m'
SPARK = '▁▂▃▄▅▆▇█'


def color_for(fraction):
    r = int(min(1, fraction * 2) * 255)
    g = int(min(1, (1 - fraction) * 2) * 200)
    return f'\x1b[38;2;{r};{g};90m'


def bar(fraction, width):
    fraction = max(0.0, min(1.0, fraction))
    full = fraction * width
    blocks = '█' * int(full) + ' ▏▎▍▌▋▊▉'[int((full - int(full)) * 8)].strip()
    return color_for(fraction) + blocks.ljust(width, '·') + RESET


def cpu_times():
    cores = {}
    with open('/proc/stat') as f:
        for line in f:
            if line.startswith('cpu'):
                name, *values = line.split()
                values = list(map(int, values[:8]))
                cores[name] = (sum(values), values[3] + values[4])
    return cores


def meminfo():
    data = {}
    with open('/proc/meminfo') as f:
        for line in f:
            key, value = line.split(':', 1)
            data[key] = int(value.split()[0]) * 1024
    return data


def net_bytes():
    rx = tx = 0
    with open('/proc/net/dev') as f:
        for line in f.readlines()[2:]:
            name, data = line.split(':', 1)
            if name.strip() == 'lo':
                continue
            fields = data.split()
            rx += int(fields[0])
            tx += int(fields[8])
    return rx, tx


def processes():
    ans = {}
    for pid in os.listdir('/proc'):
        if not pid.isdigit():
            continue
        try:
            with open(f'/proc/{pid}/stat') as f:
                raw = f.read()
        except OSError:
            continue
        name = raw[raw.index('(') + 1 : raw.rindex(')')]
        fields = raw[raw.rindex(')') + 2 :].split()
        ans[int(pid)] = (name, int(fields[11]) + int(fields[12]), int(fields[21]) * os.sysconf('SC_PAGE_SIZE'))
    return ans


def human(n):
    for unit in 'B KB MB GB TB'.split():
        if n < 1024:
            return f'{n:.0f}{unit}' if unit == 'B' else f'{n:.1f}{unit}'
        n /= 1024
    return f'{n:.1f}PB'


def main():
    ticks = os.sysconf('SC_CLK_TCK')
    prev_cpu, prev_net, prev_procs, prev_t = cpu_times(), net_bytes(), processes(), time.monotonic()
    rx_hist, tx_hist = [0.0] * 40, [0.0] * 40
    with Terminal() as term:
        while True:
            key = term.key(1.0)
            if key in ('q', KEY_ESC, KEY_CTRL_C):
                return
            now = time.monotonic()
            dt = max(now - prev_t, 1e-3)
            cpu, net, procs = cpu_times(), net_bytes(), processes()
            width, height = term.size()
            lines = [f'{BOLD}\x1b[38;5;45m◉ System monitor{RESET}  {DIM}{time.strftime("%H:%M:%S")} · q to close{RESET}', '']
            usage = {}
            for name, (total, idle) in cpu.items():
                pt, pi = prev_cpu.get(name, (total, idle))
                usage[name] = 1 - (idle - pi) / max(total - pt, 1)
            bar_w = max(10, width // 2 - 14)
            lines.append(f'{BOLD}CPU{RESET} {bar(usage["cpu"], bar_w * 2 + 9)} {usage["cpu"] * 100:5.1f}%')
            cores = sorted((k for k in usage if k != 'cpu'), key=lambda k: int(k[3:]))
            for i in range(0, len(cores), 2):
                cells = [f'{c[3:]:>3} {bar(usage[c], bar_w)} {usage[c] * 100:4.0f}%' for c in cores[i : i + 2]]
                lines.append('  '.join(cells))
            mem = meminfo()
            used = mem['MemTotal'] - mem['MemAvailable']
            lines.append('')
            lines.append(f'{BOLD}MEM{RESET} {bar(used / mem["MemTotal"], bar_w * 2 + 9)} {human(used)} / {human(mem["MemTotal"])}')
            if mem.get('SwapTotal'):
                swap = mem['SwapTotal'] - mem['SwapFree']
                lines.append(f'{BOLD}SWP{RESET} {bar(swap / mem["SwapTotal"], bar_w * 2 + 9)} {human(swap)} / {human(mem["SwapTotal"])}')
            rx_rate, tx_rate = (net[0] - prev_net[0]) / dt, (net[1] - prev_net[1]) / dt
            rx_hist, tx_hist = rx_hist[1:] + [rx_rate], tx_hist[1:] + [tx_rate]
            top = max(max(rx_hist), max(tx_hist), 1)
            spark = lambda h: ''.join(SPARK[min(7, int(v / top * 7.99))] for v in h)
            lines.append('')
            lines.append(f'{BOLD}NET{RESET} \x1b[38;5;78m↓ {spark(rx_hist)} {human(rx_rate)}/s{RESET}')
            lines.append(f'    \x1b[38;5;213m↑ {spark(tx_hist)} {human(tx_rate)}/s{RESET}')
            load = os.getloadavg()
            lines.append('')
            lines.append(f'{BOLD}LOAD{RESET} {load[0]:.2f} {load[1]:.2f} {load[2]:.2f}   {DIM}{len(procs)} processes{RESET}')
            lines.append('')
            lines.append(f'{BOLD}{"PID":>7}  {"CPU%":>6}  {"MEM":>8}  NAME{RESET}')
            rows = []
            for pid, (name, cpu_ticks, rss) in procs.items():
                before = prev_procs.get(pid)
                delta = cpu_ticks - before[1] if before else 0
                rows.append((delta / ticks / dt * 100, pid, name, rss))
            for pct, pid, name, rss in sorted(rows, reverse=True)[: max(3, height - len(lines) - 1)]:
                lines.append(f'{pid:>7}  {color_for(min(pct / 100, 1))}{pct:6.1f}{RESET}  {human(rss):>8}  {name}')
            term.draw(lines[:height])
            prev_cpu, prev_net, prev_procs, prev_t = cpu, net, procs, now


main()
