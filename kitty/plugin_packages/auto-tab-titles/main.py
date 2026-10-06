import os
import re

ICONS = (
    (r'python\d*(\.\d+)?|pip\d*|uv|poetry|pytest|ipython', '🐍'),
    (r'cargo|rustc|rustup', '🦀'),
    (r'go', '🐹'),
    (r'node|npm|npx|pnpm|yarn|bun|deno|tsc|vite', '⬢'),
    (r'docker|podman|docker-compose', '🐳'),
    (r'kubectl|k9s|helm|kubectx', '⎈'),
    (r'ssh|mosh|autossh|et', '🌐'),
    (r'n?vim?|vi|nano|emacs|hx|micro|code', '📝'),
    (r'git|lazygit|tig|gh', '⎇'),
    (r'make|cmake|ninja|meson|bazel|gradle|mvn', '🔨'),
    (r'top|htop|btop|glances', '📈'),
    (r'man|less|more|bat', '📖'),
    (r'psql|mysql|sqlite3|redis-cli|mongosh', '🛢'),
    (r'curl|wget|http|xh', '📡'),
)
WRAPPERS = {'sudo', 'doas', 'env', 'time', 'nice', 'nohup', 'exec', 'command'}


def split_command(cmdline):
    words = cmdline.strip().split()
    while words and (words[0] in WRAPPERS or re.fullmatch(r'\w+=\S*', words[0]) or (words[0].startswith('-') and len(words) > 1)):
        words.pop(0)
    return words


def running_title(cmdline):
    words = split_command(cmdline)
    if not words:
        return ''
    program = os.path.basename(words[0])
    icon = next((i for pattern, i in ICONS if re.fullmatch(pattern, program)), '▶')
    if icon == '🌐':
        host = next((w for w in words[1:] if not w.startswith('-')), program)
        return f'{icon} {host.split("@")[-1]}'
    detail = next((w for w in words[1:] if not w.startswith('-')), '')
    detail = os.path.basename(detail.rstrip('/')) if '/' in detail else detail
    return f'{icon} {program} {detail[:24]}'.strip()


def repo_command(cwd):
    return ['git', '-C', cwd, 'rev-parse', '--show-toplevel', '--abbrev-ref', 'HEAD']


def idle_title(cwd, output):
    # judge by the output, exit codes are not reliable inside kitty, which reaps all child processes
    top, branch = (output.splitlines() + ['', ''])[:2]
    if top.startswith('/'):
        return f'{os.path.basename(top)} ⎇ {branch}'
    home = os.path.expanduser('~')
    return '🏠 ~' if cwd == home else f'📁 {os.path.basename(cwd) or cwd}'


def setup(api):
    def on_started(event):
        title = running_title(event.cmdline)
        if title and event.window_id is not None:
            api.set_tab_title(title, window_id=event.window_id)

    def on_finished(event):
        window_id = event.window_id
        try:
            cwd = api.window_info(window_id)['cwd']
        except Exception:
            return
        if cwd:

            def done(error, result):
                if error is None:
                    api.set_tab_title(idle_title(cwd, result.stdout), window_id=window_id)

            api.run_process(repo_command(cwd), done, timeout=10)

    api.subscribe('command_started', on_started)
    api.subscribe('command_finished', on_finished)
