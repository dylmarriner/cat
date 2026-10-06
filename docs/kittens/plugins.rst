kitty plugins
=============

kitty has a versioned, in-process Python plugin API. Plugins are loaded from
:file:`<kitty config directory>/plugins/<plugin-id>/` only when their ID is
listed as enabled in :file:`plugins/plugins.json`. The registry records the
capabilities granted to each plugin. A plugin runs with the same user
privileges as kitty; capability declarations control access to the host API,
not Python or operating-system access.

Each plugin directory contains :file:`plugin.json` and the Python entry point
named there. For example::

    {
      "id": "example-tools",
      "name": "Example tools",
      "version": "1.0.0",
      "api_versions": [1],
      "entry_point": "main.py",
      "capabilities": ["commands", "events", "key_mappings", "screen", "scroll", "settings", "terminal", "ui"],
      "settings": [{
        "id": "general",
        "title": "General",
        "fields": [{"key": "greeting", "label": "Greeting", "type": "string", "default": "Hello"}]
      }]
    }

The entry point defines ``setup(api)``. The API supports command registration,
settings pages, key mappings, UI contributions, and lifecycle cleanup. A setup
function can return a cleanup callable or register one with
``api.on_disable()``. Commands and UI contributions are available in the
command palette. Registered key mappings are installed only if they do not
conflict with an existing mapping. A minimal entry point looks like::

    def greet(api, args):
        print('Hello', *args)

    def setup(api):
        api.register_command('greet', greet, 'Print a greeting')
        api.register_settings_page('general', {'title': 'General', 'fields': [
            {'key': 'greeting', 'label': 'Greeting', 'type': 'string', 'default': 'Hello'}
        ]})
        api.add_key_mapping('ctrl+alt+g', 'greet', 'from kitty')
        api.contribute_ui('Greet from a plugin', 'greet')

The current event hooks are ``window_created``, ``window_focused``,
``window_closed``, ``child_exited``, and ``settings_changed``. Event data is a
read-only snapshot containing the event name and, when available, window ID,
tab ID, window title, and process exit code. Plugins granted ``screen`` can
read the visible text of a window through ``api.read_screen(window_id)``;
plugins granted ``terminal`` can send text through
``api.send_text(window_id, text)``.
Commands invoked by a window action can use ``api.current_window_id`` to identify
that window. The ``scroll`` capability exposes only kitty's six built-in
scrolling actions through ``api.scroll_window(action)``; the action result
indicates whether the active screen handled scrolling. Plugins granted
``terminal`` can forward key names with ``api.send_key(*keys)``. These methods
make it possible to migrate mode-aware scrolling helpers such as
``kitty-smart-scroll`` without giving plugins arbitrary window method access.

Shell integration adds the ``command_started``, ``command_finished`` and
``bell`` events. Command events carry ``cmdline``; ``command_finished`` also
carries ``exit_code`` and ``duration`` in seconds.

Further capabilities unlock richer integrations:

``appearance``
    ``api.set_colors({'background': '#101820'}, window_id=None, all_windows=False)``
    changes colors using :file:`kitty.conf` color names, ``api.reset_colors()``
    restores the startup colors and ``api.set_background_opacity(0.8)``
    changes the opacity of the OS window.

``notify``
    ``api.notify(title, body)`` shows a desktop notification.

``tabs``
    Also allows ``api.set_tab_title(title, window_id=None)``. An empty title
    restores the automatic one.

``timers``
    ``api.add_timer(callback, interval, repeat=False)`` returns an ID for
    ``api.cancel_timer()``. Timers are cancelled when the plugin is disabled.

``background``
    ``api.run_process(argv, done, input='', cwd=None, env=None, timeout=60)``
    runs a program without blocking kitty and calls ``done(error, result)``
    with its ``stdout`` and ``stderr``. Prefer it for anything that runs a
    program. ``api.run_in_background(task, done)`` runs a Python ``task`` in a
    worker thread and calls ``done(error, result)`` on the UI thread. kitty's
    event loop holds the GIL while it waits, so threads only suit short,
    mostly blocking work.

``launch``
    ``api.launch()`` takes ``launch_type`` (``tab``, ``window``, ``overlay`` or
    ``os-window``), ``env`` and an ``on_exit`` callback, and returns the new
    window ID. ``api.run_app(script, args, launch_type='overlay', on_result=...)``
    runs a Python script from the plugin package with kitty's interpreter. The
    script can write a result to the file named by ``KITTY_PLUGIN_RESULT``,
    which is passed to ``on_result`` when its window closes.
    ``KITTY_PLUGIN_DATA`` names the plugin's data directory.

``shaders``
    ``api.shader_effect('effect.pipeline')`` activates a :doc:`custom shader
    </custom-shaders>` pipeline shipped in the plugin package and returns a
    handle bound to one of 16 plugin shader channels. In the pipeline,
    ``@SIGNAL@`` is replaced by that channel's ``plugin-signal-N`` animation
    event, and shaders that declare ``static const int PLUGIN_CHANNEL`` get the
    channel number. ``effect.set(index, x, y, z, w)`` updates
    ``d.plugin_params[2 * PLUGIN_CHANNEL + index]`` without recompiling, and
    ``effect.fire()`` starts animations waiting on ``@SIGNAL@`` and
    ``effect.show(False)`` hides every group of the effect so it costs no GPU
    time at all. Activating or removing an effect rebuilds the custom shaders
    in the background, so keep effects loaded and switch them with
    ``show()`` and parameters.

kitty reaps every child process it starts, so inside a plugin the exit code
reported by :mod:`subprocess` is not reliable, it is often zero for a failed
command. Judge the result of a program by its output instead.

Every plugin also has ``api.data_directory``, a private writable directory,
``api.package_directory`` and ``api.settings()``, which returns the current
values of its settings pages with defaults filled in.

The API version is :code:`kitty.plugins.PLUGIN_API_VERSION`. kitty rejects
plugins that do not declare support for the host's API version, lack grants for
their requested capabilities, or fail during setup. A failed plugin is
reported in kitty's log without preventing other enabled plugins from loading.

.. warning::

   Installing or updating a plugin executes its Python code as your user. The
   capability list is descriptive access control for kitty's API, not a
   sandbox. Review the upstream source before trusting it.

Remote catalog browsing, installation, updates, and local plugin management
are available in the :doc:`settings overlay </kittens/settings>` as well as
the command palette. New installations use the maintained kitty catalog; users
can set a different HTTPS catalog URL, which kitty stores under the plugin
configuration directory. Kitty fetches the index each time the catalog is
opened. A remote index uses schema version 1 and has this shape::

    {
      "schema_version": 1,
      "plugins": [{
        "id": "example-tools",
        "name": "Example tools",
        "version": "1.2.3",
        "description": "A short summary",
        "api_versions": [1],
        "capabilities": ["commands"],
        "source_url": "https://github.com/example/example-tools",
        "license": "MIT",
        "release_url": "https://github.com/example/example-tools/releases/download/v1.2.3/example-tools.zip",
        "archive_sha256": "<64 lowercase hexadecimal digits>"
      }]
    }

The release must be a ZIP containing one :file:`plugin.json` and Python entry
point, either at its root or inside one enclosing directory. kitty limits the
download and expanded sizes, checks the archive digest and manifest against
the index, and rejects unsafe paths and special files. Before download kitty
shows the release, upstream project, license, requested capabilities, and
archive digest. The user must confirm before kitty installs and runs the code.
The index digest protects transport and package integrity relative to that
index; it is not a publisher signature or a sandbox. kitty checks for catalog
updates when the catalog is opened. An update is downloaded and validated
before the installed package is replaced; a failed replacement restores the
previous files. Successful updates disable the plugin and require a fresh
review before its new code can run. Bundled packages can be installed from
kitty's command palette, and local packages can be disabled or uninstalled
there. Uninstall asks for confirmation and removes package files, the registry
record, and saved plugin settings.
Existing custom kittens continue to load through the existing kitten mechanism.
For local development, place a package directory under
:file:`<kitty config directory>/plugins/`. The command palette offers review
and enable, disable, and uninstall actions for packages found there. Changes to
an approved package trigger another review before its new code runs.

The checked-in bundled catalog is :file:`kitty/plugin_packages/catalog.json`.
Besides a Plugin API v1 port of the mode-aware scrolling behavior from
``kitty-smart-scroll``, a tab switcher and a Git worktree switcher, it bundles:

* GPU effects: ``fail-glitch``, ``streak-fireworks``, ``pomodoro-aura``,
  ``prod-guard``, ``warp-screensaver``, ``load-heatwave``, ``git-mood``,
  ``busy-orbit`` and the color theme ``daylight-themes``.
* Automation: ``cmd-timer``, ``auto-tab-titles``, ``ssh-themes``,
  ``command-stats``, ``reopen-closed`` and ``screen-watcher``.
* Overlay apps: ``sysmon-hud``, ``git-dashboard``, ``emoji-picker``,
  ``color-picker``, ``file-peek``, ``snake`` and ``typing-test``.
* Claude powered helpers: ``ai-explain``, ``ai-command`` and ``ai-fix``. They
  use Claude Code (the ``claude`` command) with your existing login, so no API
  key is needed, falling back to the ``anthropic`` Python package and
  Anthropic credentials. They send terminal text to Claude when used.

Each package has a :file:`README.rst` describing its commands.
The catalog pins each package digest and checks it against the package files
and manifest before listing or installing it. Choose **Install bundled
plugin** in kitty's command palette, then review and enable it. Installation
copies the package without executing it; enabling shows the upstream source,
license, and capability confirmation. The published remote catalog also lists
the versioned Smart Scroll release.

Upstream integration candidates
-------------------------------

These projects are useful references and potential migration candidates. They
are custom kittens or editor integrations, not packages compatible with this
host API yet, so they must not appear in the executable plugin catalog as-is.
Kitty also maintains a `third-party kittens list
<https://sw.kovidgoyal.net/kitty/kittens/custom/#kittens-created-by-kitty-users>`_,
which is a useful discovery source, not a compatibility or security review:

* `kitty-scrollback.nvim <https://github.com/mikesmithgh/kitty-scrollback.nvim>`_
  is an Apache-2.0 Neovim plugin plus custom kitten. Its current main branch
  requires kitty 0.43 or newer and Neovim 0.10 or newer, and uses shell
  integration and remote control. It is actively maintained and a good
  reference for scrollback workflows, but would need a deliberately narrower
  kitty-side port before it could use this API.
* `kitty-navigator.nvim <https://github.com/MunsMan/kitty-navigator.nvim>`_
  pairs a Neovim plugin with two Python kittens and requires remote control.
  The repository currently has no license file; do not copy or redistribute
  its code unless the author clarifies the license.
* `kitty-worktree <https://github.com/shaunchander/kitty-worktree>`_ is a small
  MIT-licensed Python kitten for choosing Git worktrees and opening per-repo
  Kitty layouts. It requires Python 3.11+, Git, and Kitty remote control. It is
  a plausible port candidate, but the current host API has no explicit
  tab/session launch capability, so it must not be packaged as a plugin until
  that API boundary is designed and reviewed.
* `kitty_grab <https://github.com/yurikhan/kitty_grab>`_ is a GPL-3.0-or-later
  keyboard-driven screen and scrollback selector that copies selected text to
  the clipboard. Its upstream kitten requires direct screen and input access;
  this host currently exposes neither keyboard capture nor clipboard access,
  so a port needs narrowly scoped APIs for both.
* `kitty-save-session <https://github.com/dflock/kitty-save-session>`_ is a
  GPL-3.0-or-later set of scripts that serializes ``kitty @ ls`` output into
  native session files and can restore sessions across instances. It is a
  useful recovery-workflow reference, but this plugin API does not expose
  instance-wide session enumeration, session-file writing, or launching new
  Kitty instances.
* `kitty-tab-switcher <https://github.com/OsiPog/kitty-tab-switcher>`_ is an
  MIT-licensed fzf and jq script for fuzzy tab selection with previews. It
  uses remote control to list and focus tabs; those operations are not exposed
  by this plugin API.
* `vim-kitty-navigator <https://github.com/knubie/vim-kitty-navigator>`_ is an
  MIT-licensed Vim/Neovim integration for moving between editor splits and
  Kitty windows. It depends on editor-side mappings and Kitty remote control,
  which this in-process plugin API does not provide.
* `familiar <https://github.com/DenoBY/familiar>`_ is an MIT-licensed set of
  Kitty overlays for Git review, history, and coding-agent sessions. It is
  macOS-only, and its session overlay reads Claude Code state. Treat it as a
  UI reference; porting it would need filesystem and process capabilities the
  current API deliberately does not expose.
* `kitty-smart-scroll <https://github.com/yurikhan/kitty-smart-scroll>`_ is a
  standalone Python kitten under GPL-3.0-or-later, with Kitty 0.24+ support.
  Its upstream repository has no versioned releases. The bundled
  :file:`smart-scroll` API v1 package is a port of its documented behavior,
  not an upstream release archive; it is the only one of these candidates
  currently installable through this host API.

For theme discovery, Kitty maintains the separate
`kitty-themes repository <https://github.com/kovidgoyal/kitty-themes>`_ with a
machine-readable :file:`themes.json` index. It is a useful source for a future
theme browser in settings, not an executable plugin source. Per-theme license
metadata varies, so any redistribution must preserve and check each entry's
license and attribution.

Published catalog
-----------------

The public ``plugin-smart-scroll-v1.0.0`` release is published from
``https://github.com/dylmarriner/cat/releases/tag/plugin-smart-scroll-v1.0.0``.
The ``plugin-catalog`` branch serves the current index at
``https://raw.githubusercontent.com/dylmarriner/cat/plugin-catalog/catalog.json``.
New installations use this catalog by default; a user can replace the URL with
another HTTPS catalog. The release workflow tests and packages the bundled
plugin selected by a tag matching ``plugin-<plugin-id>-v<version>``. It uploads
the archive and merged catalog to the versioned release, then updates the
dedicated catalog branch without removing entries for other plugins. Releases
are serialized so concurrent plugin releases cannot overwrite one another's
catalog updates.
