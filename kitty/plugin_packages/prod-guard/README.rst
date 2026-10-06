Prod guard
==========

Never mistake production for staging again: when a command touches production, that window turns blood red and kitty draws hazard stripes around it until the command ends.

Needs kitty shell integration. A command counts as dangerous when it matches the pattern on the plugin settings page; the default catches ssh, kubectl, psql, terraform and similar commands that mention prod, production or prd.

Install it from kitty's command palette with **Install bundled plugin**, then
**Review and enable**. Requested capabilities: appearance, events, settings, shaders.

Original code written for kitty's plugin API, distributed under GPL-3.0-or-later.
