def setup(api):
    def run(context, args):
        cwd = None
        try:
            cwd = context.window_info()['cwd'] or None
        except Exception:
            pass

        context.run_app('hud.py', list(args), title='System monitor HUD', cwd=cwd)

    api.register_command('open', run, 'Open the system monitor overlay')
    api.contribute_ui('System monitor HUD', 'open')
