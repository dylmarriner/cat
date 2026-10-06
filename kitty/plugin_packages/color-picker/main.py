def setup(api):
    def pick(context, _args):
        def on_result(text):
            if text:
                context.clipboard(text)
                context.notify('🎨 Color copied', text)

        context.run_app('picker.py', title='Color picker', on_result=on_result)

    api.register_command('pick', pick, 'Pick a color and copy it')
    api.contribute_ui('Color picker', 'pick')
