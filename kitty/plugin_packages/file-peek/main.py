def setup(api):
    def run(context, args):
        cwd = None
        try:
            cwd = context.window_info()['cwd'] or None
        except Exception:
            pass

        window_id = context.current_window_id

        def on_result(text):
            if text and window_id is not None:
                context.send_text(window_id, text)

        context.run_app('peek.py', list(args), title='File peek', cwd=cwd, on_result=on_result)

    api.register_command('open', run, 'Browse files with a preview')
    api.contribute_ui('File peek', 'open')
