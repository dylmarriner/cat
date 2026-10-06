MOODS = {
    'clean': (0.1, 0.85, 0.35),
    'dirty': (1.0, 0.65, 0.05),
    'conflict': (1.0, 0.08, 0.08),
    'ahead': (0.65, 0.35, 1.0),
    'detached': (0.15, 0.5, 1.0),
}


def classify(porcelain):
    lines = porcelain.splitlines()
    headers = {l.split(' ', 2)[1]: l.split(' ', 2)[2] for l in lines if l.startswith('# ') and len(l.split(' ', 2)) == 3}
    entries = [l for l in lines if l and not l.startswith('#')]
    if any(l.startswith('u ') for l in entries):
        return 'conflict'
    if entries:
        return 'dirty'
    if headers.get('branch.head') == '(detached)':
        return 'detached'
    ahead = headers.get('branch.ab', '+0 -0').split()[0]
    if ahead != '+0':
        return 'ahead'
    return 'clean'


def git_status_command(cwd):
    return ['git', '-C', cwd, 'status', '--porcelain=v2', '--branch']


def mood_of(output):
    # judge by the output, exit codes are not reliable inside kitty, which reaps all child processes
    return classify(output) if '# branch.oid' in output else None


def setup(api):
    effect = api.shader_effect('git-mood.pipeline')
    effect.show(False)
    focused = [None]

    def update(window_id):
        try:
            cwd = api.window_info(window_id)['cwd']
        except Exception:
            return
        if not cwd:
            return

        def done(error, result):
            if error is None and focused[0] == window_id:
                mood = mood_of(result.stdout)
                if mood is None:
                    effect.set(0, 0)
                else:
                    effect.set(0, *MOODS[mood], 1.0)
                effect.show(mood is not None)

        api.run_process(git_status_command(cwd), done, timeout=10)

    def on_focus(event):
        focused[0] = event.window_id
        if event.window_id is not None:
            update(event.window_id)

    def on_finished(event):
        if event.window_id == focused[0]:
            update(event.window_id)

    api.subscribe('window_focused', on_focus)
    api.subscribe('command_finished', on_finished)
