#!/usr/bin/env python
# License: GPL v3 Copyright: 2026, Kovid Goyal <kovid at kovidgoyal.net>

"""Helpers for settings UIs backed by kitty's canonical option definitions."""

from collections.abc import Mapping, Sequence
from typing import Any

from kitty.conf.types import Unset
from kitty.config import atomic_save, parse_config
from kitty.constants import is_macos
from kitty.options.definition import definition

BEGIN_MARKER = '# BEGIN KITTY SETTINGS UI'
END_MARKER = '# END KITTY SETTINGS UI'


def settings_metadata() -> list[dict[str, Any]]:
    """Return editable option metadata without maintaining a second schema."""
    ans: list[dict[str, Any]] = []

    def walk(group: Any, parents: tuple[str, ...] = ()) -> None:
        from kitty.conf.types import Group, MultiOption, Option

        for item in group:
            if isinstance(item, Group):
                walk(item, parents + (item.title,))
            elif isinstance(item, Option):
                default = item.macos_defval if is_macos and not isinstance(item.macos_defval, Unset) else item.defval_as_string
                entry: dict[str, Any] = {
                    'name': item.name,
                    'group': parents,
                    'type': item.ctype or item.parser_func.__name__,
                    'value_type': item.parser_func.__name__,
                    'default': default,
                    'choices': item.choices,
                    'help': item.long_text,
                    'multiple': False,
                    'restart_required': (
                        'only take effect after a kitty restart' in item.long_text.lower() or 'require a full restart of kitty' in item.long_text.lower()
                    ),
                }
                if not isinstance(item.macos_defval, Unset):
                    entry['platform_defaults'] = {'macos': item.macos_defval}
                ans.append(entry)
            elif isinstance(item, MultiOption):
                ans.append(
                    {
                        'name': item.name,
                        'group': parents,
                        'type': item.ctype or item.parser_func.__name__,
                        'value_type': item.parser_func.__name__,
                        'default': tuple(x.defval_as_str for x in item.items if x.add_to_default),
                        'choices': (),
                        'help': item.long_text,
                        'multiple': True,
                        'restart_required': (
                            'only take effect after a kitty restart' in item.long_text.lower() or 'require a full restart of kitty' in item.long_text.lower()
                        ),
                    }
                )

    walk(definition.root_group)
    return ans


def settings_ui_data(config_paths: Sequence[str]) -> dict[str, Any]:
    from .config import effective_config_lines, effective_config_sources

    metadata = settings_metadata()
    current: dict[str, list[str]] = {}
    multi_names = {item['name'] for item in metadata if item['multiple']}
    known_names = {item['name'] for item in metadata}
    for line in effective_config_lines:
        parts = line.split(maxsplit=1)
        if not parts:
            continue
        name = parts[0]
        value = parts[1] if len(parts) > 1 else ''
        name = name.removeprefix('+')
        if name not in known_names:
            continue
        if name in multi_names:
            current.setdefault(name, []).append(value)
        else:
            current[name] = [value]
    for item in metadata:
        item['current'] = current.get(item['name'], [])
        item['source'] = effective_config_sources.get(item['name'], '')
    return {'settings': metadata, 'source_files': tuple(config_paths)}


def _settings_block_bounds(existing: str, path: str) -> tuple[int, int] | None:
    lines = existing.splitlines(keepends=True)
    marker_lines = [line.rstrip('\r\n') for line in lines]
    begin_positions = [i for i, line in enumerate(marker_lines) if line == BEGIN_MARKER]
    end_positions = [i for i, line in enumerate(marker_lines) if line == END_MARKER]
    if len(begin_positions) != len(end_positions) or len(begin_positions) > 1:
        raise ValueError(f'Malformed settings UI block in {path}')
    if not begin_positions:
        return None
    begin_line, end_line = begin_positions[0], end_positions[0]
    if end_line < begin_line:
        raise ValueError(f'Malformed settings UI block in {path}')
    return sum(map(len, lines[:begin_line])), sum(map(len, lines[: end_line + 1]))


def revert_settings(path: str) -> bool:
    """Remove the settings UI block, revealing the values it overrode."""
    import os

    try:
        with open(path, encoding='utf-8') as f:
            existing = f.read()
    except FileNotFoundError:
        return False
    bounds = _settings_block_bounds(existing, path)
    if bounds is None:
        return False
    start, end = bounds
    atomic_save((existing[:start] + existing[end:]).encode('utf-8'), os.path.abspath(path))
    return True


def save_settings(path: str, values: Mapping[str, str | Sequence[str]]) -> None:
    """Replace the UI-owned config block after validating it with kitty's parser."""
    import os

    from kitty.conf.utils import BadLine

    known = {**definition.option_map, **definition.multi_option_map}
    try:
        with open(path, encoding='utf-8') as f:
            existing = f.read()
    except FileNotFoundError:
        existing = ''
    bounds = _settings_block_bounds(existing, path)
    preserved: dict[str, list[str]] = {}
    if bounds:
        block = existing[bounds[0] : bounds[1]].splitlines()[1:-1]
        changed = set(values)
        for line in block:
            parts = line.split(maxsplit=1)
            if parts and parts[0] not in changed:
                preserved.setdefault(parts[0], []).append(parts[1] if len(parts) > 1 else '')
    merged: dict[str, str | Sequence[str]] = dict(preserved)
    merged.update(values)

    lines = [BEGIN_MARKER]
    for name, value in merged.items():
        if name not in known:
            raise ValueError(f'Unknown kitty setting: {name}')
        if isinstance(value, str):
            vals = (value,)
        else:
            vals = tuple(value)
        if name in definition.option_map and len(vals) != 1:
            raise ValueError(f'{name} accepts exactly one value')
        if name in definition.option_map and vals[0] == '':
            continue
        for val in vals:
            if not isinstance(val, str) or '\n' in val or '\r' in val:
                raise ValueError(f'Invalid value for {name}: setting values must be single-line strings')
            if name in definition.multi_option_map and not val:
                raise ValueError(f'Invalid value for {name}: repeated values cannot be empty')
            lines.append(f'{name} {val}'.rstrip())
    lines.append(END_MARKER)

    bad_lines: list[BadLine] = []
    parse_config(lines[1:-1], accumulate_bad_lines=bad_lines, allow_geninclude=False)
    if bad_lines:
        details = '; '.join(f'line {x.number}: {x.exception}' for x in bad_lines)
        raise ValueError(f'Invalid kitty settings: {details}')

    if bounds:
        start, end = bounds
        updated = existing[:start] + '\n'.join(lines) + '\n' + existing[end:]
    else:
        updated = existing.rstrip('\n')
        updated += ('\n\n' if updated else '') + '\n'.join(lines) + '\n'

    atomic_save(updated.encode('utf-8'), os.path.abspath(path))
