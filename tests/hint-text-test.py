#!/usr/bin/env python3
"""hint-text-test: hooks/session-hint.sh prints exactly the texts of TEXT in tests/hint_common.py, for each of its hints.
tests/hint-replay.py checks the same on live transcripts, but verify.sh does not run it; tests/hint-delivered-test.py
builds its transcripts from TEXT, so it cannot see a text that drifted, and on live sessions such a hint counts as not
delivered, which reads as a rollback.

Run (from the repo root): python3 -I tests/hint-text-test.py -> the last line "session-hint texts: N cases, F failed";
exit 0 when none failed. Offline; the hook's error log goes to a temp folder.
"""
import json
import os
import subprocess
import sys
import tempfile

TESTS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TESTS)   # -I drops the script folder from sys.path
from hint_common import EVENT, TEXT  # noqa: E402

HOOK = os.path.join(os.path.dirname(TESTS), 'hooks', 'session-hint.sh')
BASH = {'hook_event_name': 'PostToolUse', 'tool_name': 'Bash', 'session_id': 'hint-text'}
CASES = {'PostToolUse': dict(BASH, tool_input={'command': 'git push'}, tool_response={'stdout': '', 'stderr': ''}),
         'PullRequest': dict(BASH, tool_input={'command': 'gh pr create --fill'},
                             tool_response={'stdout': 'https://github.com/o/r/pull/1', 'stderr': ''}),
         'SessionStart': {'hook_event_name': 'SessionStart', 'source': 'compact'}}


def main():
    fails = ['FAIL TEXT has %s, no case here' % k for k in TEXT if k not in CASES]
    with tempfile.TemporaryDirectory(prefix='hint-text-') as tmp:
        env = dict(os.environ, SESSION_HINT_ERRLOG=os.path.join(tmp, 'err.log'))
        for key, payload in CASES.items():
            p = subprocess.run(['/bin/bash', HOOK], input=json.dumps(payload), env=env, capture_output=True, text=True,
                               timeout=30)
            hso = json.loads(p.stdout).get('hookSpecificOutput', {}) if p.stdout.strip() else {}
            if p.returncode or hso.get('hookEventName') != EVENT[key] or hso.get('additionalContext') != TEXT[key]:
                fails.append('FAIL %s: exit %d, got %r' % (key, p.returncode, hso.get('additionalContext')))
    print('\n'.join(fails + ['session-hint texts: %d cases, %d failed' % (len(CASES), len(fails))]))
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
