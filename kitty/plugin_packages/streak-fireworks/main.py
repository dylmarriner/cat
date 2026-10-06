import json
import os

MILESTONES = (5, 10, 25, 50, 100)


def is_milestone(streak):
    return streak in MILESTONES or (streak > 100 and streak % 100 == 0)


def setup(api):
    effect = api.shader_effect('streak-fireworks.pipeline')
    path = os.path.join(api.data_directory, 'streak.json')
    try:
        with open(path, encoding='utf-8') as f:
            state = json.load(f)
    except (OSError, ValueError):
        state = {'streak': 0, 'best': 0}

    def save():
        with open(path + '.tmp', 'w', encoding='utf-8') as f:
            json.dump(state, f)
        os.replace(path + '.tmp', path)

    def launch(level):
        effect.set(0, min(level, 5), (level * 0.137) % 1.0)
        effect.fire()

    def on_finished(event):
        if event.exit_code:
            state['streak'] = 0
        else:
            state['streak'] += 1
            state['best'] = max(state['best'], state['streak'])
            if is_milestone(state['streak']):
                level = MILESTONES.index(state['streak']) + 1 if state['streak'] in MILESTONES else 5
                launch(level)
                api.notify(f'🔥 {state["streak"]} command streak!', f'Best ever: {state["best"]}')
        save()

    def status(context, _args):
        context.notify(f'Streak: {state["streak"]}', f'Best streak: {state["best"]}')

    api.subscribe('command_finished', on_finished)
    api.register_command('status', status, 'Show the current command streak')
    api.register_command('test', lambda context, _args: launch(3), 'Launch fireworks now')
    api.contribute_ui('Show command streak', 'status')
    api.contribute_ui('Launch streak fireworks', 'test')
