#!/usr/bin/env python
# License: GPL v3 Copyright: 2026, Kovid Goyal <kovid at kovidgoyal.net>

import sys
from typing import Any

from kittens.tui.handler import result_handler
from kitty.boss import Boss
from kitty.config import prepare_config_file_for_editing
from kitty.settings import revert_settings, save_settings

help_text = 'Browse and edit kitty configuration settings in a searchable overlay.'
usage = ''
OPTIONS = ''.format


def main(args: list[str]) -> None:
    raise SystemExit('The settings overlay must be opened from a running kitty instance')


@result_handler()
def handle_result(args: list[str], data: dict[str, Any], target_window_id: int, boss: Boss) -> None:
    action = data.get('action')
    try:
        if action == 'plugin_action':
            plugin_action = data.get('plugin_action')
            plugin_id = data.get('plugin_id', '')
            if not isinstance(plugin_action, str) or not isinstance(plugin_id, str):
                raise ValueError('The settings overlay returned an invalid plugin action')
            boss.settings_plugin_action(plugin_action, plugin_id, target_window_id)
        elif action == 'edit':
            boss.edit_config_file()
        elif action == 'reload':
            boss.load_config_file()
        elif action == 'revert':
            if revert_settings(prepare_config_file_for_editing()):
                boss.load_config_file()
        elif action == 'save':
            raw_changes = data.get('changes', {})
            if not isinstance(raw_changes, dict):
                raise ValueError('The settings overlay returned invalid changes')
            changes: dict[str, str | tuple[str, ...]] = {}
            for name, value in raw_changes.items():
                if not isinstance(name, str):
                    raise ValueError('The settings overlay returned an invalid setting name')
                if isinstance(value, str):
                    changes[name] = value
                elif isinstance(value, list) and all(isinstance(x, str) for x in value):
                    changes[name] = tuple(value)
                else:
                    raise ValueError(f'The settings overlay returned an invalid value for {name}')
            raw_plugin_changes = data.get('plugin_changes', {})
            if not isinstance(raw_plugin_changes, dict):
                raise ValueError('The settings overlay returned invalid plugin changes')
            plugin_changes: dict[str, dict[str, dict[str, str]]] = {}
            for plugin_id, pages in raw_plugin_changes.items():
                if not isinstance(plugin_id, str) or not isinstance(pages, dict):
                    raise ValueError('The settings overlay returned invalid plugin settings')
                plugin_changes[plugin_id] = {}
                for page_id, fields in pages.items():
                    if (
                        not isinstance(page_id, str)
                        or not isinstance(fields, dict)
                        or not all(isinstance(k, str) and isinstance(v, str) for k, v in fields.items())
                    ):
                        raise ValueError('The settings overlay returned invalid plugin setting values')
                    plugin_changes[plugin_id][page_id] = fields
            for plugin_id, pages in plugin_changes.items():
                boss.plugin_manager.validate_settings(plugin_id, pages)
            if changes:
                save_settings(prepare_config_file_for_editing(), changes)
                boss.load_config_file()
            for plugin_id, pages in plugin_changes.items():
                boss.plugin_manager.update_settings(plugin_id, pages)
    except Exception as err:
        boss.show_error('Settings update failed', str(err))


if __name__ == '__main__':
    main(sys.argv)
elif __name__ == '__doc__':
    cd = sys.cli_docs  # type: ignore
    cd['usage'] = usage
    cd['options'] = OPTIONS
    cd['help_text'] = help_text
    cd['short_desc'] = help_text
