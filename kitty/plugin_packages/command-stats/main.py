import os
import sqlite3
import time

SCHEMA = 'CREATE TABLE IF NOT EXISTS commands (ts REAL, program TEXT, cmdline TEXT, exit_code INTEGER, duration REAL, cwd TEXT)'


def program_of(cmdline):
    for word in cmdline.split():
        if '=' in word.split('/')[0] or word in ('sudo', 'doas', 'env', 'time', 'nice', 'command', 'exec'):
            continue
        return os.path.basename(word)
    return ''


def setup(api):
    path = os.path.join(api.data_directory, 'commands.sqlite')
    db = sqlite3.connect(path)
    db.execute(SCHEMA)
    db.commit()
    api.on_disable(db.close)

    def on_finished(event):
        if not event.cmdline.strip():
            return
        try:
            cwd = api.window_info(event.window_id)['cwd']
        except Exception:
            cwd = ''
        db.execute(
            'INSERT INTO commands VALUES (?, ?, ?, ?, ?, ?)',
            (time.time(), program_of(event.cmdline), event.cmdline[:500], event.exit_code or 0, event.duration, cwd),
        )
        db.commit()

    def dashboard(context, _args):
        context.run_app('dashboard.py', [path], title='Command stats')

    def forget(context, _args):
        db.execute('DELETE FROM commands')
        db.commit()

    api.subscribe('command_finished', on_finished)
    api.register_command('dashboard', dashboard, 'Open the command statistics dashboard')
    api.register_command('forget', forget, 'Erase all recorded commands')
    api.contribute_ui('Command stats dashboard', 'dashboard')
