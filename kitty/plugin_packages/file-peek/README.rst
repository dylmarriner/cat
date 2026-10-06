File peek
=========

Browse the current directory in a split overlay with a live, syntax-highlighted preview of whatever is under the cursor. Press Enter on a file to drop its path, shell-quoted, at your prompt.

Run ``open``. Arrows move, Enter opens a folder or picks a file, Backspace goes up a level, typing filters, ``.`` toggles hidden files, Escape closes. Highlighting uses Pygments when it is installed.

Install it from kitty's command palette with **Install bundled plugin**, then
**Review and enable**. Requested capabilities: commands, launch, terminal, ui, window.

Original code written for kitty's plugin API, distributed under GPL-3.0-or-later.
