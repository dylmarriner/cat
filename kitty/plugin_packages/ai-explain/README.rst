AI explain
==========

Stuck on a wall of red? One command sends what is on screen, plus the command you ran and its exit code, to Claude and opens a scrollable explanation of what went wrong and how to fix it.

Run ``explain`` in the window with the problem. In the answer, arrows / j / k / Space scroll, ``y`` copies the first code block, ``q`` closes. Uses Claude Code (the ``claude`` command) with your existing login, no API key needed; without it, the ``anthropic`` Python package and Anthropic credentials. Screen text is sent to Claude.

Install it from kitty's command palette with **Install bundled plugin**, then
**Review and enable**. Requested capabilities: background, clipboard, commands, events, launch, screen, tabs, ui, window.

Original code written for kitty's plugin API, distributed under GPL-3.0-or-later.
