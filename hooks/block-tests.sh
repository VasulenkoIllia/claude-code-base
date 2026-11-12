#!/bin/bash
# shellcheck disable=SC2154,SC2034   # D, H, f, bg and bgc come from extra-tests.sh, which sources this file
# The block rules of 11.11.2026: a print of an env file and docker compose config block with the reason that names what
# passes (they were asks), grep, sed and awk read an env file too, rm -r also as \rm or /bin/rm and on a folder of home
# that nothing makes again
reason(){ printf '%s' "$1" | /usr/bin/jq -Rs '{tool_input:{command:.},cwd:"/tmp"}' | { PATH=$D/bin:/usr/bin:/bin "$H/bash-guard.sh" >/dev/null; } 2>&1; }   # its stderr
# cat, head, tail, less, more, bat: a block; an example, a mask on the same line and a count pass
bg 2 'cat .env.example; cat .env'   # every read is looked at, the first one is an example
bg 2 'cat .env| tee x'
bg 0 'cat .env|cut -d= -f1'         # the match ends with the | itself
bg 2 'cat .env | cut -d= -f1; cat .env'
many=$(printf 'cat .env.example; %.0s' {1..20}); bg 0 "$many"; bg 0 "${many//cat/grep KEY}"
bg 2 "$many cat .env.example"; bg 2 "${many//cat/grep KEY} grep KEY .env.example"   # over 20 reads are not looked at one by one
out=$(reason 'cat .env')
[[ $out == 'BLOCKED by bash-guard: printing an env file puts its values'*'.env.example'*'| cut -d= -f1'*'len=${#VAR}'*'Use a form named here'* ]] &&
  [[ $out != *"don't work around"* ]] || { echo "FAIL the block of an env print names no form that passes, or forbids them: $out"; f=1; }
# every file of a command counts, an example next to it or a plain file before it; a quoted name, a glob, a longer suffix
for c in 'cat .env.example .env' 'grep KEY .env.example .env.local' 'grep -h KEY .env .env.example' 'cat README.md .env' 'head -3 a.txt .env' \
    'grep KEY settings.dist .env' 'cat .env*' 'cat .env.*' 'cat ".env"' 'cat "$PWD/.env"' 'grep KEY "$APP/.env.local"' "head -2 '.env'" \
    '/bin/cat .env' '/usr/bin/grep KEY .env' 'cat < .env' 'cat .env.prod-2' 'tail -n 3 .env.staging_eu' 'cat "my dir/.env.example" .env'; do
  bg 2 "$c"
done
# a file that the command writes, a file-name filter and a quoted pattern with the word in it are no read
for c in $'cat > .env <<\'EOF\'\nA=1\nEOF' "sed 's/x/y/' .env.example > .env" 'cat a.txt >> "$DIR/.env"' 'cat a.txt > "my dir/.env"' \
    'grep -rn TODO . --exclude=.env' 'grep -rn KEY --include="*.env" .' 'grep -e foo -e "uses .env vars" README.md' \
    'grep -e foo -e "\.env" README.md' 'cat "$DIR/.env.example"' "cat 'my dir/.env.sample' x.dist" 'grep KEY .env.example; echo see .env' \
    'cat .env.example && echo copy it to .env' 'grep -q KEY a.txt || echo "add KEY to .env"' 'x="run with --env-file a.env"; cat a.txt'; do
  bg 0 "$c"
done
# a long script: a match that starts inside a string does not run over the lines to a string that ends with .env (the
# first case is a command of the replay of 11.11 with its words made neutral: the rules before WL blocked it); a
# quoted name with a blank in it is not seen
bg 0 $'cd d/w && bash -c \'\ncompose="docker compose -p w -f d/w -f d/w --env-file d/.env.example --env-file d/x.env --env-file $Vd/x.env"\n$V exec -T w sh -c "w; grep w d/w"\n$V w -v w>&w | tail -n w\''
bg 0 $'cat > /tmp/s.sh <<\'EOF\'\necho "top: $(ls | head -1)"\necho "-- .env --"\nstat -c "%y" "$d/.env" 2>/dev/null\ngrep -oE "^[A-Z_]+=" "$d/.env" | tr -d "="\nEOF'
bg 0 'grep KEY "app dir/.env"'
# a mask after a pipe on the same line, read with the case of the letters: grep -C is context
for c in 'cat .env | grep -C 2 KEY' 'cat .env | head -3' 'cat .env | sort' $'cat .env\n echo x | cut -d= -f1' 'cat .env; ls | wc -l'; do bg 2 "$c"; done
for c in "cat .env | awk -F= '{print \$1}'" "cat .env | sed 's/=.*//'" "grep -v '^#' .env | sed -E 's/=.+\$/=***/'" 'cat .env | cut -d "=" -f 1 | sort' \
    'cat .env | grep -c KEY' 'head -5 .env | wc -l' 'grep DATABASE_URL .env | sed "s/:[^:@]*@/:***@/"'; do
  bg 0 "$c"
done
# grep, sed, awk: the file after the pattern or the script
for c in 'grep -n KEY .env' 'grep -E "^(A|B)=" .env.production' "sed -n '1,5p' .env" "awk -F= '{print \$2}' .env" 'grep -e KEY .env' \
    'grep -C2 KEY .env' 'cd app && grep DATABASE_URL config/stage.env' 'grep KEY .env.example; grep KEY .env' 'grep KEY ~/proj/.env.local' \
    "sed 's/a/b/' app.env" 'grep KEY .env | head -3' 'grep -i key .env; grep -c KEY .env' 'grep -eKEY .env' 'grep --regexp=KEY .env' \
    "sed -e'p' .env" 'sed --expression=p .env' 'grep -ve -zzz .env'; do
  bg 2 "$c"
done
for c in 'grep -c KEY .env' 'grep -q "^KEY=" .env && echo set' 'grep -l KEY .env .env.local' 'grep -qE "^A=" .env' 'grep --count KEY .env' \
    'grep -L KEY .env' 'grep --quiet KEY .env' 'grep --silent KEY .env' 'grep --files-with-matches KEY .env' 'grep --files-without-match KEY .env' \
    'grep KEY .env | cut -d= -f1' "grep -v '^#' .env | wc -l" 'grep KEY .env.example' 'grep KEY .env 1>/dev/null' \
    "sed -i '' 's/^A=.*/A=1/' .env" "sed -i.bak -e 's/^A=.*/A=1/' .env" "sed --in-place 's/a/b/' .env" "sed -Ei 's/a/b/' .env" \
    "sed 's/=.*/=***/' .env" 'sed -e "s/=.*//" -e 5q .env.production' "sed -E 's|=.+|=|' app.env" \
    'grep -E "^KEY=" .env >/dev/null && echo set' 'grep KEY .env > /dev/null 2>&1; echo $?' 'cat .env &>/dev/null' \
    "grep -oE '^[A-Z_]+=' .env" "grep -o '^KEY=' .env | head" 'grep -no "^[A-Z0-9_]*=" .env.production' "grep -E -o '^[^=]+=' app.env" \
    "grep -o -E '^(DB|REDIS)_[A-Z]+=' .env .env.local" "ssh host \"grep -oE '^[A-Z_]+=' /srv/app/.env\""; do
  bg 0 "$c"
done
# an option before the one that counts takes it as its value: -e -l is the pattern -l, -ec the pattern c
for c in 'grep -e -l -e KEY .env' 'grep -ec KEY .env' 'grep -e KEY -c .env' 'grep -m -c KEY .env' "grep -e -o '^[A-Z_]+=' .env" \
    "grep -fo '^[A-Z_]+=' .env" "sed -e p -e 's/=.*//' .env" "sed -e -i 's/a/b/' .env" "sed -n -e p -e 's/=.*//' .env"; do
  bg 2 "$c"
done
for c in 'grep -ic key .env' 'grep -Eq "^A=" .env' 'grep -rl KEY .env' 'grep -i -c -e KEY .env' "sed -n -E -i.bak 's/a/b/' .env" \
    '/usr/bin/grep -c KEY .env' "/usr/bin/sed 's/=.*//' .env" \
    "sed -n -e 's/=.*//p' .env" "sed -En 's/=.*//p' .env"; do
  bg 0 "$c"
done
# grep -o: a pattern that may run into the value prints it, one with no ^ finds the = inside a value, -v prints the
# other lines whole
for c in "grep -o '.*=' .env" "grep -o 'KEY=.*' .env" "grep -oE '[A-Za-z0-9_=]*=' .env" "grep -oE '^[A-Z_]+=.' .env" "grep -oE '[^ ]*=' .env" \
    "grep -E '^[A-Z_]+=' .env" "grep -O '^[A-Z_]+=' .env" "grep -o --include='^A=' KEY .env" "grep -o '[A-Za-z0-9_]*=' .env" \
    "grep -o 'KEY=' .env" "grep -ov '^ZZ=' .env" "grep -v -o '^ZZ=' .env"; do
  bg 2 "$c"
done
# a script that cuts the values of one key only, stderr to /dev/null and a file as the output still print or keep them
for c in "sed 's/PASSWORD=.*/PASSWORD=x/' .env" 'grep KEY .env 2>/dev/null' 'grep KEY .env > /tmp/out.txt' "sed -n 's/^A=//p' .env" \
    "sed 's/=.*/&/' .env" "sed -n 's/=.*/&/p' .env" "sed 's/=.*/\\0/' .env" "sed 's/=.*//w /dev/stdout' .env" "sed -i '' 'w /dev/stdout' .env" \
    "sed 's/=.*//e' .env" \
    'cat .env >/dev/null >&2' 'grep KEY .env > /dev/null 1>&2' "sed -n 'w /dev/stderr' .env >/dev/null"; do
  bg 2 "$c"
done
# the word .env as a pattern or as text is no file
for c in 'grep -rn process.env src/' 'grep -rn process.env.PORT src' 'ls -a | grep -v .env' 'ls -la | grep -i .env' 'grep -rn "\.env" docs/' \
    'git status --short | grep .env' 'grep -rn dotenv .' 'sed -n 5p README.md' "echo 'grep KEY .env'" 'grep -rn import.meta.env src' \
    'awk -F= "{print \$1}" notes.txt'; do
  bg 0 "$c"
done
# compose config: the listing flags and a file pass, as before
bg 2 'docker-compose config'; bg 2 'docker compose config -q; docker compose config'
bg 0 'docker compose config --services'; bg 0 'docker compose config -o /tmp/c.yml'; bg 0 'docker compose config > /tmp/c.yml'
# only options of docker and of compose before config: a block; any other word there asks, as before
for c in 'docker compose -f a.yml --env-file .env.prod config' 'docker --context prod compose config' 'docker compose --profile x config --format json' \
    'docker-compose -p app -f docker-compose.prod.yml convert'; do
  bg 2 "$c"
done
bg ask 'docker compose exec app npm config get registry'; bg ask 'docker compose $ARGS config'; bg ask 'docker compose run --rm app config'
bg 0 'docker compose -f a.yml config --services'; bg 0 'docker compose exec app npm config get registry -q'; bg 0 'docker compose exec app npm run build'
# a block comes before any ask: an ask rule or an identity next to it hides nothing, and with no block it still asks
bg 2 'docker volume prune; cat .env'; bg 2 'git reset --hard; docker compose config'; bg ask 'docker volume prune; cat .env.example'
bgc 2 "$REAL" 'git -c user.name=Bot commit -m x; cat .env'
bgc ask "$REAL" 'git -c user.name=Bot commit -m x; cat .env | cut -d= -f1'
bg 0 "docker exec test-db sh -c 'grep KEY .env'"; bg 0 $'cat > /tmp/doc.md <<\'EOF\'\ngrep KEY .env\ndocker compose config\nEOF'
# rm -r: \rm, /bin/rm, /usr/bin/rm
for c in '\rm -rf ~' '/bin/rm -rf $HOME' '/usr/bin/rm -rf "$HOME"' 'cd /tmp; \rm -rf ~/' '/bin/rm -r -f /' "bash -c '/bin/rm -rf ~'"; do bg 2 "$c"; done
for c in '/bin/rm -rf dist' '\rm -rf build' '/usr/bin/rm -rf node_modules/.cache' '/bin/rm ~/x.log'; do bg 0 "$c"; done
# a folder of the first level of home: itself or its /*; a path inside it and a folder with a longer name pass
for c in 'rm -rf ~/WebstormProjects' 'rm -rf ~/.claude' 'rm -rf ~/.ssh/' 'rm -rf ~/project-docs/*' 'rm -rf ~/claude-time' 'rm -rf $HOME/.claude' \
    'rm -rf "${HOME}/WebstormProjects"' "rm -rf '/Users/someone/.ssh'" 'rm -rf /Users/someone/Documents' '/bin/rm -rf ~/Projects' \
    'rm -fr ~/.claude; ls' 'rm -r --force ~/.ssh' 'rm --recursive ~/project-docs' 'sudo rm -rf ~/.claude' 'rm -rf "$HOME/.claude"/*' \
    'rm -rf "$HOME"/.claude' 'rm -rf "${HOME}"/.ssh/*' '(rm -rf ~/.ssh)' 'echo "$(rm -rf ~)"' '(cd /tmp && rm -rf ~/WebstormProjects)'; do
  bg 2 "$c"
done
out=$(reason 'rm -rf ~/.claude')
[[ $out == 'BLOCKED by bash-guard: rm -r on a system or home directory, or on a folder of home'* ]] || { echo "FAIL the block of rm -r: $out"; f=1; }
for c in 'rm -rf ~/WebstormProjects/app/dist' 'rm -rf ~/.claude/logs/old' 'rm -rf ~/projects-old' 'rm -rf ~/claude-time-test' \
    'rm -rf "$HOME/WebstormProjects/app/node_modules"' 'rm -rf ~/Documents/tmp' 'rm ~/.claude/logs/x.log' 'ls ~/.ssh' 'rm -rf ./.claude' \
    'rm -rf .claude/worktrees/x' 'rm -rf ~/tmp/build' 'rm -rf ~/.claude-old' 'echo "rm -rf ~/.claude"' 'rm -rf "$HOME"/tmp/build' '(rm -rf dist)' \
    'rm -rf "$HOME"/.claude/logs/old'; do
  bg 0 "$c"
done
