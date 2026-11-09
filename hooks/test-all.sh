#!/bin/bash
# Run every hook test suite. Expect ALL OK, EXTRA OK, DIRS OK, ALL OK, DUP OK, DOCS OK, HINT OK, SYNC OK and NODE OK,
# and exit 0.
H=$(cd "$(dirname "$0")" && pwd); rc=0
bash "$H/test-hooks.sh" || rc=1
bash "$H/extra-tests.sh" || rc=1
bash "$H/dirs-tests.sh" || rc=1
bash "$H/secret-tests.sh" "$H/secret-guard.sh" | grep -v '^--- new cases' || rc=1
bash "$H/dup-tests.sh" || rc=1
bash "$H/doc-tests.sh" || rc=1
bash "$H/hint-tests.sh" || rc=1
bash "$H/docs-sync-tests.sh" || rc=1
bash "$H/node-std-tests.sh" || rc=1
exit $rc
