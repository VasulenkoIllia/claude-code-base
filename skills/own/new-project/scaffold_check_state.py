"""Self-check of STATUS and its archive: the adoption renders the templates creation walks, keeps a STATUS the project
has, and puts a new one where the global rule says: docs/ when git ignores both files there or there is no repository,
else .claude/state/. Offline, in temp folders.
"""
import os
import tempfile

import scaffold_render as sr
from scaffold_check_modes import ADOPT_ARGS, BAD_PROJECT, commit, git, put, run_quiet, text_of

OWN = 'свій\n'


def check_state_files():
    folder = os.path.join(sr.TEMPLATES, 'common', 'state')
    found = sorted(os.listdir(folder)) if os.path.isdir(folder) else []
    wanted = sorted(name + '.tmpl' for name in sr.STATE_FILES)
    return [] if found == wanted else ['state: templates/common/state has %s, STATE_FILES %s' % (found, wanted)]


def adopted(sc, tmp, name, files, repo=True):
    """(card, output, target) of an adoption of a project with these files more."""
    target = os.path.join(tmp, name)
    put(target, {**BAD_PROJECT, **files})
    if repo:
        git(target, 'init', '-q', '-b', 'main')
        git(target, 'config', 'core.excludesFile', os.devnull)
        commit(target)
        commit(target, 'second')
    else:  # without a repository the number of files makes it a project, not an IDE template
        put(target, {'src/f%d.ts' % i: '' for i in range(45)})
    code, out = run_quiet(sc, [target] + ADOPT_ARGS)
    card = text_of(target, 'CLAUDE.local.md') if code == 0 else ''
    return card, out, target


def check_state(sc):
    fails = check_state_files()
    with tempfile.TemporaryDirectory() as tmp:
        card, out, target = adopted(sc, tmp, 'no-repo', {}, repo=False)
        if '- Стан: `docs/STATUS.md`' not in card or not os.path.isfile(os.path.join(target, 'docs/STATUS-archive.md')):
            fails.append('state: no repository, STATUS not in docs/: %s' % out[:300])
        card, out, target = adopted(sc, tmp, 'root', {'STATUS.md': OWN})
        if '- Стан: `STATUS.md`' not in card or 'kept STATUS.md' not in out or 'STATUS-archive' in out:
            fails.append('state: a STATUS of the project was not kept: %s' % out[:300])
        card, out, target = adopted(sc, tmp, 'both', {'docs/STATUS.md': OWN, sr.STATE_DIR + '/STATUS.md': OWN})
        if '- Стан: `docs/STATUS.md`' not in card or 'kept docs/STATUS.md' not in out:
            fails.append('state: of two STATUS files docs/ counts first, as in project-doctor.sh: %s' % out[:300])
        card, out, target = adopted(sc, tmp, 'archive', {sr.STATE_DIR + '/STATUS-archive.md': OWN})
        if 'created %s/STATUS.md' % sr.STATE_DIR not in out \
                or text_of(target, sr.STATE_DIR + '/STATUS-archive.md') != OWN:
            fails.append('state: an archive without STATUS: %s' % out[:300])
        card, out, target = adopted(sc, tmp, 'half', {'.gitignore': 'node_modules\ndocs/STATUS.md\n'})
        if '- Стан: `%s/STATUS.md`' % sr.STATE_DIR not in card or os.path.exists(os.path.join(target, 'docs/STATUS.md')):
            fails.append('state: git hides docs/STATUS.md but not its archive, STATUS went to docs/: %s' % out[:300])
    return fails
