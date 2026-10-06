#!/usr/bin/env python3

"""Build a reproducible ZIP and catalog entry for the bundled smart-scroll plugin."""

import argparse
import hashlib
import json
import os
import re
import stat
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / 'kitty' / 'plugin_packages' / 'smart-scroll'
MANIFEST = PACKAGE / 'plugin.json'


def build_release(repository: str, tag: str, output_directory: Path) -> tuple[Path, Path]:
    manifest = json.loads(MANIFEST.read_text(encoding='utf-8'))
    catalog = json.loads((PACKAGE.parent / 'catalog.json').read_text(encoding='utf-8'))
    entry = next((x for x in catalog['plugins'] if x.get('id') == manifest['id']), None)
    if entry is None or tag != f'plugin-{manifest["id"]}-v{manifest["version"]}':
        raise ValueError('Release tag must match the bundled plugin id and version')
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository):
        raise ValueError('Repository must use owner/name form')

    output_directory.mkdir(parents=True, exist_ok=True)
    archive_path = output_directory / f'{manifest["id"]}.zip'
    files = []
    for path in PACKAGE.rglob('*'):
        if path.is_symlink():
            raise ValueError(f'Plugin packages cannot contain symlinks: {path}')
        if path.is_file() and '__pycache__' not in path.parts and path.suffix != '.pyc':
            files.append(path)
    files.sort(key=lambda p: p.relative_to(PACKAGE).as_posix())
    files.append(ROOT / 'LICENSE')
    with zipfile.ZipFile(archive_path, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in files:
            name = path.relative_to(ROOT if path.name == 'LICENSE' else PACKAGE).as_posix()
            info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            archive.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)

    digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    remote_entry = {key: entry[key] for key in ('id', 'name', 'version', 'description', 'api_versions', 'capabilities', 'source_url', 'license')}
    remote_entry['release_url'] = f'https://github.com/{repository}/releases/download/{tag}/{archive_path.name}'
    remote_entry['archive_sha256'] = digest
    index_path = output_directory / 'catalog.json'
    index_path.write_text(json.dumps({'schema_version': 1, 'plugins': [remote_entry]}, indent=2) + '\n', encoding='utf-8')
    return archive_path, index_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository', default=os.environ.get('GITHUB_REPOSITORY', ''))
    parser.add_argument('--tag', default=os.environ.get('GITHUB_REF_NAME', ''))
    parser.add_argument('--output-directory', type=Path, default=Path('dist/plugins'))
    args = parser.parse_args()
    if not args.repository or not args.tag:
        parser.error('--repository and --tag are required (or set GITHUB_REPOSITORY and GITHUB_REF_NAME)')
    archive, index = build_release(args.repository, args.tag, args.output_directory)
    print(f'Built {archive} and {index}')


if __name__ == '__main__':
    main()
