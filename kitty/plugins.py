#!/usr/bin/env python
# License: GPL v3 Copyright: 2026, Kovid Goyal <kovid at kovidgoyal.net>

"""Versioned in-process extension host for explicitly enabled kitty plugins."""

import hashlib
import importlib.util
import io
import json
import math
import os
import re
import shutil
import stat
import sys
import tempfile
import zipfile
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath, PureWindowsPath
from types import ModuleType
from typing import Any
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .config import atomic_save

PLUGIN_API_VERSION = 1
PLUGIN_ID_PATTERN = re.compile(r'^[a-z][a-z0-9-]{1,62}[a-z0-9]$')
PLUGIN_NAME_PATTERN = re.compile(r'^[a-z][a-z0-9_-]{0,63}$')
LICENSE_PATTERN = re.compile(r'^[A-Za-z0-9.+-]{1,128}$')
CAPABILITIES = frozenset({'commands', 'settings', 'events', 'key_mappings', 'ui', 'terminal', 'screen', 'scroll'})
EVENTS = frozenset({'window_focused', 'window_created', 'window_closed', 'child_exited', 'settings_changed'})
SCROLL_ACTIONS = frozenset({'scroll_line_up', 'scroll_line_down', 'scroll_page_up', 'scroll_page_down', 'scroll_home', 'scroll_end'})
MAX_CATALOG_BYTES = 1 << 20
MAX_PLUGIN_ARCHIVE_BYTES = 32 << 20
MAX_PLUGIN_UNPACKED_BYTES = 128 << 20
MAX_PLUGIN_ARCHIVE_FILES = 512


class PluginError(ValueError):
    pass


def _valid_https_url(url: str) -> bool:
    try:
        parsed = urlsplit(url)
        return parsed.scheme == 'https' and bool(parsed.hostname) and parsed.username is None and parsed.password is None and not any(ord(c) < 32 for c in url)
    except ValueError:
        return False


class _HTTPSRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> Any:
        if not _valid_https_url(newurl):
            raise PluginError('HTTPS request redirected to an invalid or insecure URL')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _open_https_url(request: Request, timeout: int) -> Any:
    return build_opener(_HTTPSRedirectHandler).open(request, timeout=timeout)


def _normalize_settings_page(page_id: str, page: Mapping[str, Any]) -> dict[str, Any]:
    if not PLUGIN_NAME_PATTERN.fullmatch(page_id):
        raise PluginError(f'Invalid plugin settings page id: {page_id!r}')
    title = page.get('title')
    fields = page.get('fields')
    if not isinstance(title, str) or not title.strip() or len(title) > 128:
        raise PluginError('A plugin settings page needs a title of 1 to 128 characters')
    if not isinstance(fields, Sequence) or isinstance(fields, (str, bytes)):
        raise PluginError('Settings page fields must be a sequence')
    validated: list[dict[str, Any]] = []
    seen: set[str] = set()
    for field_data in fields:
        if not isinstance(field_data, Mapping):
            raise PluginError('Each plugin setting must be an object')
        key, label, kind = field_data.get('key'), field_data.get('label'), field_data.get('type')
        if not all(isinstance(x, str) and x for x in (key, label, kind)) or key in seen:
            raise PluginError('Each plugin setting needs a unique key, label, and type')
        if not PLUGIN_NAME_PATTERN.fullmatch(key) or len(label) > 128:
            raise PluginError('Setting keys must be identifiers and labels cannot exceed 128 characters')
        if kind not in {'string', 'integer', 'float', 'boolean', 'choice'}:
            raise PluginError(f'Unsupported plugin setting type: {kind}')
        seen.add(key)
        defaults: dict[str, Any] = {'string': '', 'integer': 0, 'float': 0.0, 'boolean': False, 'choice': ''}
        default = field_data.get('default', defaults[kind])
        if kind == 'string' and not isinstance(default, str):
            raise PluginError(f'Default for {key} must be a string')
        if kind == 'integer' and (not isinstance(default, int) or isinstance(default, bool)):
            raise PluginError(f'Default for {key} must be an integer')
        if kind == 'float' and (not isinstance(default, (int, float)) or isinstance(default, bool) or not math.isfinite(default)):
            raise PluginError(f'Default for {key} must be a finite number')
        if kind == 'boolean' and not isinstance(default, bool):
            raise PluginError(f'Default for {key} must be a boolean')
        choices = field_data.get('choices', [])
        if kind == 'choice':
            if not isinstance(choices, list) or not choices or any(not isinstance(x, str) for x in choices):
                raise PluginError(f'Choice setting {key} needs a non-empty string choices array')
            if default not in choices:
                raise PluginError(f'Default for {key} must be one of its choices')
        elif choices:
            raise PluginError(f'Only choice settings can declare choices ({key})')
        validated.append({'key': key, 'label': label, 'type': kind, 'default': default, 'choices': choices})
    return {'id': page_id, 'title': title.strip(), 'fields': validated}


@dataclass(frozen=True)
class PluginManifest:
    plugin_id: str
    name: str
    version: str
    api_versions: tuple[int, ...]
    entry_point: str
    capabilities: frozenset[str]
    settings_pages: tuple[dict[str, Any], ...]
    source_url: str
    license: str
    directory: Path

    @classmethod
    def read(cls, directory: str | os.PathLike[str]) -> 'PluginManifest':
        base = Path(directory).resolve(strict=True)
        manifest_path = base / 'plugin.json'
        try:
            raw = json.loads(manifest_path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError) as err:
            raise PluginError(f'Cannot read plugin manifest {manifest_path}: {err}') from err
        if not isinstance(raw, dict):
            raise PluginError('Plugin manifest must be a JSON object')
        plugin_id = raw.get('id')
        name = raw.get('name')
        version = raw.get('version')
        entry_point = raw.get('entry_point')
        api_versions = raw.get('api_versions')
        capabilities = raw.get('capabilities', [])
        settings = raw.get('settings')
        source_url = raw.get('source_url', '')
        license_name = raw.get('license', '')
        if not isinstance(plugin_id, str) or not PLUGIN_ID_PATTERN.fullmatch(plugin_id):
            raise PluginError('Plugin id must be a lowercase kebab-case identifier')
        if not isinstance(name, str) or not name.strip() or len(name) > 128:
            raise PluginError('Plugin name must contain 1 to 128 characters')
        if not isinstance(source_url, str) or (source_url and not _valid_https_url(source_url)):
            raise PluginError('source_url must be an HTTPS URL when present')
        if not isinstance(license_name, str) or (license_name and not LICENSE_PATTERN.fullmatch(license_name)):
            raise PluginError('license must be a short SPDX-style identifier when present')
        if not isinstance(version, str) or not re.fullmatch(r'\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?', version):
            raise PluginError('Plugin version must use semantic version syntax')
        if not isinstance(entry_point, str) or not entry_point or Path(entry_point).is_absolute():
            raise PluginError('Plugin entry_point must be a relative Python file path')
        entry = (base / entry_point).resolve(strict=True)
        if not entry.is_relative_to(base) or not entry.is_file() or entry.suffix != '.py':
            raise PluginError('Plugin entry_point must resolve to a Python file inside the plugin directory')
        if not isinstance(api_versions, list) or not api_versions or any(type(x) is not int for x in api_versions):
            raise PluginError('api_versions must be a non-empty array of integers')
        if not isinstance(capabilities, list) or any(not isinstance(x, str) for x in capabilities):
            raise PluginError('capabilities must be an array of strings')
        requested = frozenset(capabilities)
        unknown = requested - CAPABILITIES
        if unknown:
            raise PluginError(f'Unknown plugin capabilities: {", ".join(sorted(unknown))}')
        if not isinstance(settings, list):
            raise PluginError('settings must be an array of settings page declarations')
        settings_pages: list[dict[str, Any]] = []
        page_ids: set[str] = set()
        for page in settings:
            if not isinstance(page, dict) or not isinstance(page.get('id'), str):
                raise PluginError('Each settings page needs an id')
            page_id = page['id']
            if page_id in page_ids:
                raise PluginError(f'Duplicate settings page id: {page_id}')
            page_ids.add(page_id)
            settings_pages.append(_normalize_settings_page(page_id, page))
        if settings_pages and 'settings' not in requested:
            raise PluginError('Settings pages require the settings capability')
        return cls(plugin_id, name, version, tuple(api_versions), entry_point, requested, tuple(settings_pages), source_url, license_name, base)


@dataclass(frozen=True)
class PluginEvent:
    name: str
    window_id: int | None = None
    tab_id: int | None = None
    title: str = ''
    exit_code: int | None = None


@dataclass(frozen=True)
class PluginCommand:
    plugin_id: str
    name: str
    description: str


@dataclass
class _LoadedPlugin:
    manifest: PluginManifest
    module: ModuleType
    context: 'PluginContext | None'
    granted_capabilities: frozenset[str]
    commands: dict[str, tuple[PluginCommand, Callable[['PluginContext', Sequence[str]], None]]] = field(default_factory=dict)
    settings_pages: dict[str, dict[str, Any]] = field(default_factory=dict)
    key_mappings: list[tuple[str, str, tuple[str, ...]]] = field(default_factory=list)
    ui_contributions: list[tuple[str, str]] = field(default_factory=list)
    cleanups: list[Callable[[], None]] = field(default_factory=list)


class PluginContext:
    """The stable host surface passed to a plugin's ``setup(api)`` function."""

    def __init__(self, host: 'PluginManager', loaded: _LoadedPlugin):
        self._host = host
        self._loaded = loaded
        self._window_id: int | None = None

    @property
    def plugin_id(self) -> str:
        return self._loaded.manifest.plugin_id

    @property
    def plugin_version(self) -> str:
        return self._loaded.manifest.version

    @property
    def api_version(self) -> int:
        return PLUGIN_API_VERSION

    @property
    def config_directory(self) -> str:
        return str(self._host.config_directory)

    def register_command(
        self,
        name: str,
        callback: Callable[['PluginContext', Sequence[str]], None],
        description: str,
    ) -> None:
        self._host._require_capability(self._loaded, 'commands')
        if not PLUGIN_NAME_PATTERN.fullmatch(name) or not callable(callback):
            raise PluginError(f'Invalid plugin command: {name!r}')
        if not isinstance(description, str) or not description.strip():
            raise PluginError('Plugin commands need a description')
        if name in self._loaded.commands:
            raise PluginError(f'Duplicate plugin command: {name}')
        command = PluginCommand(self.plugin_id, name, description.strip())
        self._loaded.commands[name] = (command, callback)

    def register_settings_page(self, page_id: str, page: Mapping[str, Any]) -> None:
        self._host._require_capability(self._loaded, 'settings')
        if page_id in self._loaded.settings_pages:
            raise PluginError(f'Invalid or duplicate settings page id: {page_id!r}')
        normalized = _normalize_settings_page(page_id, page)
        declared = {x['id']: x for x in self._loaded.manifest.settings_pages}
        if declared.get(page_id) != normalized:
            raise PluginError(f'Settings page {page_id!r} does not match plugin.json')
        self._loaded.settings_pages[page_id] = normalized

    def add_key_mapping(self, key: str, command: str, *args: str) -> None:
        self._host._require_capability(self._loaded, 'key_mappings')
        if not isinstance(key, str) or not key.strip() or command not in self._loaded.commands:
            raise PluginError('A plugin key mapping needs a key and a registered command')
        self._loaded.key_mappings.append((key.strip(), command, tuple(args)))

    def subscribe(self, event: str, callback: Callable[[PluginEvent], None]) -> None:
        self._host._require_capability(self._loaded, 'events')
        if event not in EVENTS or not callable(callback):
            raise PluginError(f'Unsupported plugin event: {event!r}')
        callbacks = self._host._callbacks[event]
        callbacks.append((self.plugin_id, callback))
        self._loaded.cleanups.append(lambda: callbacks.remove((self.plugin_id, callback)))

    def contribute_ui(self, label: str, command: str) -> None:
        self._host._require_capability(self._loaded, 'ui')
        if not isinstance(label, str) or not label.strip() or command not in self._loaded.commands:
            raise PluginError('A UI contribution needs a label and a registered command')
        self._loaded.ui_contributions.append((label.strip(), command))

    def on_disable(self, callback: Callable[[], None]) -> None:
        if not callable(callback):
            raise PluginError('Plugin cleanup handler must be callable')
        self._loaded.cleanups.append(callback)

    def read_screen(self, window_id: int) -> str:
        self._host._require_capability(self._loaded, 'screen')
        if self._host.screen_reader is None:
            raise PluginError('Screen access is not available in this host context')
        return self._host.screen_reader(window_id)

    def send_text(self, window_id: int, text: str) -> None:
        self._host._require_capability(self._loaded, 'terminal')
        if self._host.terminal_writer is None:
            raise PluginError('Terminal input is not available in this host context')
        if not isinstance(text, str):
            raise PluginError('Terminal input must be a string')
        self._host.terminal_writer(window_id, text)

    @property
    def current_window_id(self) -> int | None:
        """The kitty window whose action invoked the current plugin command."""
        return self._window_id

    def send_key(self, *keys: str, window_id: int | None = None) -> None:
        self._host._require_capability(self._loaded, 'terminal')
        if self._host.key_writer is None:
            raise PluginError('Key input is not available in this host context')
        target = self._window_id if window_id is None else window_id
        if target is None or not keys or any(not isinstance(key, str) or not key for key in keys):
            raise PluginError('Sending keys needs a live window and one or more key names')
        self._host.key_writer(target, tuple(keys))

    def scroll_window(self, action: str, window_id: int | None = None) -> bool | None:
        self._host._require_capability(self._loaded, 'scroll')
        if action not in SCROLL_ACTIONS:
            raise PluginError(f'Unsupported plugin scroll action: {action!r}')
        if self._host.scroll_handler is None:
            raise PluginError('Window scrolling is not available in this host context')
        target = self._window_id if window_id is None else window_id
        if target is None:
            raise PluginError('Scrolling needs a live kitty window')
        return self._host.scroll_handler(target, action)


class PluginManager:
    """Load only plugins listed as enabled and trusted in the local state file."""

    state_filename = 'plugins.json'

    def __init__(
        self,
        config_directory: str | os.PathLike[str],
        on_change: Callable[[], None] | None = None,
        screen_reader: Callable[[int], str] | None = None,
        terminal_writer: Callable[[int, str], None] | None = None,
        scroll_handler: Callable[[int, str], bool | None] | None = None,
        key_writer: Callable[[int, tuple[str, ...]], None] | None = None,
    ):
        self.config_directory = Path(config_directory).resolve()
        self.on_change = on_change
        self.screen_reader = screen_reader
        self.terminal_writer = terminal_writer
        self.scroll_handler = scroll_handler
        self.key_writer = key_writer
        self.plugins_directory = self.config_directory / 'plugins'
        self.state_path = self.plugins_directory / self.state_filename
        self.loaded: dict[str, _LoadedPlugin] = {}
        self.errors: dict[str, str] = {}
        self._callbacks: dict[str, list[tuple[str, Callable[[PluginEvent], None]]]] = defaultdict(list)
        self._remote_catalog_url = ''
        self._remote_catalog: dict[str, dict[str, Any]] = {}

    @property
    def api_version(self) -> int:
        return PLUGIN_API_VERSION

    def remote_catalog_entries(self) -> tuple[dict[str, Any], ...]:
        if self._remote_catalog_url != self.catalog_url():
            return ()
        return tuple(dict(item) for item in self._remote_catalog.values())

    @staticmethod
    def bundled_plugins_directory() -> Path:
        return Path(__file__).with_name('plugin_packages')

    def catalog_url(self) -> str:
        try:
            return (self.plugins_directory / 'catalog-url').read_text(encoding='utf-8').strip()
        except FileNotFoundError:
            return ''

    def set_catalog_url(self, url: str) -> None:
        url = url.strip()
        if len(url) > 2048 or not _valid_https_url(url):
            raise PluginError('Plugin catalog URL must use HTTPS and include a host')
        os.makedirs(self.plugins_directory, exist_ok=True)
        atomic_save((url + '\n').encode('utf-8'), str(self.plugins_directory / 'catalog-url'))
        self._remote_catalog_url = url
        self._remote_catalog.clear()

    @staticmethod
    def _fetch_url(url: str, limit: int, accept: str) -> bytes:
        if not _valid_https_url(url):
            raise PluginError('Catalog and plugin release URLs must use HTTPS')
        request = Request(url, headers={'Accept': accept, 'User-Agent': 'kitty-plugin-host/1'})
        try:
            with _open_https_url(request, timeout=15) as response:
                if not _valid_https_url(response.geturl()):
                    raise PluginError('HTTPS request redirected to an invalid or insecure URL')
                length = response.headers.get('Content-Length')
                if length and int(length) > limit:
                    raise PluginError(f'Download exceeds the {limit}-byte limit')
                data = response.read(limit + 1)
        except PluginError:
            raise
        except Exception as err:
            raise PluginError(f'HTTPS download failed: {err}') from err
        if len(data) > limit:
            raise PluginError(f'Download exceeds the {limit}-byte limit')
        return data

    @staticmethod
    def fetch_remote_catalog_data(url: str) -> bytes:
        return PluginManager._fetch_url(url, MAX_CATALOG_BYTES, 'application/json')

    def load_remote_catalog(self, url: str, data: bytes) -> tuple[dict[str, Any], ...]:
        if url != self.catalog_url():
            raise PluginError('Plugin catalog URL changed while the catalog was loading')
        if not url:
            raise PluginError('No remote plugin catalog URL has been configured')
        try:
            catalog = json.loads(data)
        except (UnicodeDecodeError, json.JSONDecodeError) as err:
            raise PluginError(f'Remote plugin catalog is not valid JSON: {err}') from err
        if (
            not isinstance(catalog, dict)
            or type(catalog.get('schema_version')) is not int
            or catalog['schema_version'] != 1
            or not isinstance(catalog.get('plugins'), list)
        ):
            raise PluginError('Remote plugin catalog has an unsupported schema')
        entries: dict[str, dict[str, Any]] = {}
        for item in catalog['plugins']:
            if not isinstance(item, dict):
                raise PluginError('Each remote catalog entry must be an object')
            plugin_id = item.get('id')
            name = item.get('name')
            version = item.get('version')
            description = item.get('description', '')
            api_versions = item.get('api_versions')
            capabilities = item.get('capabilities')
            source_url = item.get('source_url')
            license_name = item.get('license')
            release_url = item.get('release_url')
            archive_sha256 = item.get('archive_sha256')
            if not isinstance(plugin_id, str) or not PLUGIN_ID_PATTERN.fullmatch(plugin_id) or plugin_id in entries:
                raise PluginError('Remote catalog plugin IDs must be valid and unique')
            if not isinstance(name, str) or not name.strip() or len(name) > 128:
                raise PluginError(f'{plugin_id} has an invalid name')
            if not isinstance(version, str) or not re.fullmatch(r'\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?', version):
                raise PluginError(f'{plugin_id} has an invalid version')
            if not isinstance(description, str) or len(description) > 512 or any(ord(c) < 32 and c not in '\t' for c in description):
                raise PluginError(f'{plugin_id} has an invalid description')
            if not isinstance(api_versions, list) or not api_versions or any(type(x) is not int for x in api_versions):
                raise PluginError(f'{plugin_id} has invalid api_versions')
            if not isinstance(capabilities, list) or any(x not in CAPABILITIES for x in capabilities) or len(capabilities) != len(set(capabilities)):
                raise PluginError(f'{plugin_id} has invalid capabilities')
            if not isinstance(source_url, str) or not _valid_https_url(source_url):
                raise PluginError(f'{plugin_id} must have an HTTPS upstream source URL')
            if not isinstance(license_name, str) or not LICENSE_PATTERN.fullmatch(license_name):
                raise PluginError(f'{plugin_id} must declare a license')
            if not isinstance(release_url, str) or not _valid_https_url(release_url):
                raise PluginError(f'{plugin_id} must have an HTTPS release URL')
            if not isinstance(archive_sha256, str) or not re.fullmatch(r'[0-9a-f]{64}', archive_sha256):
                raise PluginError(f'{plugin_id} has an invalid release archive SHA-256')
            entries[plugin_id] = {
                'id': plugin_id,
                'name': name.strip(),
                'version': version,
                'description': description,
                'api_versions': tuple(api_versions),
                'capabilities': tuple(sorted(capabilities)),
                'source_url': source_url,
                'license': license_name,
                'release_url': release_url,
                'archive_sha256': archive_sha256,
                'compatible': PLUGIN_API_VERSION in api_versions,
                'catalog_url': url,
            }
        self._remote_catalog_url, self._remote_catalog = url, entries
        return tuple(entries.values())

    def fetch_remote_catalog(self) -> tuple[dict[str, Any], ...]:
        url = self.catalog_url()
        if not url:
            raise PluginError('No remote plugin catalog URL has been configured')
        return self.load_remote_catalog(url, self.fetch_remote_catalog_data(url))

    def cached_remote_catalog_plugin(self, plugin_id: str) -> dict[str, Any]:
        if self._remote_catalog_url != self.catalog_url():
            raise PluginError('Refresh the plugin catalog before selecting a release')
        try:
            return dict(self._remote_catalog[plugin_id])
        except KeyError as err:
            raise PluginError(f'No plugin named {plugin_id!r} is present in the loaded remote catalog') from err

    def remote_catalog_plugin(self, plugin_id: str) -> dict[str, Any]:
        if self._remote_catalog_url != self.catalog_url():
            self.fetch_remote_catalog()
        try:
            return dict(self._remote_catalog[plugin_id])
        except KeyError as err:
            raise PluginError(f'No plugin named {plugin_id!r} is present in the remote catalog') from err

    def install_remote_plugin(self, plugin_id: str, expected_archive_sha256: str, archive_data: bytes | None = None) -> dict[str, Any]:
        return self._install_remote_plugin(plugin_id, expected_archive_sha256, update=False, archive_data=archive_data)

    def update_remote_plugin(self, plugin_id: str, expected_archive_sha256: str, archive_data: bytes | None = None) -> dict[str, Any]:
        return self._install_remote_plugin(plugin_id, expected_archive_sha256, update=True, archive_data=archive_data)

    @staticmethod
    def download_remote_plugin_archive(url: str) -> bytes:
        return PluginManager._fetch_url(url, MAX_PLUGIN_ARCHIVE_BYTES, 'application/zip')

    def _install_remote_plugin(self, plugin_id: str, expected_archive_sha256: str, *, update: bool, archive_data: bytes | None = None) -> dict[str, Any]:
        entry = self.cached_remote_catalog_plugin(plugin_id) if archive_data is not None else self.remote_catalog_plugin(plugin_id)
        if not entry['compatible']:
            raise PluginError(f'{plugin_id} does not support plugin API version {PLUGIN_API_VERSION}')
        if entry['archive_sha256'] != expected_archive_sha256:
            raise PluginError('Remote plugin catalog changed after the installation review')
        target = self.plugins_directory / plugin_id
        if update:
            unsafe = target.is_symlink() or (
                target.exists() and (not target.is_dir() or target.resolve(strict=True).parent != self.plugins_directory.resolve(strict=False))
            )
            if unsafe:
                raise PluginError('Plugin directory must be a direct child of the configured plugin directory')
            if not target.is_dir():
                raise PluginError(f'Plugin {plugin_id} is not installed')
        elif target.exists() or target.is_symlink():
            raise PluginError(f'Plugin {plugin_id} is already installed')
        if archive_data is None:
            archive_data = self.download_remote_plugin_archive(entry['release_url'])
        archive_digest = hashlib.sha256(archive_data).hexdigest()
        if archive_digest != entry['archive_sha256']:
            raise PluginError('Plugin release archive SHA-256 did not match the catalog')
        os.makedirs(self.plugins_directory, exist_ok=True)
        temp_root = Path(tempfile.mkdtemp(prefix='.kitty-plugin-install-', dir=self.plugins_directory))
        staged = temp_root / plugin_id
        backup = temp_root / 'previous'
        try:
            staged.mkdir()
            self._extract_plugin_archive(archive_data, staged)
            manifest = PluginManifest.read(staged)
            if (
                manifest.plugin_id != plugin_id
                or manifest.name != entry['name']
                or manifest.version != entry['version']
                or manifest.api_versions != entry['api_versions']
                or tuple(sorted(manifest.capabilities)) != entry['capabilities']
                or manifest.source_url != entry['source_url']
                or manifest.license != entry['license']
            ):
                raise PluginError('Plugin release manifest does not match the remote catalog')
            package_digest = self._content_digest(staged)
            if not update and (target.exists() or target.is_symlink()):
                raise PluginError(f'Plugin {plugin_id} is already installed')
            if update:
                state = self._read_state()
                if target.exists():
                    os.rename(target, backup)
                try:
                    os.rename(staged, target)
                    record = state['plugins'].get(plugin_id)
                    if isinstance(record, dict):
                        record['enabled'] = False
                    self._write_state(state)
                except Exception:
                    if target.exists():
                        shutil.rmtree(target)
                    if backup.exists():
                        os.rename(backup, target)
                    raise
                self.disable(plugin_id)
                if self.on_change is not None:
                    self.on_change()
            else:
                os.rename(staged, target)
        finally:
            shutil.rmtree(temp_root, ignore_errors=True)
        return {
            **entry,
            'source': str(target),
            'content_digest': package_digest,
            'enabled': False,
            'approval_required': True,
            'error': '',
        }

    @staticmethod
    def _extract_plugin_archive(data: bytes, destination: Path) -> None:
        try:
            archive = zipfile.ZipFile(io.BytesIO(data))
        except (OSError, zipfile.BadZipFile) as err:
            raise PluginError(f'Plugin release is not a valid ZIP archive: {err}') from err
        with archive:
            infos = archive.infolist()
            if not infos or len(infos) > MAX_PLUGIN_ARCHIVE_FILES:
                raise PluginError('Plugin release has an invalid number of archive entries')
            files: list[tuple[zipfile.ZipInfo, tuple[str, ...]]] = []
            manifest_roots: list[tuple[str, ...]] = []
            total_declared_size = 0
            for info in infos:
                name = info.filename
                windows_name = PureWindowsPath(name)
                raw_name = name[:-1] if info.is_dir() and name.endswith('/') else name
                raw_parts = tuple(raw_name.split('/'))
                if '\\' in name or name.startswith('/') or windows_name.drive or windows_name.root:
                    raise PluginError('Plugin release contains an unsafe archive path')
                if not raw_parts or any(part in ('', '.', '..') or len(part) > 255 for part in raw_parts):
                    raise PluginError('Plugin release contains an unsafe archive path')
                for part in raw_parts:
                    stem = part.split('.', 1)[0].upper()
                    is_windows_device_name = stem in {'CON', 'PRN', 'AUX', 'NUL'} or re.fullmatch(r'(?:COM|LPT)[1-9]', stem)
                    if any(c in part for c in '<>:"|?*') or part.endswith(('.', ' ')) or is_windows_device_name:
                        raise PluginError('Plugin release contains a path that is unsafe on Windows')
                mode = info.external_attr >> 16
                if stat.S_ISLNK(mode) or (mode and not info.is_dir() and stat.S_IFMT(mode) not in (0, stat.S_IFREG)):
                    raise PluginError('Plugin release cannot contain symlinks or special files')
                if info.flag_bits & 1:
                    raise PluginError('Encrypted plugin releases are not supported')
                if info.is_dir():
                    continue
                total_declared_size += info.file_size
                if total_declared_size > MAX_PLUGIN_UNPACKED_BYTES:
                    raise PluginError('Plugin release expands beyond the unpacked size limit')
                if raw_parts[-1] == 'plugin.json':
                    manifest_roots.append(raw_parts[:-1])
                files.append((info, raw_parts))
            if len(manifest_roots) != 1:
                raise PluginError('Plugin release must contain exactly one plugin.json')
            root_parts = manifest_roots[0]
            normalized: set[str] = set()
            total_written = 0
            for info, parts in files:
                if parts[: len(root_parts)] != root_parts:
                    raise PluginError('Plugin release contains files outside its package directory')
                rel_parts = parts[len(root_parts) :]
                if not rel_parts:
                    raise PluginError('Invalid package root')
                relative_name = PurePosixPath(*rel_parts).as_posix()
                if relative_name.casefold() in normalized:
                    raise PluginError('Plugin release contains duplicate file paths')
                normalized.add(relative_name.casefold())
                target = destination.joinpath(*rel_parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                written = 0
                with archive.open(info) as source, target.open('xb') as output:
                    while chunk := source.read(64 * 1024):
                        written += len(chunk)
                        total_written += len(chunk)
                        if written > info.file_size or total_written > MAX_PLUGIN_UNPACKED_BYTES:
                            raise PluginError('Plugin release expands beyond its declared size')
                        output.write(chunk)
                if written != info.file_size:
                    raise PluginError('Plugin release entry size did not match its ZIP directory')

    def bundled_plugins(self) -> tuple[dict[str, Any], ...]:
        root = self.bundled_plugins_directory()
        try:
            catalog = json.loads((root / 'catalog.json').read_text(encoding='utf-8'))
        except (FileNotFoundError, OSError, json.JSONDecodeError) as err:
            self.report_error('catalog', f'Cannot read bundled plugin catalog: {err}')
            return ()
        if (
            not isinstance(catalog, dict)
            or type(catalog.get('schema_version')) is not int
            or catalog['schema_version'] != 1
            or not isinstance(catalog.get('plugins'), list)
        ):
            self.report_error('catalog', 'Bundled plugin catalog has an unsupported schema')
            return ()
        ans: list[dict[str, Any]] = []
        seen: set[str] = set()
        for entry in catalog['plugins']:
            try:
                if not isinstance(entry, dict):
                    raise PluginError('Each bundled catalog entry must be an object')
                plugin_id = entry.get('id')
                package = entry.get('package')
                expected_digest = entry.get('sha256')
                source_url = entry.get('source_url')
                license_name = entry.get('license')
                if not isinstance(plugin_id, str) or not PLUGIN_ID_PATTERN.fullmatch(plugin_id) or plugin_id in seen:
                    raise PluginError('Bundled catalog plugin IDs must be valid and unique')
                seen.add(plugin_id)
                if package != plugin_id:
                    raise PluginError('Bundled plugin packages must be named after their plugin ID')
                if not isinstance(expected_digest, str) or not re.fullmatch(r'[0-9a-f]{64}', expected_digest):
                    raise PluginError(f'{plugin_id} has an invalid SHA-256 digest in the bundled catalog')
                if not isinstance(source_url, str) or not _valid_https_url(source_url):
                    raise PluginError(f'{plugin_id} must have an HTTPS upstream source URL')
                if not isinstance(license_name, str) or not LICENSE_PATTERN.fullmatch(license_name):
                    raise PluginError(f'{plugin_id} must declare a license')
                description = entry.get('description', '')
                if not isinstance(description, str) or len(description) > 512 or any(ord(c) < 32 and c not in '\t' for c in description):
                    raise PluginError(f'{plugin_id} has an invalid catalog description')
                directory = root / package
                if directory.is_symlink() or directory.resolve(strict=True).parent != root.resolve(strict=True):
                    raise PluginError('Bundled plugin packages must be direct, non-symlink children')
                manifest = PluginManifest.read(directory)
                if manifest.plugin_id != plugin_id or manifest.name != entry.get('name') or manifest.version != entry.get('version'):
                    raise PluginError(f'{plugin_id} catalog metadata does not match its plugin manifest')
                if list(manifest.api_versions) != entry.get('api_versions'):
                    raise PluginError(f'{plugin_id} catalog API versions do not match its plugin manifest')
                if manifest.source_url != source_url or manifest.license != license_name:
                    raise PluginError(f'{plugin_id} catalog source or license does not match its plugin manifest')
                if PLUGIN_API_VERSION not in manifest.api_versions:
                    raise PluginError(f'{manifest.plugin_id} does not support API version {PLUGIN_API_VERSION}')
                if list(sorted(manifest.capabilities)) != entry.get('capabilities'):
                    raise PluginError(f'{plugin_id} catalog capabilities do not match its plugin manifest')
                actual_digest = self._content_digest(directory)
                if actual_digest != expected_digest:
                    raise PluginError(f'{plugin_id} package digest does not match the bundled catalog')
                ans.append(
                    {
                        'id': manifest.plugin_id,
                        'name': manifest.name,
                        'version': manifest.version,
                        'source': str(directory),
                        'source_url': source_url,
                        'description': description,
                        'license': license_name,
                        'capabilities': tuple(sorted(manifest.capabilities)),
                        'content_digest': actual_digest,
                    }
                )
            except Exception as err:
                self.report_error(entry.get('id', 'catalog') if isinstance(entry, dict) else 'catalog', f'Bundled package is invalid: {err}')
        return tuple(ans)

    def install_bundled_plugin(self, plugin_id: str) -> dict[str, Any]:
        if not PLUGIN_ID_PATTERN.fullmatch(plugin_id):
            raise PluginError('Invalid plugin id')
        catalog_entry = next((item for item in self.bundled_plugins() if item['id'] == plugin_id), None)
        if catalog_entry is None:
            raise PluginError(f'No valid bundled catalog entry for plugin {plugin_id}')
        source = self.bundled_plugins_directory() / plugin_id
        if source.resolve(strict=True).parent != self.bundled_plugins_directory().resolve(strict=True):
            raise PluginError('Bundled plugins must be direct children of the package directory')
        manifest = PluginManifest.read(source)
        if manifest.plugin_id != plugin_id:
            raise PluginError('Plugin manifest id does not match its directory')
        if PLUGIN_API_VERSION not in manifest.api_versions:
            raise PluginError(f'{plugin_id} does not support API version {PLUGIN_API_VERSION}')
        expected_digest = self._content_digest(source)
        os.makedirs(self.plugins_directory, exist_ok=True)
        target = self.plugins_directory / plugin_id
        if target.exists() or target.is_symlink():
            raise PluginError(f'Plugin {plugin_id} is already installed')
        temp_root = Path(tempfile.mkdtemp(prefix='.kitty-plugin-install-', dir=self.plugins_directory))
        staged = temp_root / plugin_id
        try:
            shutil.copytree(source, staged, symlinks=True)
            if self._content_digest(staged) != expected_digest:
                raise PluginError('Bundled plugin changed while it was being installed')
            staged_manifest = PluginManifest.read(staged)
            if staged_manifest.plugin_id != plugin_id or staged_manifest.version != manifest.version:
                raise PluginError('Installed plugin metadata does not match the bundled package')
            if target.exists() or target.is_symlink():
                raise PluginError(f'Plugin {plugin_id} is already installed')
            os.rename(staged, target)
        finally:
            shutil.rmtree(temp_root, ignore_errors=True)
        return {
            'id': plugin_id,
            'name': manifest.name,
            'version': manifest.version,
            'source': str(target),
            'source_url': manifest.source_url,
            'license': manifest.license,
            'capabilities': tuple(sorted(manifest.capabilities)),
            'settings': manifest.settings_pages,
            'content_digest': expected_digest,
            'enabled': False,
            'approval_required': True,
            'error': '',
        }

    def report_error(self, plugin_id: str, message: str) -> None:
        self.errors[plugin_id] = message
        from .utils import log_error

        log_error(f'Plugin {plugin_id}: {message}')

    def _require_capability(self, loaded: _LoadedPlugin, capability: str) -> None:
        if capability not in loaded.manifest.capabilities:
            raise PluginError(f'{loaded.manifest.plugin_id} did not request {capability!r}')
        if capability not in loaded.granted_capabilities:
            raise PluginError(f'{loaded.manifest.plugin_id} has not been granted {capability!r}')

    def _read_state(self) -> dict[str, Any]:
        try:
            state = json.loads(self.state_path.read_text(encoding='utf-8'))
        except FileNotFoundError:
            return {'plugins': {}}
        except (OSError, json.JSONDecodeError) as err:
            raise PluginError(f'Cannot read plugin registry: {err}') from err
        if not isinstance(state, dict) or not isinstance(state.get('plugins'), dict):
            raise PluginError('Plugin registry must contain a plugins object')
        return state

    def _write_state(self, state: Mapping[str, Any]) -> None:
        os.makedirs(self.plugins_directory, exist_ok=True)
        atomic_save((json.dumps(state, indent=2, sort_keys=True) + '\n').encode('utf-8'), str(self.state_path))

    @staticmethod
    def _content_digest(directory: Path) -> str:
        digest = hashlib.sha256()
        for path in sorted(directory.rglob('*')):
            if path.is_symlink():
                raise PluginError(f'Plugin packages cannot contain symlinks: {path}')
            if not path.is_file() or '__pycache__' in path.parts:
                continue
            digest.update(path.relative_to(directory).as_posix().encode('utf-8'))
            digest.update(b'\0')
            digest.update(path.read_bytes())
            digest.update(b'\0')
        return digest.hexdigest()

    def load_enabled(self) -> None:
        try:
            state = json.loads(self.state_path.read_text(encoding='utf-8'))
        except FileNotFoundError:
            return
        except (OSError, json.JSONDecodeError) as err:
            self.report_error('registry', f'Cannot read plugin registry: {err}')
            return
        entries = state.get('plugins') if isinstance(state, dict) else None
        if not isinstance(entries, dict):
            self.report_error('registry', 'Plugin registry must contain a plugins object')
            return
        for plugin_id, record in entries.items():
            if not isinstance(plugin_id, str) or not isinstance(record, dict) or record.get('enabled') is not True:
                continue
            grants = record.get('granted_capabilities', [])
            if not isinstance(grants, list) or any(not isinstance(x, str) for x in grants):
                self.report_error(plugin_id, 'Granted capabilities must be an array of strings')
                continue
            try:
                directory = self.plugins_directory / plugin_id
                if directory.resolve(strict=True).parent != self.plugins_directory.resolve(strict=True):
                    raise PluginError('Plugin directory must be a direct child of the plugin directory')
                if not PLUGIN_ID_PATTERN.fullmatch(plugin_id):
                    raise PluginError('Invalid plugin id in registry')
                manifest = PluginManifest.read(directory)
                if record.get('trusted_version') != manifest.version or record.get('content_digest') != self._content_digest(directory):
                    raise PluginError('Plugin source changed since approval; review and enable it again')
                self.load(directory, frozenset(grants))
            except Exception as err:
                self.report_error(plugin_id, str(err))

    def enable(
        self,
        plugin_id: str,
        granted_capabilities: frozenset[str],
        *,
        confirmed: bool = False,
        expected_digest: str = '',
    ) -> None:
        if not confirmed:
            raise PluginError('Enabling a plugin requires explicit code-execution confirmation')
        if not PLUGIN_ID_PATTERN.fullmatch(plugin_id):
            raise PluginError('Invalid plugin id')
        directory = self.plugins_directory / plugin_id
        manifest = PluginManifest.read(directory)
        if manifest.plugin_id != plugin_id:
            raise PluginError('Plugin manifest id does not match its directory')
        if PLUGIN_API_VERSION not in manifest.api_versions:
            raise PluginError(f'{plugin_id} does not support API version {PLUGIN_API_VERSION}')
        digest = self._content_digest(directory)
        if not expected_digest or expected_digest != digest:
            raise PluginError('Plugin source changed during approval; review it again')
        was_loaded = plugin_id in self.loaded
        if was_loaded:
            self.disable(plugin_id)
        self.load(directory, granted_capabilities)
        try:
            state = self._read_state()
            records = state['plugins']
            records[plugin_id] = {
                'enabled': True,
                'granted_capabilities': sorted(granted_capabilities),
                'trusted_version': manifest.version,
                'content_digest': digest,
            }
            self._write_state(state)
        except Exception:
            self.disable(plugin_id)
            raise
        if self.on_change is not None:
            self.on_change()

    def plugin_info(self, plugin_id: str) -> dict[str, Any]:
        if not PLUGIN_ID_PATTERN.fullmatch(plugin_id):
            raise PluginError('Invalid plugin id')
        manifest = PluginManifest.read(self.plugins_directory / plugin_id)
        if manifest.plugin_id != plugin_id:
            raise PluginError('Plugin manifest id does not match its directory')
        digest = self._content_digest(manifest.directory)
        state = self._read_state()['plugins'].get(plugin_id, {})
        if not isinstance(state, dict):
            state = {}
        return {
            'id': plugin_id,
            'name': manifest.name,
            'version': manifest.version,
            'source': str(manifest.directory),
            'source_url': manifest.source_url,
            'license': manifest.license,
            'capabilities': tuple(sorted(manifest.capabilities)),
            'settings': manifest.settings_pages,
            'content_digest': digest,
            'enabled': plugin_id in self.loaded,
            'approval_required': state.get('trusted_version') != manifest.version or state.get('content_digest') != digest,
            'error': self.errors.get(plugin_id, ''),
        }

    def available_plugins(self) -> tuple[dict[str, Any], ...]:
        try:
            children = sorted(self.plugins_directory.iterdir())
        except FileNotFoundError:
            return ()
        ans: list[dict[str, Any]] = []
        for directory in children:
            if directory.name == 'settings' or not directory.is_dir() or directory.is_symlink():
                continue
            plugin_id = directory.name
            try:
                ans.append(self.plugin_info(plugin_id))
            except Exception as err:
                self.report_error(plugin_id, str(err))
                ans.append(
                    {
                        'id': plugin_id,
                        'name': plugin_id,
                        'version': '',
                        'source': str(directory),
                        'capabilities': (),
                        'settings': (),
                        'content_digest': '',
                        'enabled': False,
                        'approval_required': True,
                        'error': str(err),
                    }
                )
        return tuple(ans)

    def disable_plugin(self, plugin_id: str) -> None:
        state = self._read_state()
        records = state['plugins']
        record = records.get(plugin_id)
        if isinstance(record, dict):
            record['enabled'] = False
            self._write_state(state)
        self.disable(plugin_id)
        if self.on_change is not None:
            self.on_change()

    def uninstall_plugin(self, plugin_id: str) -> None:
        if not PLUGIN_ID_PATTERN.fullmatch(plugin_id):
            raise PluginError('Invalid plugin id')
        target = self.plugins_directory / plugin_id
        if target.is_symlink():
            raise PluginError('Plugin directories cannot be symlinks')
        if target.exists() and (not target.is_dir() or target.resolve(strict=True).parent != self.plugins_directory.resolve(strict=True)):
            raise PluginError('Plugin directory must be a direct child of the configured plugin directory')
        state = self._read_state()
        state['plugins'].pop(plugin_id, None)
        self._write_state(state)
        self.disable(plugin_id)
        if self.on_change is not None:
            self.on_change()
        if target.is_dir():
            shutil.rmtree(target)
        settings_path = self._plugin_settings_path(plugin_id)
        if settings_path.is_file() or settings_path.is_symlink():
            settings_path.unlink()

    def load(self, directory: str | os.PathLike[str], granted_capabilities: frozenset[str]) -> None:
        base = Path(directory).resolve(strict=True)
        if base.parent != self.plugins_directory.resolve(strict=False):
            raise PluginError('Plugins must be loaded from a direct child of the configured plugins directory')
        manifest = PluginManifest.read(base)
        plugin_id = manifest.plugin_id
        if base.name != plugin_id:
            raise PluginError(f'Plugin directory name must match its id: {plugin_id}')
        if plugin_id in self.loaded:
            raise PluginError(f'Plugin {plugin_id} is already enabled')
        if PLUGIN_API_VERSION not in manifest.api_versions:
            raise PluginError(f'{plugin_id} supports API versions {manifest.api_versions}, host provides {PLUGIN_API_VERSION}')
        unknown_grants = granted_capabilities - CAPABILITIES
        if unknown_grants:
            raise PluginError(f'Unknown granted capabilities: {", ".join(sorted(unknown_grants))}')
        if not manifest.capabilities <= granted_capabilities:
            missing = sorted(manifest.capabilities - granted_capabilities)
            raise PluginError(f'{plugin_id} requires ungranted capabilities: {", ".join(missing)}')
        entry = (manifest.directory / manifest.entry_point).resolve(strict=True)
        module_name = '_kitty_plugin_' + hashlib.sha256(str(entry).encode()).hexdigest()
        spec = importlib.util.spec_from_file_location(module_name, entry, submodule_search_locations=[str(entry.parent)])
        if spec is None or spec.loader is None:
            raise PluginError(f'Cannot create module loader for {entry}')
        module = importlib.util.module_from_spec(spec)
        loaded = _LoadedPlugin(manifest, module, None, granted_capabilities)
        context = PluginContext(self, loaded)
        loaded.context = context
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
            setup = getattr(module, 'setup', None)
            if not callable(setup):
                raise PluginError('Plugin entry point must define setup(api)')
            cleanup = setup(context)
            declared_pages = {x['id'] for x in manifest.settings_pages}
            if set(loaded.settings_pages) != declared_pages:
                raise PluginError('Registered settings pages must match plugin.json')
            if cleanup is not None:
                if not callable(cleanup):
                    raise PluginError('setup(api) must return None or a cleanup function')
                context.on_disable(cleanup)
        except Exception:
            for cleanup in reversed(loaded.cleanups):
                try:
                    cleanup()
                except Exception as cleanup_error:
                    self.report_error(plugin_id, f'Failed to clean up after load error: {cleanup_error}')
            self._remove_modules(module_name)
            raise
        self.loaded[plugin_id] = loaded
        self.errors.pop(plugin_id, None)

    def disable(self, plugin_id: str) -> None:
        loaded = self.loaded.pop(plugin_id, None)
        if loaded is None:
            return
        for cleanup in reversed(loaded.cleanups):
            try:
                cleanup()
            except Exception as err:
                self.report_error(plugin_id, f'Cleanup failed: {err}')
        self._remove_modules(loaded.module.__name__)

    @staticmethod
    def _remove_modules(prefix: str) -> None:
        for name in tuple(sys.modules):
            if name == prefix or name.startswith(prefix + '.'):
                sys.modules.pop(name, None)

    def shutdown(self) -> None:
        for plugin_id in tuple(self.loaded):
            self.disable(plugin_id)

    def run_command(self, plugin_id: str, name: str, args: Sequence[str], window_id: int | None = None) -> None:
        loaded = self.loaded.get(plugin_id)
        if loaded is None or name not in loaded.commands:
            raise PluginError(f'No enabled plugin command: {plugin_id}:{name}')
        context = loaded.context
        if context is None:
            raise PluginError(f'Plugin {plugin_id} has no active host context')
        previous_window_id = context._window_id
        context._window_id = window_id
        try:
            loaded.commands[name][1](context, tuple(args))
        except Exception as err:
            self.report_error(plugin_id, f'Command {name} failed: {err}')
            raise
        finally:
            context._window_id = previous_window_id

    def emit(self, event: PluginEvent) -> None:
        for plugin_id, callback in tuple(self._callbacks.get(event.name, ())):
            try:
                callback(event)
            except Exception as err:
                self.report_error(plugin_id, f'Event {event.name} failed: {err}')

    def commands(self) -> tuple[PluginCommand, ...]:
        return tuple(command for loaded in self.loaded.values() for command, _ in loaded.commands.values())

    def settings_pages(self) -> tuple[dict[str, Any], ...]:
        pages: list[dict[str, Any]] = []
        for plugin_id, loaded in self.loaded.items():
            saved = self._read_plugin_settings(plugin_id)
            for page in loaded.settings_pages.values():
                fields = []
                for field_data in page['fields']:
                    field = dict(field_data)
                    field['current'] = saved.get(page['id'], {}).get(field['key'], field['default'])
                    fields.append(field)
                pages.append({**page, 'plugin_id': plugin_id, 'fields': fields})
        return tuple(pages)

    def _plugin_settings_path(self, plugin_id: str) -> Path:
        return self.plugins_directory / 'settings' / f'{plugin_id}.json'

    def _read_plugin_settings(self, plugin_id: str) -> dict[str, dict[str, Any]]:
        path = self._plugin_settings_path(plugin_id)
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
        except FileNotFoundError:
            return {}
        except (OSError, json.JSONDecodeError) as err:
            self.report_error(plugin_id, f'Cannot read plugin settings: {err}')
            return {}
        if not isinstance(data, dict) or any(not isinstance(k, str) or not isinstance(v, dict) for k, v in data.items()):
            self.report_error(plugin_id, 'Plugin settings data has an invalid structure')
            return {}
        return data

    def update_settings(self, plugin_id: str, changes: Mapping[str, Mapping[str, str]]) -> None:
        values = self._updated_settings(plugin_id, changes)
        path = self._plugin_settings_path(plugin_id)
        os.makedirs(path.parent, exist_ok=True)
        atomic_save((json.dumps(values, indent=2, sort_keys=True) + '\n').encode('utf-8'), str(path))
        self.emit(PluginEvent('settings_changed'))

    def _updated_settings(self, plugin_id: str, changes: Mapping[str, Mapping[str, str]]) -> dict[str, dict[str, Any]]:
        loaded = self.loaded.get(plugin_id)
        if loaded is None:
            raise PluginError(f'Plugin {plugin_id} is not enabled')
        pages = loaded.settings_pages
        values = self._read_plugin_settings(plugin_id)
        for page_id, changed in changes.items():
            page = pages.get(page_id)
            if page is None:
                raise PluginError(f'Unknown settings page for {plugin_id}: {page_id}')
            if not isinstance(changed, Mapping):
                raise PluginError(f'Invalid settings for page {page_id}')
            fields = {x['key']: x for x in page['fields']}
            for key, value in changed.items():
                field_data = fields.get(key)
                if field_data is None or not isinstance(value, str):
                    raise PluginError(f'Unknown or invalid setting {page_id}:{key}')
                kind = field_data['type']
                try:
                    if kind == 'string':
                        parsed: Any = value
                    elif kind == 'integer':
                        parsed = int(value)
                    elif kind == 'float':
                        parsed = float(value)
                    elif kind == 'boolean' and value in {'true', 'false'}:
                        parsed = value == 'true'
                    elif kind == 'choice' and value in field_data['choices']:
                        parsed = value
                    else:
                        raise ValueError(f'Invalid {kind} value')
                except ValueError as err:
                    raise PluginError(f'Invalid plugin setting {page_id}:{key}: {err}') from err
                values.setdefault(page_id, {})[key] = parsed
        return values

    def validate_settings(self, plugin_id: str, changes: Mapping[str, Mapping[str, str]]) -> None:
        self._updated_settings(plugin_id, changes)

    def key_mappings(self) -> tuple[tuple[str, str, str, tuple[str, ...]], ...]:
        return tuple((loaded.manifest.plugin_id, key, command, args) for loaded in self.loaded.values() for key, command, args in loaded.key_mappings)

    def ui_contributions(self) -> tuple[tuple[str, str, str], ...]:
        return tuple((loaded.manifest.plugin_id, label, command) for loaded in self.loaded.values() for label, command in loaded.ui_contributions)
