Reopen closed
=============

Ctrl+Shift+T for your terminal: closed a shell by accident? Bring it back in the same directory with the same title, or pick from the last twenty closed shells.

Needs kitty shell integration, which is how it knows a window was a shell. Run ``reopen`` for the most recently closed shell or ``choose`` for the list.

Install it from kitty's command palette with **Install bundled plugin**, then
**Review and enable**. Requested capabilities: commands, events, launch, ui, window.

Original code written for kitty's plugin API, distributed under GPL-3.0-or-later.
