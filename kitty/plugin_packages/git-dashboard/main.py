def setup(api):
    def run(context, args):
        cwd = None
        try:
            cwd = context.window_info()['cwd'] or None
        except Exception:
            pass

        context.run_app('dashboard.py', list(args), title='Git dashboard', cwd=cwd)

    api.register_command('open', run, 'Open the Git dashboard overlay')
    api.contribute_ui('Git dashboard', 'open')
