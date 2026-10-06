def setup(api):
    effect = api.shader_effect('warp-screensaver.pipeline')
    enabled = [True]

    def toggle(context, _args):
        enabled[0] = not enabled[0]
        effect.show(enabled[0])

    api.register_command('toggle', toggle, 'Turn the warp screensaver on or off')
    api.contribute_ui('Toggle warp screensaver', 'toggle')
