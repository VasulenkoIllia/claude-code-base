#!/bin/bash
# bash-guard-dirs.py: no ask about another commit identity in a one-off repo under /tmp, the ask of before elsewhere
H=$(cd "$(dirname "$0")" && pwd); f=0
D=$(mktemp -d /private/tmp/bash-guard-tests.XXXXXX) || { echo "FAIL no test folder in /private/tmp"; exit 1; }
mkdir "$D/bin" && printf '#!/bin/bash\nexit 0\n' >"$D/bin/gitleaks" && chmod +x "$D/bin/gitleaks"   # first on PATH: no real gitleaks here
export BASH_GUARD_ERRLOG="$D/errors.log"   # bash-guard-dirs.py must not fail in any case below
REAL=/var/empty/bash-guard-real            # a folder outside /tmp: the identity rule asks there
bgc(){ out=$(printf '%s' "$3" | /usr/bin/jq -Rs --arg c "$2" '{tool_input:{command:.},cwd:$c}' | PATH=$D/bin:/usr/bin:/bin "$H/bash-guard.sh" 2>/dev/null); rc=$?; [ $rc -eq 0 ] && [[ $out == *'"ask"'* ]] && rc=ask; [ "$rc" == "$1" ] || { echo "FAIL expected $1 got $rc: $3"; f=1; }; }
# another identity: every form asks in a real folder, not in a one-off repo under /tmp (bash-guard-dirs.py)
fx(){ GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1 git -c user.name=t -c user.email=t@t "$@"; }
mkdir -p "$D/r" "$D/wt" "$D/clone/.git" "$D/clone/src" "$D/local/.git" "$D/inc/.git" "$D/main" "$D/common/.git" \
  "$D/lout/.git" "$D/odd" "$D/empty" "$D/-" "$D/+1" "$D/q*"   # cd -, pushd +1 and a glob must not take these
printf 'gitdir: /var/empty/real/.git/worktrees/wt\n' > "$D/wt/.git"
printf '/var/empty/real/.git\n' > "$D/common/.git/commondir"
printf '[remote "origin"]\n\turl = /var/empty/real.git\n' > "$D/lout/.git/config"
printf 'not a gitdir line\n' > "$D/odd/.git"
printf '[remote "origin"]\n\turl = https://github.com/o/r.git\n' > "$D/clone/.git/config"
printf '[remote "origin"]\n\turl = %s/bare.git\n' "$D" > "$D/local/.git/config"
printf '[include]\n\tpath = /var/empty/x\n' > "$D/inc/.git/config"
ln -s /var/empty "$D/link"
fx -C "$D/main" init -q && fx -C "$D/main" commit -q --allow-empty -m i && fx -C "$D/main" worktree add -q "$D/wt2" ||
  { echo "FAIL fixture worktree"; f=1; }
for form in 'git commit -m x --author "Bot <bot@example.com>"' 'git -c user.name=Bot -c user.email=bot@example.com commit -m x' \
    'git -c "user.name=Bot" commit -m x' 'GIT_AUTHOR_NAME=Bot git commit -m x' 'git config user.name Bot' \
    'export GIT_COMMITTER_EMAIL=c@example.com'; do
  bgc ask "$REAL" "$form"
  bgc 0 "$D/r" "$form"
  bgc 0 "$REAL" "cd $D/r && $form"
done
# the folder from the command: variables, relative cd, subshells, git -C, /tmp as /private/tmp
bgc 0 "$REAL" "S=$D/s; mkdir -p \"\$S/repo/src\"; cd \"\$S/repo\"; git init -q; git -c user.email=a@b -c user.name=n commit -q -m init"
bgc 0 "$REAL" "cd $D && mkdir -p r2 && cd r2 && git init -q && git -c user.name=t commit -m x"
bgc 0 "$REAL" "cd $D && mkdir n && cd n && git init -q && git -c user.name=t commit -m x"
bgc 0 "$REAL" "cd $D/r; time (git -c user.name=t commit -m x) && ! (git -c user.name=t commit -m y)"
bgc 0 "$REAL" "cd $D/r && if true; then (git -c user.name=t commit -m x); fi"
bgc 0 "$REAL" "cd $D/r && ln -sfn /var/empty node_modules && ln -s /var/empty/x . && git -c user.name=t commit -m x"
bgc 0 "$REAL" "cd $D && (cd r && git -c user.name=t commit -m x)"
bgc 0 "$REAL" "git -C $D/r -c user.name=t commit -m x"
bgc 0 "$REAL" "cd ${D#/private}/r && git -c user.name=t commit -m x"
bgc 0 "$REAL" "cd $D && X=\$(cd /var/empty && pwd) && git -c user.name=t commit -m x"
bgc 0 "$REAL" "cd $D && for m in a b; do git -c user.name=t commit -q -m \$m; done"
bgc 0 "$REAL" "cd $D && mk() { git -c user.name=t commit -q -m \"\$1\"; } && mk a"
bgc 0 "$REAL" "cd $D && export GIT_AUTHOR_NAME=t && git commit -m x"
bgc 0 "$REAL" "cd $D # cd /var/empty"$'\n'"git -c user.name=t commit -m x"
bgc 0 "$REAL" "cd $D && echo 'cd /var/empty' && git -c user.name=t commit -m x"
bgc 0 "$REAL" "cd $D && bash -c \"git -c user.name=t commit -m x\""
bgc ask "$REAL" "(cd $D && git init -q) && git -c user.name=t commit -m x"
bgc ask "$REAL" "cd $D/../../var/empty && git -c user.name=t commit -m x"
bgc ask "$REAL" "cd $D && cd /var/empty && git -c user.name=t commit -m x"
bgc ask "$REAL" "cd $D && cd - && git -c user.name=t commit -m x"
bgc ask "$REAL" "cd $D && cd && git -c user.name=t commit -m x"
bgc ask "$REAL" 'cd "$(mktemp -d)" && git -c user.name=t commit -m x'
bgc ask "$REAL" "cd $D && git -C /var/empty -c user.name=t commit -m x"
bgc ask "$REAL" "if [ -d $D ]; then cd $D; fi; git -c user.name=t commit -m x"
bgc ask "$REAL" "test -d /x || cd $D; git -c user.name=t commit -m x"
bgc ask "$REAL" "cd $D | cat; git -c user.name=t commit -m x"
bgc ask "$REAL" "cd $D && sleep 1 & git -c user.name=t commit -m x"
bgc ask "$REAL" "cd $D && X=\$(cd /var/empty && git -c user.name=t commit -q -m x)"
bgc ask "$REAL" "cd $D && . ./env.sh && git -c user.name=t commit -m x"
bgc ask "$REAL" "cd $D && mk() { GIT_AUTHOR_NAME=t git commit -q -m x; }; cd /var/empty; mk"
bgc ask "$REAL" "cd $D && export GIT_AUTHOR_NAME=t && cd /var/empty && git commit -m x"
bgc ask "$REAL" "cd $D && export GIT_AUTHOR_NAME=t && git -C /var/empty commit -m x"
bgc ask "$REAL" "case x in a) cd $D;; esac; git -c user.name=t commit -m x"
bgc ask "$REAL" "cd $D && GIT_AUTHOR_NAME=t; cd /var/empty && git commit -m x"
bgc ask "$REAL" "cd $D && builtin cd /var/empty && git -c user.name=t commit -m x"
bgc ask "$REAL" "cd $D && pushd +1 && git -c user.name=t commit -m x"
bgc ask "$REAL" "cd $D/r* && git -c user.name=t commit -m x"
bgc ask "$REAL" "cd $D/r x && git -c user.name=t commit -m x"
bgc 0 "$REAL" "cd $D/r && pushd -n /var/empty && git -c user.name=t commit -m x"
bgc ask "$REAL" "cd $D/r && popd && git -c user.name=t commit -m x"
bgc ask "$REAL" "cd $D/r && X=\`pwd\` && git -c user.name=t commit -m x"
bgc ask "$REAL" "cd $D/r && cat > f <<-EOF"$'\n\tx\n\tEOF\n'"cd /var/empty && git -c user.name=t commit -m x"
CDPATH=/var bgc ask "$REAL" "cd $D && cd empty && git -c user.name=t commit -m x"
bgc ask "$REAL" "cd $D && CDPATH=/var; cd empty && git -c user.name=t commit -m x"
bgc ask "$REAL" "cd $D/r && env -C /var/empty git -c user.name=t commit -m x"
bgc ask "$REAL" "mkdir $D/n5/a; cd $D/n5; git -c user.name=t commit -m x"
bgc ask "$REAL" "S=/var/empty; false || S=$D/r; cd \$S && git -c user.name=t commit -m x"
bgc ask "$REAL" "S=$D/r; read S; cd \$S && git -c user.name=t commit -m x"
bgc ask "$REAL" "S=$D/r; for S in x; do :; done; cd \$S && git -c user.name=t commit -m x"
bgc ask "$REAL" "for d in x; do cd $D/r; done; git -c user.name=t commit -m x"
bgc 0 "$REAL" "S=$D/r; (S=/var/empty); cd \$S && git -c user.name=t commit -m x"
bgc 0 "$REAL" "S=$D/r; cd \${S} && cd \$PWD && git -c user.name=t commit -m x"
bgc ask "$REAL" "cd $D/r && \\"$'\n'"cd /var/empty && git -c user.name=t commit -m x"
bgc ask "$REAL" "cd $D/r && cat > f <<'EOF'"$'\nx\nEOF\n'"cd /var/empty && git -c user.name=t commit -m x"
BASH_GUARD_RESCAN_SECS=1000 bgc ask "$D/r" "git -c user.name=t commit -m x # $(head -c 200001 /dev/zero | tr '\0' x)"
HOME=$D/r bgc ask "$REAL" "cd && git -c user.name=t commit -m x"
# a cd that may fail leaves git in the old folder: a folder that is not there and that no mkdir before it makes
bgc ask "$REAL" "cd $D/nope; git -c user.name=t commit -m x"
bgc ask "$REAL" "cd $D/nope || git -c user.name=t commit -m x"
bgc 0 "$REAL" "cp -R $D/r $D/cp && cd $D/cp && git -c user.name=t commit -m x"
bgc 0 "$REAL" "cd $D && git init -q -b main $D/g/a; cd g; git -c user.name=t commit -m x"
bgc ask "$REAL" "cd $D && git init -q -b g2; cd g2; git -c user.name=t commit -m x"
bgc ask "$REAL" "cd $D && git init -q --separate-git-dir /var/empty/x.git g3 && cd g3 && git -c user.name=t commit -m x"
bgc 0 "$D/r" "(cd $D/nope && true); git -c user.name=t commit -m x"
bgc ask "$REAL" "cd $D/nope && git -c user.name=t commit -m x; git -c user.name=t commit -m y"
bgc ask "$REAL" "cd $D/nope && true || git -c user.name=t commit -m x"
bgc ask "$REAL" "test -f /x && cd $D/r; for m in GIT_AUTHOR_NAME=x; do :; done"
bgc ask "$REAL" "mkdir -p $D/n2/a; cd $D/n2/b; git -c user.name=t commit -m x"
bgc ask "$REAL" "if false; then mkdir -p $D/n3; fi; cd $D/n3; git -c user.name=t commit -m x"
bgc ask "$REAL" "cd -P $D/r && git -c user.name=t commit -m x"
bgc ask "$REAL" "git -C $D/r/.. -c user.name=t commit -m x"
# heredocs: the text that cat or tee writes to a file or into $(...) does not count, code does
bgc 0 "$REAL" $'cat > /var/empty/f.sh <<\'EOF\'\ngit -c user.name=t commit -m x\nEOF'
bgc 0 "$REAL" $'tee notes.md >/dev/null <<EOF\nexport GIT_AUTHOR_NAME=t\nEOF'
bgc 0 "$REAL" $'git commit -m "$(cat <<\'EOF\'\nfix: git -c user.name=x commit in the docs\nEOF\n)"'
bgc ask "$REAL" $'cat <<\'EOF\' | bash\ngit -c user.name=t commit -m x\nEOF'
bgc ask "$REAL" $'cat <<\'EOF\'\ngit -c user.name=t commit -m x\nEOF'
bgc ask "$REAL" $'tee <<\'EOF\'\ngit -c user.name=t commit -m x\nEOF'
bgc ask "$REAL" $'tee f <<\'EOF\' | bash\ngit -c user.name=t commit -m x\nEOF'
bgc ask "$REAL" $'bash <<\'EOF\'\ngit -c user.name=t commit -m x\nEOF'
bgc ask "$REAL" $'python3 - <<\'EOF\'\nprint("git -c user.name=t commit")\nEOF'
bgc 0 "$REAL" "cd $D && bash <<'EOF'"$'\ngit -c user.name=t commit -m x\nEOF'
bgc ask "$REAL" "cd $D && bash <<'EOF'"$'\ncd /var/empty && git -c user.name=t commit -m x\nEOF'
# what asks also under /tmp: a link to a real repo, ssh or sudo, a setting outside the repo, a cd in quotes
bgc ask "$REAL" "cd $D && bash -c \"cd /var/empty && git -c user.name=t commit -m x\""
bgc ask "$REAL" "cd $D && ssh host 'git -c user.name=t commit -m x'"
bgc ask "$REAL" "cd $D && sudo git -c user.name=t commit -m x"
bgc ask "$REAL" "cd $D && git config --global user.name t"
bgc ask "$REAL" "cd $D && git -c user.name=t commit -m x && git push origin main"
bgc ask "$REAL" "git clone https://github.com/o/r $D/c && cd $D/c && git -c user.name=t commit -m x"
bgc ask "$REAL" "git worktree add $D/w && cd $D/w && git -c user.name=t commit -m x"
bgc ask "$REAL" "cd $D && GIT_DIR=/var/empty/.git git -c user.name=t commit -m x"
bgc ask "$REAL" "cd $D && gh repo clone o/r && git -c user.name=t commit -m x"
bgc ask "$REAL" "ln -s /var/empty $D/l2 && git -C $D/l2 -c user.name=t commit -m x"
bgc ask "$REAL" "cd $D && ln -s /var/empty l3 && git -C l3/x -c user.name=t commit -m x"
bgc ask "$REAL" "cd $D/r && ln -s /var/empty/real .git && git -c user.name=t commit -m x"
bgc ask "$REAL" "cd $D/r && ln -s /var/empty/.git && git -c user.name=t commit -m x"
bgc 0 "$REAL" "cd $D/r && ln -s -- /var/empty/x y && git -c user.name=t commit -m x"
bgc ask "$REAL" "cd $D/r && trap 'git push' EXIT && git -c user.name=t commit -m x"
bgc ask "$REAL" "cd $D/r && bash <<'EOF'"$'\ngit push\nEOF\n'"git -c user.name=t commit -m x"
bgc ask "$REAL" "cd $D/r && git --git-dir=/var/empty/.git -c user.name=t commit -m x"
bgc ask "$REAL" "cd $D/r && git -c user.name=t -C /var/empty commit -m x"
bgc ask "$REAL" "cd $D/common && git -c user.name=t commit -m x"
bgc ask "$REAL" "cd $D/lout && git -c user.name=t commit -m x"
bgc ask "$REAL" "cd $D/odd && git -c user.name=t commit -m x"
bgc ask "$REAL" "cd $D/r && ln -t /var/empty x && git -c user.name=t commit -m x"
bgc ask "$REAL" "cd $D/r && ls | xargs ln -s && git -c user.name=t commit -m x"
bgc ask "$REAL" "cd $D/r && bash -c 'ln -s /var/empty y' && git -c user.name=t commit -m x"
bgc ask "$REAL" "cd $D/r && eval \"gh repo clone o/r\" && git -c user.name=t commit -m x"
bgc ask "$REAL" "cd $D/wt && git -c user.name=t commit -m x"
bgc 0 "$REAL" "cd $D/wt2 && git -c user.name=t commit -m x"
bgc ask "$REAL" "cd $D/clone/src && git -c user.name=t commit -m x"
bgc 0 "$REAL" "cd $D/local && git -c user.name=t commit -m x"
bgc ask "$REAL" "cd $D/inc && git -c user.name=t commit -m x"
bgc ask "$REAL" "cd $D/link && git -c user.name=t commit -m x"
bgc 2 "$REAL" "cd $D && git -c user.name=Claude commit -m x"
bgc 2 "$D/r" 'GIT_AUTHOR_NAME=Claude git commit -m x'
bgc ask "$REAL" "echo 'git -c user.name=x commit'"   # known limit: a form in text outside a file heredoc
# a backslash-newline as the shell reads it: not in a comment, a quoted heredoc or after \\; inside a word it goes
bgc ask "$REAL" "# n \\"$'\n'"git -c user.name=t commit -m x"
bgc ask "$REAL" "cd $D/r && cat >/dev/null <<'EOF'"$'\nx\\\nEOF\n'"cd /var/empty && git -c user.name=t commit -m x"
bgc ask "$REAL" "cd $D/r && echo a\\\\"$'\n'"cd /var/empty"$'\n'"git -c user.name=t commit -m x"
bgc ask "$D/r" "gi\\"$'\n'"t -C /var/empty -c user.name=t commit -m x"
bgc 0 "$REAL" "cd $D/\\"$'\n'"r && git -c user.name=t commit -m x"
bgc 0 "$D/r" "cat > f <<EOF"$'\na\\\nEOF\ncd /var/empty && git -c user.name=t commit -m x\nEOF'
# (( that is two subshells, a command in arithmetic
bgc ask "$D/r" "((git -C /var/empty -c user.name=t commit -m x) && true)"
bgc ask "$D/r" "(( x = \$(git -C /var/empty -c user.name=t commit -m x) ))"
bgc 0 "$REAL" "cd $D/r && (( 1 + (2) )) && git -c user.name=t commit -m x"
# heredocs: an unquoted delimiter runs \$(...) and backticks; git reads a message; \$(cat <<EOF) is text only for git
bgc ask "$REAL" $'cat > f <<EOF\n$(git -c user.name=t commit -m x)\nEOF'
bgc ask "$REAL" $'cat > f <<EOF\n`git -c user.name=t commit -m x`\nEOF'
bgc 0 "$REAL" $'cat > f <<\'EOF\'\n$(git -c user.name=t commit -m x)\nEOF'
bgc 0 "$REAL" "git commit -F - <<'EOF'"$'\nfix: git -c user.name=x commit in the docs\nEOF'
bgc ask "$REAL" $'eval "$(cat <<\'EOF\'\ngit -c user.name=t commit -m x\nEOF\n)"'
bgc ask "$REAL" $'bash -c "$(cat <<\'EOF\'\ngit -c user.name=t commit -m x\nEOF\n)"'
bgc ask "$REAL" $'$(cat <<\'EOF\'\ngit -c user.name=t commit -m x\nEOF\n)'
# a heredoc script with identity text that the command runs: asks when it runs outside /tmp or has cd, -C, chdir, cwd
bgc ask "$REAL" "cat > $D/t.sh <<'EOF'"$'\ngit -c user.name=t commit -m x\nEOF\n'"bash $D/t.sh"
bgc 0 "$REAL" "cat > $D/t.sh <<'EOF'"$'\ngit -c user.name=t commit -m x\nEOF\n'"cd $D/r && bash $D/t.sh"
bgc ask "$REAL" "cd $D/r && cat > t.sh <<'EOF'"$'\ncd /var/empty && git -c user.name=t commit -m x\nEOF\n'"bash t.sh"
bgc ask "$REAL" "cd $D/r && cat > t.py <<'EOF'"$'\nimport os; os.chdir("/var/empty"); os.system("git -c user.name=t commit")\nEOF\n'"python3 t.py"
bgc ask "$REAL" "cat > $D/t.sh <<'EOF'"$'\ngit -c user.name=t commit -m x\nEOF\n'"chmod +x $D/t.sh && $D/t.sh"
bgc ask "$D/r" "cat > t.sh <<'EOF'"$'\ngit -c user.name=t commit -m x\nEOF\n'"sudo bash t.sh"
bgc ask "$D/r" "cat > t.sh <<'EOF'"$'\ngit -c user.name=t commit -m x && git push\nEOF\n'"bash t.sh"
bgc ask "$D/r" "cat > \"\$F\" <<'EOF'"$'\ngit -c user.name=t commit -m x\nEOF'
# a write to a dot file outside /tmp outlives the command; GIT_* of another repo or config, also quoted
bgc ask "$D/r" "echo 'export GIT_AUTHOR_NAME=M' >> ~/.zshrc"
bgc ask "$D/r" "cat >> ~/.zshrc <<'EOF'"$'\nexport GIT_AUTHOR_NAME=M\nEOF'
bgc 0 "$D/r" "echo 'export GIT_AUTHOR_NAME=M' >> $D/r/.envrc"
bgc ask "$D/r" "GIT_CONFIG=\$HOME/.gitconfig git config user.name M"
bgc 0 "$REAL" "cd $D/r && export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1 && git -c user.name=t commit -m x"
bgc 0 "$D/r" "GIT_CONFIG_SYSTEM=/dev/null GIT_CONFIG_NOSYSTEM=\$X git -c user.name=t commit -m x"
bgc ask "$D/r" "GIT_CONFIG_GLOBAL=/var/empty/g git -c user.name=t commit -m x"
bgc ask "$D/r" "GIT_CONFIG_GLOBAL=\$G git -c user.name=t commit -m x"
bgc ask "$D/r" "GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=include.path GIT_CONFIG_VALUE_0=/var/empty/c git -c user.name=t commit -m x"
bgc ask "$D/r" "env \"GIT_DIR=/var/empty/.git\" git -c user.name=t commit -m x"
bgc ask "$D/r" "export \"GIT_DIR=/var/empty/.git\"; git -c user.name=t commit -m x"
bgc ask "$D/r" "env GIT_\\DIR=/var/empty/.git git -c user.name=t commit -m x"
bgc ask "$D/r" "GIT_INDEX_FILE=/var/empty/i git -c user.name=t commit -m x"
# git -c alias. or include.; an unknown or wrapped command word; a function in the way
bgc ask "$D/r" "git -c alias.z='!git -C /var/empty commit' -c user.name=t z"
bgc ask "$D/r" "git -c include.path=/var/empty/c -c user.name=t commit -m x"
bgc ask "$D/r" "git --config-env=alias.z=V -c user.name=t z"
bgc ask "$D/r" "\${GIT:-git} -C /var/empty -c user.name=t commit -m x"
bgc ask "$D/r" "\"\$GIT\" -C /var/empty -c user.name=t commit -m x"
bgc ask "$D/r" "\$(command -v git) -C /var/empty -c user.name=t commit -m x"
bgc ask "$D/r" "=git -C /var/empty -c user.name=t commit -m x"
bgc ask "$D/r" "git \$OPT -C /var/empty -c user.name=t commit -m x"
bgc ask "$D/r" "npm --prefix /var/empty exec git -c user.name=t commit -m x"
bgc ask "$D/r" "pnpm --dir /var/empty exec git -c user.name=t commit -m x"
bgc ask "$D/r" "g() { git -C /var/empty \"\$@\"; }; g -c user.name=t commit -m x"
bgc ask "$D/r" "git() { command git -C /var/empty \"\$@\"; }; git -c user.name=t commit -m x"
bgc ask "$REAL" "cd $D && f() { cd /var/empty; }; f; git -c user.name=t commit -m x"
bgc 0 "$REAL" "cd $D && f() { cd /var/empty; }; git -c user.name=t commit -m x"
bgc 0 "$REAL" "cd $D && f() { echo hi; }; f; git -c user.name=t commit -m x"
# eval forgets the variables; zsh prefixes, chdir, command cd (zsh: /usr/bin/cd, no move), a trap that moves
bgc ask "$REAL" "S=$D/r; eval \"S=/var/empty\"; cd \$S && git -c user.name=t commit -m x"
bgc ask "$REAL" "cd $D/r && noglob cd /var/empty && git -c user.name=t commit -m x"
bgc ask "$REAL" "cd $D/r && repeat 1 cd /var/empty && git -c user.name=t commit -m x"
bgc ask "$REAL" "cd $D/r && chdir /var/empty && git -c user.name=t commit -m x"
bgc ask "$REAL" "cd $D/r && builtin eval 'cd /var/empty' && git -c user.name=t commit -m x"
bgc ask "$REAL" "command cd $D/r && git -c user.name=t commit -m x"
bgc ask "$REAL" "cd $D/r && trap 'cd /var/empty' DEBUG; git -c user.name=t commit -m x"
# identity and a move in different words of a command other than git; after an export a script or a wrapper
bgc ask "$D/r" "GIT_AUTHOR_NAME=Bot bash -c 'cd /var/empty && git commit -m x'"
bgc ask "$D/r" "export GIT_AUTHOR_NAME=Bot; bash -c 'cd /var/empty && git commit -m x'"
bgc ask "$D/r" "export GIT_AUTHOR_NAME=Bot; npm --prefix /var/empty run commit"
bgc ask "$D/r" "export GIT_AUTHOR_NAME=Bot; bash ./t.sh"
bgc ask "$D/r" "echo cd /var/empty '&&' git -c user.name=t commit -m x | bash"
bgc ask "$D/r" "eval cd /var/empty '&&' git -c user.name=t commit -m x"
bgc ask "$D/r" "python3 -c \"import os; os.system('git -c user.name=t commit'); x=['-C']\""
# mkdir without -p needs its parent; cd of an empty value is cd; links ignore case; chroot
bgc ask "$REAL" "mkdir $D/n7/a; cd $D/n7/a; git -c user.name=t commit -m x"
bgc 0 "$REAL" "mkdir $D/n8 $D/n8/a && cd $D/n8/a && git init -q && git -c user.name=t commit -m x"
bgc ask "$REAL" "cd $D/r && S=; cd \$S && git -c user.name=t commit -m x"
bgc ask "$REAL" "cd $D && ln -s /var/empty L9 && git -C l9 -c user.name=t commit -m x"
bgc ask "$D/r" "chroot / git -c user.name=t commit -m x"
# a loop, a background list or group that changes the folder or a variable
bgc ask "$REAL" "cd $D/r; for i in 1 2; do git -c user.name=t commit -q -m x; cd /var/empty; done"
bgc ask "$REAL" "S=$D/r; for i in 1 2; do (cd \$S && git -c user.name=t commit -q -m x); S=/var/empty; done"
bgc ask "$REAL" "{ cd $D/r; git -c user.name=t commit -m x; } & git -c user.name=t commit -m y"
bgc ask "$REAL" "S=$D/r && true & cd \$S && git -c user.name=t commit -m x"
# a cd after a command of its && list that may fail: the folder past the list is unknown
bgc ask "$REAL" "test -f /nonexistent && cd $D/r; git -c user.name=t commit -m x"
bgc ask "$REAL" "grep -q zzz /dev/null && { cd $D/r; }; git -c user.name=t commit -m x"
bgc 0 "$REAL" "mkdir -p $D/m1 && cd $D/m1"$'\n'"git init -q"$'\n'"git -c user.name=t commit -m x"
bgc 0 "$REAL" "rm -rf $D/m2 && mkdir -p $D/m2 && cd $D/m2; git init -q; git -c user.name=t commit -m x"
bgc 0 "$REAL" "git init -q $D/m3 && cd $D/m3; git -c user.name=t commit -m x"
# copies that bring a repo or a link of elsewhere, a file copy does not; a write into .git; a link by python
mkdir -p "$D/lk" "$D/inc2/.git" "$D/url/.git" && ln -s /var/empty "$D/lk/l"
bgc ask "$REAL" "cp -R $D/wt $D/c1 && git -C $D/c1 -c user.name=t commit -m x"
bgc ask "$REAL" "cp -R $D/lk $D/c2 && git -C $D/c2/l -c user.name=t commit -m x"
bgc ask "$REAL" "cp -R $D/wt $D/c3 && cp -R $D/c3 $D/c4 && git -C $D/c4 -c user.name=t commit -m x"
bgc 0 "$REAL" "mkdir -p $D/c5 && cp \"$H/bash-guard.sh\" $D/c5/ && cd $D/c5 && git init -q && git -c user.name=t commit -m x"
bgc ask "$REAL" "cd $D/r && cp -t /var/empty x && git -c user.name=t commit -m x"
bgc ask "$REAL" "cd $D/r && cp /var/empty/x .git/config && git -c user.name=t commit -m x"
bgc ask "$REAL" "mkdir -p $D/g6 && cd $D/g6 && printf 'gitdir: /var/empty/.git' > .git && git -c user.name=t commit -m x"
bgc ask "$REAL" "cd $D/r && printf 'cd /var/empty' > .git/hooks/post-commit && git -c user.name=t commit -m x"
bgc ask "$REAL" "python3 -c 'import os; os.symlink(\"/var/empty\", \"$D/sl\")' && cd $D/sl && git -c user.name=t commit -m x"
mkdir -p "$D/big" "$D/fx" && (cd "$D/big" && touch $(seq 1 2001)) && touch "$D/fx/a.txt" "$D/fx/b.txt"
bgc ask "$REAL" "cp -R $D/link $D/c6 && git -C $D/c6 -c user.name=t commit -m x"
bgc ask "$REAL" "cp -R $D/nothere $D/c7 && git -C $D/c7 -c user.name=t commit -m x"
bgc ask "$REAL" "mkdir -p $D/c8 && cp $D/wt/.git $D/c8/ && git -C $D/c8 -c user.name=t commit -m x"
bgc ask "$REAL" "cp -R $D/big $D/c9 && git -C $D/c9 -c user.name=t commit -m x"
bgc ask "$REAL" "cp -R $D/r $D/nx/c; cd $D/nx; git -c user.name=t commit -m x"
bgc 0 "$REAL" "mkdir -p $D/mm && cp -R $D/mm $D/mm2 && cd $D/mm2 && git init -q && git -c user.name=t commit -m x"
bgc 0 "$REAL" "mkdir -p $D/c11 && cp $D/fx/*.txt $D/c11/ && cd $D/c11 && git init -q && git -c user.name=t commit -m x"
bgc ask "$D/r" "echo 'export GIT_AUTHOR_NAME=M' >> $D/link/.zshrc"
bgc ask "$D/r" "ln -s /var/empty $D/hl && echo 'export GIT_AUTHOR_NAME=M' >> $D/hl/.zshrc"
bgc ask "$D/r" "echo 'export GIT_AUTHOR_NAME=M' >& ~/.zshrc"
bgc ask "$D/r" "printf 'gitdir: /var/empty/.git' > \"\$F\"; git -c user.name=t commit -m x"
# a repo config: every [section] of a line counts; a url rewrite
printf '[core][include]\n\tpath = /var/empty/x\n' > "$D/inc2/.git/config"
printf '[url "/var/empty/"]\n\tinsteadOf = /tmp/fake/\n' > "$D/url/.git/config"
bgc ask "$REAL" "cd $D/inc2 && git -c user.name=t commit -m x"
bgc ask "$REAL" "cd $D/url && git -c user.name=t commit -m x"
# more forms: a heredoc that only stays text, a script or a program we do not read, the env wrapper, -c $KEY
bgc 0 "$REAL" "cat > $D/notes.md <<'EOF'"$'\ncd /var/empty && git -c user.name=t commit -m x\nEOF'
bgc 0 "$REAL" $'tee notes.md <<\'EOF\'\nexport GIT_AUTHOR_NAME=t\nEOF'
bgc ask "$REAL" $'X=$(cat <<\'EOF\'\ngit -c user.name=t commit -m x\nEOF\n)'
bgc ask "$D/r" "cat > t.sh <<'EOF'"$'\nnpm --prefix /var/empty exec git -c user.name=t commit\nEOF\n'"bash t.sh"
bgc ask "$D/r" "echo 'git -c user.name=t commit -m x && git push' | bash"
bgc ask "$D/r" "GIT_AUTHOR_NAME=Bot bash ./t.sh"
bgc 0 "$D/r" "GIT_AUTHOR_NAME=Bot bash -c 'git commit -m x'"
bgc ask "$D/r" "\$X bash -c 'git -c user.name=t commit -m x'"
bgc ask "$D/r" "export GIT_AUTHOR_NAME=Bot; \$X bash -c 'git commit -m x'"
bgc ask "$D/r" "GIT_DIR=\$X git -c user.name=t commit -m x"
bgc ask "$D/r" "alias g='git -C /var/empty'; g -c user.name=t commit -m x"
bgc ask "$D/r" "env --chdir=/var/empty git -c user.name=t commit -m x"
bgc ask "$D/r" "git -c \"\$K=v\" -c user.name=t commit -m x"
bgc 0 "$D/r" "env GIT_AUTHOR_NAME=t git commit -m 'fix cd'"
bgc ask "$D/r" "command cd /var/empty && git -c user.name=t commit -m x"
bgc 0 "$REAL" "HOME=$D/r; cd && git -c user.name=t commit -m x"
bgc 0 "$REAL" "HOME=$D/r; cd ~/ && git -c user.name=t commit -m x"
bgc ask "$REAL" "test -f /x && cd $D/r || git -c user.name=t commit -m x"
bgc ask "$REAL" "{ false; } && cd $D/r; git -c user.name=t commit -m x"
bgc ask "$REAL" "(false) && cd $D/r; git -c user.name=t commit -m x"
bgc ask "$REAL" "(( 0 )) && cd $D/r; git -c user.name=t commit -m x"
bgc ask "$REAL" "{ cd $D/r; } | cat; git -c user.name=t commit -m x"
# more continuations: an even run of backslashes, before an operator, in quotes, in a script, in a doubted command
bgc ask "$D/r" "cat > f <<EOF"$'\na\\\\\nEOF\ncd /var/empty && git -c user.name=t commit -m x'
bgc ask "$REAL" "cd $D/r && git \\"$'\n'" -C /var/empty -c user.name=t commit -m x"
bgc ask "$REAL" "cat <<'EOF' \\"$'\n'"| bash"$'\ngit -c user.name=t commit -m x\nEOF'
bgc 0 "$REAL" "cd \"$D/\\"$'\n'"r\" && git -c user.name=t commit -m x"
bgc ask "$D/r" "GIT_AUTHOR_NAME=Bot bash -c 'cd\\"$'\n'" /var/empty && git commit -m x'"
bgc ask "$D/r" "bash <<'EOF'"$'\ncd\\\n /var/empty && git -c user.name=t commit -m x\nEOF'
bgc ask "$D/r" "case x in a) ;; esac; git -c \\"$'\n'"user.name=t commit -m x"
# more of what the reader does not follow: a glob (q* is there), a pipe after a continuation (also after a }), sudo
# with a script, a zsh =command, a script file with a heredoc, -C in quotes, a heredoc piped to a program we do not
# know, a for list (also after a cd that may not run), --separate-git-dir in a folder that is there
bgc ask "$REAL" "cd $D/q* && git -c user.name=t commit -m x"
bgc ask "$REAL" "cd $D/r \\"$'\n'"| cat; git -c user.name=t commit -m x"
bgc ask "$REAL" "cd $D/r && sudo bash -c 'git -c user.name=t commit -m x'"
bgc ask "$REAL" "cd $D/r && =git -c user.name=t commit -m x"
bgc ask "$REAL" "cd $D/r && bash ./x.sh <<'EOF'"$'\ngit -c user.name=t commit -m x\nEOF'
bgc ask "$REAL" "cd $D/r && bash <<'EOF'"$'\ngit "-C" /var/empty -c user.name=t commit -m x\nEOF'
bgc ask "$REAL" "tee x.txt <<'EOF' | fish"$'\ngit -c user.name=t commit -m x\nEOF'
bgc ask "$REAL" 'for c in "git -c user.name=t commit -m x"; do $c; done'
bgc ask "$REAL" "test -d $D/r && cd $D/r; for c in 'git -c user.name=t commit -m x'; do \$c; done"
bgc ask "$REAL" "{ cd $D/r; } \\"$'\n'"| cat; git -c user.name=t commit -m x"
bgc ask "$REAL" "cd $D/r && git init -q --separate-git-dir=/var/empty/x.git && git -c user.name=t commit -m x"
. "$H/dirs-more-tests.sh"
# BASH_GUARD_DIRS_DEBUG=1 names the reason of a doubt
py=/opt/homebrew/bin/python3
[ -x "$py" ] || py=/usr/bin/python3
out=$(printf '{"tool_input":{"command":"case x in a) ;; esac; git -c user.name=t commit"},"cwd":"%s"}' "$D/r" |
  BASH_GUARD_DIRS_DEBUG=1 "$py" -I "$H/bash-guard-dirs.py" 2>&1 >/dev/null)
[ "$out" = 'doubt: case' ] || { echo "FAIL BASH_GUARD_DIRS_DEBUG=1 gives no reason of a doubt: $out"; f=1; }
# a NUL goes as bash drops it; the terminal tool runs in its own folder
out=$(printf '{"tool_input":{"command":"git -c user.na\\u0000me=t commit -m x"},"cwd":"%s"}' "$REAL" |
  PATH=$D/bin:/usr/bin:/bin "$H/bash-guard.sh" 2>/dev/null)
[[ $out == *'"ask"'* ]] || { echo "FAIL a NUL inside user.name hides the identity"; f=1; }
out=$(printf '%s' "git -c user.name=t commit -m x" | /usr/bin/jq -Rs --arg c "$D/r" \
  '{tool_name:"mcp__terminal__run_in_terminal",tool_input:{command:.},cwd:$c}' | PATH=$D/bin:/usr/bin:/bin "$H/bash-guard.sh" 2>/dev/null)
[[ $out == *'"ask"'* ]] || { echo "FAIL the terminal tool runs in the session folder"; f=1; }
# the second check reads only the kept parts: the owner's identity there passes; a kept text over RESCAN_MAX (8000
# characters) or after a first scan of RESCAN_SECS asks as before (no second scan)
ON=$(git config --global user.name); OE=$(git config --global user.email)
if [ -n "$ON" ] && [ -n "$OE" ]; then
  own="cd /var/empty && git -c user.name=\"$ON\" -c user.email=$OE commit -m"
  bgc 0 "$REAL" "cd $D/r && git -c user.name=t commit -m x; $own x"
  BASH_GUARD_RESCAN_SECS=0 bgc ask "$REAL" "cd $D/r && git -c user.name=t commit -m x; $own x"
  bgc ask "$REAL" "cd $D/r && git -c user.name=t commit -m x; $own \"$(printf 'word %.0s' {1..1600})\""
  bgc 0 "$REAL" "cd $D/r && git -c user.name=t commit -m x; $own \"$(printf 'word %.0s' {1..1550})\""
  # a for list after a cd that may not run: only the list is kept, and it has the owner's name
  bgc 0 "$REAL" "cd $D/r && git -c user.name=t commit -m x; test -d $D/r && cd $D/r; for c in 'git -c user.name=\"$ON\" commit'; do \$c; done"
fi
# python missing or broken: the ask of before and one line in the error log
C=$(mktemp -d) && cp "$H/bash-guard.sh" "$C/"
shim(){ # shim <python> <log word>
  printf '%s\n' "$1" > "$C/bash-guard-dirs.py"; rm -f "$C/err.log"
  out=$(printf '%s' "cd $D/r && git -c user.name=t commit -m x" | /usr/bin/jq -Rs --arg c "$REAL" '{tool_input:{command:.},cwd:$c}' |
    BASH_GUARD_ERRLOG="$C/err.log" PATH=$D/bin:/usr/bin:/bin "$C/bash-guard.sh" 2>/dev/null)
  [[ $out == *'"ask"'* ]] && grep -q "Z $2\$" "$C/err.log" || { echo "FAIL broken bash-guard-dirs.py: no ask or no $2 line"; f=1; }
}
shim 'raise SystemExit(3)' 'ShimExit 3 bash-guard-dirs.py'
shim 'import sys; sys.stdout.write("error KeyError"); sys.exit(1)' 'ShimExit 1 KeyError bash-guard-dirs.py'
shim 'print("git commit")' 'ShimOutput bash-guard-dirs.py'
printf '{"tool_input":{"command":"cd %s/r && git -c user.name=t commit -m x"}}' "$D" |
  BASH_GUARD_ERRLOG="$C/err.log" PATH=$D/bin:/usr/bin:/bin "$H/bash-guard.sh" >/dev/null 2>&1   # no cwd: the input changed
grep -q 'Z ShapeDrift cwd$' "$C/err.log" || { echo "FAIL no ShapeDrift line for an input without cwd"; f=1; }
out=$(printf '{"tool_input":{"command":["cd %s/r && git -c user.name=t commit -m x"]},"cwd":"%s"}' "$D" "$REAL" |
  BASH_GUARD_ERRLOG="$C/err.log" PATH=$D/bin:/usr/bin:/bin "$H/bash-guard.sh" 2>/dev/null)   # a command that is no string
[[ $out == *'"ask"'* ]] && grep -q 'Z ShapeDrift tool_input.command$' "$C/err.log" ||
  { echo "FAIL no ask or no ShapeDrift line for a command that is no string"; f=1; }
head -c 32001 /dev/zero | tr '\0' x > "$C/err.log"   # ShapeDrift stops at DRIFT_CAP, a dying helper still logs
printf '{"tool_input":{"command":"cd %s/r && git -c user.name=t commit -m x"}}' "$D" |
  BASH_GUARD_ERRLOG="$C/err.log" PATH=$D/bin:/usr/bin:/bin "$H/bash-guard.sh" >/dev/null 2>&1
[ "$(wc -c <"$C/err.log" | tr -d ' ')" = 32001 ] || { echo "FAIL a ShapeDrift line past DRIFT_CAP"; f=1; }
printf '%s' "cd $D/r && git -c user.name=t commit -m x" | /usr/bin/jq -Rs --arg c "$REAL" '{tool_input:{command:.},cwd:$c}' |
  BASH_GUARD_ERRLOG="$C/err.log" PATH=$D/bin:/usr/bin:/bin "$C/bash-guard.sh" >/dev/null 2>&1
grep -q 'Z ShimOutput bash-guard-dirs.py$' "$C/err.log" || { echo "FAIL no line of a dying helper past DRIFT_CAP"; f=1; }
head -c 64001 /dev/zero | tr '\0' x > "$C/err.log"   # a full log gets no more lines
printf '%s' "cd $D/r && git -c user.name=t commit -m x" | /usr/bin/jq -Rs --arg c "$REAL" '{tool_input:{command:.},cwd:$c}' |
  BASH_GUARD_ERRLOG="$C/err.log" PATH=$D/bin:/usr/bin:/bin "$C/bash-guard.sh" >/dev/null 2>&1
[ "$(wc -c <"$C/err.log" | tr -d ' ')" = 64001 ] || { echo "FAIL bash-guard error log grew past its cap"; f=1; }
printf '%s' "cd $D/r && git -c user.name=t commit -m x" | /usr/bin/jq -Rs --arg c "$REAL" '{tool_input:{command:.},cwd:$c}' |
  env -u BASH_GUARD_ERRLOG HOME="$C/home" PATH=$D/bin:/usr/bin:/bin "$C/bash-guard.sh" >/dev/null 2>&1   # the log doctor reads
grep -q 'Z ShimOutput bash-guard-dirs.py$' "$C/home/.claude/logs/bash-guard.err" 2>/dev/null || { echo "FAIL no line in ~/.claude/logs/bash-guard.err"; f=1; }
rm -rf "${C:?}"
# a byte that is no UTF-8, with either locale in the process (the hook itself runs under C): the ask stays
for l in C en_US.UTF-8; do
  for c in 'git -c user.name=Bot\udc80 commit -m x' 'git commit -m x --author \"B\udc80 <b@example.com>\"' \
      'git -c user.name=Bot commit -m x \udc80' 'GIT_AUTHOR_NAME=Bot\udc80 git commit -m x'; do
    out=$(printf '{"tool_input":{"command":"%s"},"cwd":"%s"}' "$c" "$REAL" | LC_ALL=$l PATH=$D/bin:/usr/bin:/bin "$H/bash-guard.sh" 2>/dev/null)
    [[ $out == *'"ask"'* ]] || { echo "FAIL no ask with a raw byte under LC_ALL=$l: $c"; f=1; }
    out=$(printf '{"tool_input":{"command":"%s"},"cwd":"%s/r"}' "$c" "$D" | LC_ALL=$l PATH=$D/bin:/usr/bin:/bin "$H/bash-guard.sh" 2>/dev/null)
    [ -z "$out" ] || { echo "FAIL an ask with a raw byte in a one-off repo under LC_ALL=$l: $c"; f=1; }
  done
done
out=$(printf '{"tool_input":{"command":"git -c user.name=Bot\\udc80 commit -m x"},"cwd":"%s"}' "$REAL" | /usr/bin/python3 -I "$H/bash-guard-dirs.py" 2>&1)
[ "$out" = $'git -c user.name=Bot? commit -m x\nend' ] || { echo "FAIL the text of a raw byte under /usr/bin/python3: $out"; f=1; }
[ -s "$BASH_GUARD_ERRLOG" ] && { echo "FAIL bash-guard logged: $(head -1 "$BASH_GUARD_ERRLOG")"; f=1; }
rm -rf "${D:?}"
[ $f -eq 0 ] && echo "DIRS OK"
