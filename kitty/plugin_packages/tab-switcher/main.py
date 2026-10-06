def setup(api):
    def switch(context, _args):
        tabs = context.tabs()
        if not tabs:
            return
        entries = [(str(tab['id']), f"{'● ' if tab['is_active'] else ''}{tab['title']}") for tab in tabs]

        def focus(value):
            if value:
                context.focus_tab(int(value))

        context.choose('Switch tab', entries, focus)

    api.register_command('switch', switch, 'Find and focus a kitty tab by title')
    api.contribute_ui('Switch tab', 'switch')
