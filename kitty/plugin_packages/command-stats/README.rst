Command stats
=============

Your shell, quantified: every command is logged locally, and a full screen dashboard shows your most used tools, failure rates, time sunk into builds, your busiest hours and the slowest commands of the week.

Needs kitty shell integration. Run ``dashboard`` to open the overlay; press ``r`` to refresh and ``q`` to close. Data stays in a SQLite file in the plugin data directory; run ``forget`` to erase it.

Install it from kitty's command palette with **Install bundled plugin**, then
**Review and enable**. Requested capabilities: commands, events, launch, ui, window.

Original code written for kitty's plugin API, distributed under GPL-3.0-or-later.
