#!/usr/bin/env python
# License: GPL v3 Copyright: 2026, Kovid Goyal <kovid at kovidgoyal.net>

"""Host-API port of the mode-aware scrolling behavior from kitty-smart-scroll."""

from collections.abc import Sequence

from kitty.plugins import PluginContext

KEYS = {
    'scroll_line_up': 'ctrl+alt+up',
    'scroll_line_down': 'ctrl+alt+down',
    'scroll_page_up': 'ctrl+alt+page_up',
    'scroll_page_down': 'ctrl+alt+page_down',
    'scroll_home': 'ctrl+alt+home',
    'scroll_end': 'ctrl+alt+end',
}


def smart_scroll(api: PluginContext, args: Sequence[str]) -> None:
    if len(args) != 2:
        raise ValueError('smart_scroll requires a kitty scroll action and a key name')
    action, key = args
    if api.scroll_window(action):
        api.send_key(key)


def setup(api: PluginContext) -> None:
    api.register_command('smart_scroll', smart_scroll, 'Scroll kitty history or forward the key to the application screen')
    for action, key in KEYS.items():
        api.add_key_mapping(key, 'smart_scroll', action, key)
