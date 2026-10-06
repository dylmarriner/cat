Fail glitch
===========

When a command fails, the screen glitches: RGB split, torn scanlines and a red flash, scaled by how bad the failure was.

Needs kitty shell integration so kitty knows when commands finish. Interrupted commands (exit code 130) get a small glitch, crashes from signals the biggest one.

Install it from kitty's command palette with **Install bundled plugin**, then
**Review and enable**. Requested capabilities: events, shaders.

Original code written for kitty's plugin API, distributed under GPL-3.0-or-later.
