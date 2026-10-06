Screen watcher
==============

Tell kitty what you are waiting for (“compiled successfully”, “ERROR”, a request ID…) and go do something else: when it appears in the watched window you get a notification, a flash of light and a 🔔 in the tab title.

Run ``watch`` in the window to watch and type a regular expression (case-insensitive). Run ``unwatch`` there to stop. Each window can watch one pattern.

Install it from kitty's command palette with **Install bundled plugin**, then
**Review and enable**. Requested capabilities: commands, notify, screen, shaders, tabs, timers, ui.

Original code written for kitty's plugin API, distributed under GPL-3.0-or-later.
