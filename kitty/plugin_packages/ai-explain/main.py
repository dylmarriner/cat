import json
import os
import platform
import shutil
import tempfile

MODEL = 'claude-opus-5-5'
SCREEN_CHARS = 12000
CLI_TIMEOUT = 180
CLI_LOCATIONS = ('~/.local/bin/claude', '~/.claude/local/claude', '/usr/local/bin/claude', '/usr/bin/claude')


def claude_cli():
    found = shutil.which('claude')
    if found:
        return found
    for candidate in CLI_LOCATIONS:
        path = os.path.expanduser(candidate)
        if os.access(path, os.X_OK):
            return path
    return None


def cli_command(cli, system):
    # Isolated print mode: no tools, hooks, MCP servers or user/project settings,
    # so the answer depends only on this prompt. Authenticates with the user's
    # existing Claude Code login.
    return [
        cli,
        '-p',
        '--output-format',
        'json',
        '--tools',
        '',
        '--no-session-persistence',
        '--setting-sources',
        'local',
        '--settings',
        '{"disableAllHooks": true}',
        '--strict-mcp-config',
        '--system-prompt',
        system,
    ]


def parse_cli_output(stdout, stderr):
    # Exit codes are not reliable inside kitty, which reaps all child
    # processes, so judge success by the JSON result alone.
    try:
        answer = json.loads(stdout)
    except ValueError:
        answer = {}
    if not isinstance(answer, dict):
        answer = {}
    text = str(answer.get('result') or '').strip()
    if not text or answer.get('is_error'):
        detail = (text or stderr or stdout).strip()[:300] or 'no output'
        raise RuntimeError(f'Claude Code failed: {detail}')
    return text


def ask_claude_api(system, prompt, max_tokens):
    try:
        import anthropic
    except ImportError as err:
        raise RuntimeError('Install Claude Code (the claude command) or the anthropic Python package') from err
    client = anthropic.Anthropic()
    response = client.beta.messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        betas=['server-side-fallback-2026-07-01'],
        fallbacks='default',
        output_config={'effort': 'low'},
        system=system,
        messages=[{'role': 'user', 'content': prompt}],
    )
    if response.stop_reason == 'refusal':
        raise RuntimeError('Claude declined this request')
    text = ''.join(block.text for block in response.content if block.type == 'text').strip()
    if not text:
        raise RuntimeError('Claude returned an empty answer')
    return text


def ask_claude(api, system, prompt, done, max_tokens=4000):
    """Ask Claude without blocking kitty, then call done(error, answer).
    Prefers the Claude Code CLI, which uses the existing Claude login."""
    cli = claude_cli()
    if cli is None:
        api.run_in_background(lambda: ask_claude_api(system, prompt, max_tokens), done)
        return

    def finished(error, result):
        if error is None:
            try:
                answer = parse_cli_output(result.stdout, result.stderr)
            except Exception as err:
                error, answer = err, None
        else:
            answer = None
        done(error, answer)

    env = {k: v for k, v in os.environ.items() if k != 'CLAUDECODE'}
    api.run_process(cli_command(cli, system), finished, input=prompt, cwd=tempfile.gettempdir(), env=env, timeout=CLI_TIMEOUT)


def environment(cwd):
    shell = os.path.basename(os.environ.get('SHELL', 'sh'))
    return f'Operating system: {platform.system()} {platform.release()}\nShell: {shell}\nWorking directory: {cwd}'


def single_command(text):
    """Strip Markdown fences and keep the first command line of an answer."""
    lines = [l.strip() for l in text.strip().splitlines() if l.strip() and not l.strip().startswith('```')]
    return lines[0].removeprefix('$ ') if lines else ''


def track_commands(api):
    """Remember the last command and its exit code for every window."""
    last = {}

    def started(event):
        if event.window_id is not None:
            last[event.window_id] = {'cmdline': event.cmdline, 'exit_code': None}

    def finished(event):
        if event.window_id is not None:
            last[event.window_id] = {'cmdline': event.cmdline, 'exit_code': event.exit_code}

    api.subscribe('command_started', started)
    api.subscribe('command_finished', finished)
    api.subscribe('window_closed', lambda event: last.pop(event.window_id, None))
    return last


SYSTEM = (
    'You are a senior engineer helping someone at their terminal. You are shown the visible terminal screen and the last '
    'command they ran. Explain the actual cause of the problem shown, briefly, then give the concrete fix. Use short '
    'Markdown: a one line diagnosis, then a "Fix" section with the exact commands in fenced code blocks. If nothing is '
    'wrong, say what the output means.'
)


def setup(api):
    last = track_commands(api)

    def explain(context, _args):
        window_id = context.current_window_id
        if window_id is None:
            return
        info = context.window_info()
        screen = context.read_screen(window_id)[-SCREEN_CHARS:]
        command = last.get(window_id, {})
        prompt = (
            f'{environment(info["cwd"])}\nLast command: {command.get("cmdline") or "unknown"}\n'
            f'Exit code: {command.get("exit_code", "unknown")}\n\nTerminal screen:\n```\n{screen}\n```'
        )
        context.set_tab_title('🤖 thinking…')
        answer_path = os.path.join(context.data_directory, 'answer.md')

        def done(error, answer):
            context.set_tab_title('', window_id=window_id)
            with open(answer_path, 'w', encoding='utf-8') as f:
                f.write(f'# Something went wrong\n\n{error}' if error else answer)

            def copied(text):
                if text:
                    context.clipboard(text)

            context.run_app('pager.py', [answer_path], title='Claude explains', on_result=copied)

        ask_claude(context, SYSTEM, prompt, done)

    api.register_command('explain', explain, 'Ask Claude to explain what is on screen')
    api.contribute_ui('Explain this screen with Claude', 'explain')
