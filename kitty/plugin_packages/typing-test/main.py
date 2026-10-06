def setup(api):
    api.register_command('start', lambda context, _args: context.run_app('typing.py', title='Typing test'), 'Start a typing test')
    api.contribute_ui('Typing test', 'start')
