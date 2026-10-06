SSH host themes
===============

Every server gets its own color: when you ssh somewhere, that window takes on a tint, cursor and border color derived from the host name, so the same host always looks the same and different hosts never look alike.

Needs kitty shell integration. Works for ssh, mosh, autossh and kitten ssh. Colors reset when the session ends.

Install it from kitty's command palette with **Install bundled plugin**, then
**Review and enable**. Requested capabilities: appearance, events.

Original code written for kitty's plugin API, distributed under GPL-3.0-or-later.
