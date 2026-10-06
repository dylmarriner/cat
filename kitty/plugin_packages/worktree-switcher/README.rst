Git worktree switcher
=====================

List the current repository's Git worktrees in kitty's chooser and open the
selected path in a new tab. Requires Git and a shell. Worktree metadata is read
with an argv-based Git call; paths are never interpolated into shell commands.

Run ``worktree-switcher`` from the plugin command list or assign it a key
mapping in kitty's plugin settings.

Source inspiration: https://github.com/shaunchander/kitty-worktree

This implementation uses kitty's plugin API and does not include upstream code.
