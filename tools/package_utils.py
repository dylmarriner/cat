from collections.abc import Iterable
from pathlib import Path

KITTY_SOURCE = Path(__file__).resolve().parents[1] / 'kitty'


def package_source_ignore(parent: str, entries: Iterable[str]) -> list[str]:
    source = Path(parent).resolve()
    if source.is_relative_to(KITTY_SOURCE):
        relative = source.relative_to(KITTY_SOURCE).as_posix()
    else:
        relative = ''
    if relative == 'plugin_packages' or relative.startswith('plugin_packages/'):
        return [x for x in entries if x == '__pycache__' or x.endswith(('.pyc', '.pyo'))]
    allowed_extensions = frozenset('py slang pipeline glsl so'.split())
    return [x for x in entries if '.' in x and x.rpartition('.')[2] not in allowed_extensions]
