def setup(api):
    api.register_command('play', lambda context, _args: context.run_app('snake.py', title='Snake'), 'Play snake in an overlay')
    api.contribute_ui('Play snake', 'play')
