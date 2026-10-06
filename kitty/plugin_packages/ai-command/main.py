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
    'You turn a request into exactly one shell command line for the given operating system, shell and directory. '
    'Reply with only that command: no explanation, no Markdown, no leading $. Prefer standard tools. If the request '
    'is destructive, still give the command but make it as safe as possible, for example with interactive flags.'
)


def setup(api):
    def ask(context, _args):
        window_id = context.current_window_id
        if window_id is None:
            return
        cwd = context.window_info()['cwd']

        def requested(text):
            if not text.strip():
                return
            context.set_tab_title('🤖 thinking…')

            def done(error, answer):
                context.set_tab_title('', window_id=window_id)
                if error:
                    raise error
                command = single_command(answer)
                if command:
                    context.send_text(window_id, command)

            ask_claude(context, SYSTEM, f'{environment(cwd)}\n\nRequest: {text.strip()}', done, 1000)

        context.prompt('What should the command do?', requested)

    api.register_command('ask', ask, 'Describe a command in plain words and get it typed')
    api.contribute_ui('Write a command with Claude', 'ask')
