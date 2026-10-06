import os
import subprocess


def parse_worktrees(data):
    records = []
    current = {}
    for token in data.split('\0'):
        if not token:
            if current.get('path'):
                records.append(current)
            current = {}
        elif token.startswith('worktree '):
            current['path'] = token[9:]
        elif token.startswith('branch '):
            current['branch'] = token[7:].removeprefix('refs/heads/')
        elif token == 'detached':
            current['branch'] = '(detached)'
    if current.get('path'):
        records.append(current)
    return records


def setup(api):
    def switch(context, _args):
        cwd = context.window_info()['cwd']
        result = subprocess.run(
            ['git', '-C', cwd, 'worktree', 'list', '--porcelain', '-z'],
            capture_output=True,
            check=True,
            text=True,
            timeout=5,
        )
        worktrees = parse_worktrees(result.stdout)
        if not worktrees:
            return
        entries = []
        paths = {}
        for worktree in worktrees:
            path = worktree['path']
            branch = worktree.get('branch', '(unknown)')
            label = f'{branch} — {path}'
            entries.append((path, label))
            paths[path] = worktree

        def open_path(path):
            if not path:
                return
            shell = os.environ.get('SHELL') or os.environ.get('COMSPEC') or '/bin/sh'
            branch = paths[path].get('branch', os.path.basename(path))
            context.launch([shell], cwd=path, tab_title=branch)

        context.choose('Open Git worktree', entries, open_path)

    api.register_command('switch', switch, 'Open a Git worktree in a new kitty tab')
    api.contribute_ui('Open Git worktree', 'switch')
