Smart scroll plugin
===================

This is a kitty Plugin API v1 port of the mode-aware behavior in
`kitty-smart-scroll <https://github.com/yurikhan/kitty-smart-scroll>`_. It
uses kitty's built-in scroll actions in the normal screen and forwards the
same key to the terminal application when kitty reports that the alternate
screen handled the action.

To install it, open kitty's command palette and choose **Install bundled
plugin**, then choose **Review and enable**. The plugin requests command,
key-mapping, scrolling, and terminal-key capabilities. Its default mappings
use ``ctrl+alt+up/down/page_up/page_down/home/end``; change them in
``main.py`` if those keys conflict with your configuration.

The upstream project is GPL-3.0-or-later. This port is distributed under the
same license. Remote catalog installation is available when an index lists a
versioned release ZIP. The repository workflow publishes this package and its
catalog entry when a maintainer pushes a matching
``plugin-smart-scroll-v<version>`` tag. Remote updates replace the installed
files only after verification, disable the updated package, and require a new
review before its code can run.
