AI fix
======

Your last command failed? Run ``fix`` and Claude reads the error on screen and types a corrected command at your prompt — typos, wrong flags, missing sudo, the lot.

Needs kitty shell integration to know the last command. The fix is typed but never run. Uses Claude Code (the ``claude`` command) with your existing login, no API key needed. Screen text is sent to Claude.

Install it from kitty's command palette with **Install bundled plugin**, then
**Review and enable**. Requested capabilities: background, commands, events, notify, screen, tabs, terminal, ui, window.

Original code written for kitty's plugin API, distributed under GPL-3.0-or-later.
