Kitty settings
==============

Press :kbd:`kitty_mod+F4` to open a searchable settings overlay. It is also
available as :code:`open_settings` in the command palette. Use the arrow keys to
select an option, :kbd:`Enter` to edit it, and :kbd:`Ctrl+S` to save.
Options with a finite set of choices can also be changed with the left and right
arrow keys.

Settings pages contributed by enabled plugins appear under the Plugins group.
Plugin settings are validated against the plugin's declared field types and
stored separately from :file:`kitty.conf`.

The :guilabel:`Appearance` group links to kitty's theme and font pickers, which
provide live previews. The :guilabel:`Plugins` group provides catalog refresh,
plugin review and enable, install, update, disable, and uninstall actions. Use
the search field to find a plugin by name, version, or source. Catalog releases
and plugin code execution still require their own confirmation prompts.

The overlay is generated from every option in kitty's configuration definitions.
It shows each option's group, type, default, choices, configured value, and
source file, plus help text and a restart hint where the option definition
provides them. Repeated options accept a JSON array of strings, for example::

    ["U+E0A0-U+E0A3 PowerlineSymbols", "U+E0C0-U+E0C7 PowerlineSymbols"]

Before writing, kitty parses the generated directives with its normal
configuration parser. On success it atomically replaces the settings overlay
block in :file:`kitty.conf`, retaining other values previously saved by the
overlay, and reloads configuration. Invalid values leave the file unchanged and
are reported in kitty.

The :kbd:`E` key opens the existing text editor for advanced configuration,
including key and mouse mappings. The :kbd:`R` key reloads the current
configuration without saving overlay edits. Use :kbd:`Ctrl+C` to discard
in-memory edits and close the overlay. Use :kbd:`V` to remove the overlay-owned
block and reveal values from the rest of your configuration.

.. note::

   Settings that require a full kitty restart do not take effect until kitty is
   restarted. The overlay edits configuration values and does not restart kitty.
