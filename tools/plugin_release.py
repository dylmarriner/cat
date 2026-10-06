#!/usr/bin/env python3

"""Build reproducible plugin archives and merge their entries into the catalog."""

import argparse
import hashlib
import json
import os
import re
import stat
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = ROOT / 'kitty' / 'plugin_packages'
RELEASE_TAG = re.compile(r'plugin-(?P<id>[a-z][a-z0-9-]{1,62}[a-z0-9])-v(?P<version>\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?)\Z')
CATALOG_RELEASE_TAG = re.compile(r'plugin-catalog-v(?P<version>\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?)\Z')
VERSION = re.compile(r'(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)(?:-(?P<prerelease>[0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?\Z')


def _version_key(value: str) -> tuple[object, ...]:
    match = VERSION.fullmatch(value)
    if match is None:
        raise ValueError(f'Invalid plugin version: {value!r}')
    prerelease = match['prerelease']
    identifiers = () if prerelease is None else tuple((0, int(x)) if x.isdigit() else (1, x) for x in prerelease.split('.'))
    return int(match['major']), int(match['minor']), int(match['patch']), prerelease is None, identifiers


def _catalog(data: bytes, source: str) -> dict[str, dict[str, object]]:
    try:
        value = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as err:
        raise ValueError(f'{source} is not valid JSON: {err}') from err
    if (
        not isinstance(value, dict)
        or type(value.get('schema_version')) is not int
        or value['schema_version'] != 1
        or not isinstance(value.get('plugins'), list)
    ):
        raise ValueError(f'{source} must use catalog schema version 1')
    entries: dict[str, dict[str, object]] = {}
    for entry in value['plugins']:
        if not isinstance(entry, dict):
            raise ValueError(f'{source} contains a non-object plugin entry')
        plugin_id, version = entry.get('id'), entry.get('version')
        if not isinstance(plugin_id, str) or not re.fullmatch(r'[a-z][a-z0-9-]{1,62}[a-z0-9]', plugin_id):
            raise ValueError(f'{source} contains an invalid plugin ID')
        if plugin_id in entries:
            raise ValueError(f'{source} contains duplicate plugin ID {plugin_id!r}')
        if not isinstance(version, str):
            raise ValueError(f'{source} contains a plugin without a version')
        _version_key(version)
        archive_sha256 = entry.get('archive_sha256')
        if not isinstance(archive_sha256, str) or not re.fullmatch(r'[0-9a-f]{64}', archive_sha256):
            raise ValueError(f'{source} contains an invalid archive SHA-256 for {plugin_id!r}')
        entries[plugin_id] = entry
    return entries


def merge_catalogs(existing: bytes, release: bytes) -> bytes:
    """Merge one release index into the stable catalog without downgrading plugins."""
    entries = _catalog(existing, 'Existing catalog')
    updates = _catalog(release, 'Release catalog')
    for plugin_id, update in updates.items():
        current = entries.get(plugin_id)
        if current is not None:
            update_version = str(update['version'])
            current_version = str(current['version'])
            update_key, current_key = _version_key(update_version), _version_key(current_version)
            if update_key < current_key:
                raise ValueError(f'Release {plugin_id} {update_version} would downgrade catalog version {current_version}')
            if update_key == current_key and update.get('archive_sha256') != current.get('archive_sha256'):
                raise ValueError(f'Release {plugin_id} {update_version} conflicts with the published archive digest')
        entries[plugin_id] = update
    return (json.dumps({'schema_version': 1, 'plugins': [entries[key] for key in sorted(entries)]}, indent=2) + '\n').encode()


def exclude_published_versions(existing: bytes, release: bytes, output_directory: Path) -> bytes:
    """Keep only new plugin versions in a catalog release and remove skipped archives."""
    current = _catalog(existing, 'Existing catalog')
    updates = _catalog(release, 'Release catalog')
    kept = []
    for plugin_id, update in updates.items():
        published = current.get(plugin_id)
        if published is not None:
            new_version, old_version = _version_key(str(update['version'])), _version_key(str(published['version']))
            if new_version < old_version:
                raise ValueError(f'Release {plugin_id} {update["version"]} would downgrade catalog version {published["version"]}')
            if new_version == old_version:
                (output_directory / f'{plugin_id}.zip').unlink(missing_ok=True)
                continue
        kept.append(update)
    if not kept:
        raise ValueError('Catalog release contains no new plugin versions')
    return (json.dumps({'schema_version': 1, 'plugins': kept}, indent=2) + '\n').encode()


def _content_digest(package: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(package.rglob('*')):
        if path.is_symlink():
            raise ValueError(f'Plugin packages cannot contain symlinks: {path}')
        if not path.is_file() or '__pycache__' in path.parts or path.suffix == '.pyc':
            continue
        digest.update(path.relative_to(package).as_posix().encode('utf-8'))
        digest.update(b'\0')
        digest.update(path.read_bytes())
        digest.update(b'\0')
    return digest.hexdigest()


def _build_plugin(repository: str, tag: str, plugin_id: str, version: str, entry: dict[str, object], output_directory: Path) -> tuple[Path, dict[str, object]]:
    package = PACKAGE_ROOT / plugin_id
    manifest_path = package / 'plugin.json'
    if package.is_symlink() or not package.is_dir() or not manifest_path.is_file():
        raise ValueError(f'No bundled package exists for plugin {plugin_id!r}')
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if version != manifest.get('version') or entry.get('version') != version:
        raise ValueError('Release tag must match the bundled plugin id and version')
    for key in ('id', 'name', 'api_versions', 'capabilities', 'source_url', 'license'):
        if entry.get(key) != manifest.get(key):
            raise ValueError(f'Bundled catalog {key} does not match the plugin manifest')
    if entry.get('sha256') != _content_digest(package):
        raise ValueError('Bundled catalog package digest does not match the package files')
    output_directory.mkdir(parents=True, exist_ok=True)
    archive_path = output_directory / f'{plugin_id}.zip'
    files = []
    for path in package.rglob('*'):
        if path.is_file() and '__pycache__' not in path.parts and path.suffix != '.pyc':
            files.append(path)
    if not any(path.name.lower() in {'license', 'license.txt', 'copying'} for path in files):
        raise ValueError(f'Plugin {plugin_id!r} must include its own license text')
    files.sort(key=lambda p: p.relative_to(package).as_posix())
    with zipfile.ZipFile(archive_path, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in files:
            info = zipfile.ZipInfo(path.relative_to(package).as_posix(), (1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            archive.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)

    digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    remote_entry = {key: entry[key] for key in ('id', 'name', 'version', 'description', 'api_versions', 'capabilities', 'source_url', 'license')}
    remote_entry['release_url'] = f'https://github.com/{repository}/releases/download/{tag}/{archive_path.name}'
    remote_entry['archive_sha256'] = digest
    return archive_path, remote_entry


def build_release(repository: str, tag: str, output_directory: Path) -> tuple[Path, Path]:
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository):
        raise ValueError('Repository must use owner/name form')
    bundled = json.loads((PACKAGE_ROOT / 'catalog.json').read_text(encoding='utf-8'))['plugins']
    single = RELEASE_TAG.fullmatch(tag)
    if CATALOG_RELEASE_TAG.fullmatch(tag):
        if not bundled:
            raise ValueError('Cannot publish an empty plugin catalog')
        archives_and_entries = [
            _build_plugin(repository, tag, str(entry['id']), str(entry['version']), entry, output_directory) for entry in bundled
        ]
    elif single is not None:
        plugin_id, version = single['id'], single['version']
        entry = next((x for x in bundled if x.get('id') == plugin_id), None)
        if entry is None:
            raise ValueError('Release tag must match a bundled plugin')
        archives_and_entries = [_build_plugin(repository, tag, plugin_id, version, entry, output_directory)]
    else:
        raise ValueError('Release tag must match plugin-<plugin-id>-v<version> or plugin-catalog-v<version>')
    index_path = output_directory / 'catalog.json'
    index_path.write_text(json.dumps({'schema_version': 1, 'plugins': [entry for _, entry in archives_and_entries]}, indent=2) + '\n', encoding='utf-8')
    return archives_and_entries[0][0], index_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository', default=os.environ.get('GITHUB_REPOSITORY', ''))
    parser.add_argument('--tag', default=os.environ.get('GITHUB_REF_NAME', ''))
    parser.add_argument('--output-directory', type=Path, default=Path('dist/plugins'))
    parser.add_argument('--merge-catalog', type=Path, help='Merge the built entry into this existing catalog before writing catalog.json')
    args = parser.parse_args()
    if not args.repository or not args.tag:
        parser.error('--repository and --tag are required (or set GITHUB_REPOSITORY and GITHUB_REF_NAME)')
    archive, index = build_release(args.repository, args.tag, args.output_directory)
    if args.merge_catalog:
        current = args.merge_catalog.read_bytes()
        release = index.read_bytes()
        if CATALOG_RELEASE_TAG.fullmatch(args.tag):
            release = exclude_published_versions(current, release, args.output_directory)
        merged = merge_catalogs(current, release)
        index.write_bytes(merged)
    print(f'Built {len(tuple(args.output_directory.glob("*.zip")))} archive(s) and {index}')


if __name__ == '__main__':
    main()
