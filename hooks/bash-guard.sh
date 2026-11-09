#!/bin/bash
# PreToolUse (Bash|Monitor|mcp__terminal__run_in_terminal): blocks destructive commands, asks about risky ones
# exit 2 = hard block; JSON permissionDecision "ask" = ask the user; exit 0 = allow
SECONDS=0   # past RESCAN_SECS every step that takes time gives up and asks: past the hook timeout nothing asks
RESCAN_SECS=${BASH_GUARD_RESCAN_SECS:-3}
LEAKS_SECS=${BASH_GUARD_LEAKS_SECS:-10}   # gitleaks stops here on the same clock, the steps after it have the rest of the
                                          # 15 s (BASH_GUARD_LEAKS_SECS: tests only)
LEAKS_CODE=17   # gitleaks exits with 1 on a broken config or a failed fork as well: with this code only a finding does
unchecked=""   # what section 2 could not check: it goes ahead of the reason in any ask after it
MAX_CMD=300000   # bytes, three times the longest real command of 60 days: split_first still grows with the square of the
                 # place of its match, and past about 1 MB one call takes the whole hook timeout
export LC_ALL=C  # bytes, as in the app, whose hooks have no LANG: in eucJP or GBK a text before a command hides it
DRIFT_CAP=32000   # bytes: a ShapeDrift line comes with every call while the input stays odd, so it stops there and
                  # leaves room for the line of a helper that dies later (the log stops at 64000)
guard_log(){   # guard_log <line> [cap]
  local log=${BASH_GUARD_ERRLOG:-$HOME/.claude/logs/bash-guard.err}
  [ "$(wc -c 2>/dev/null <"$log" | tr -d ' ')" -gt "${2:-64000}" ] 2>/dev/null ||
    { mkdir -p "$(dirname "$log")" && date -u "+%Y-%m-%dT%H:%M:%SZ $1" >>"$log"; } 2>/dev/null
}
ask(){   # a literal JSON: jq may be dead, and printf needs no fork. A reason is a fixed text, or a host or a branch that a
  # regex has checked, and $unchecked a fixed text with a number: nothing to escape
  printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"ask","permissionDecisionReason":"bash-guard: %s%s"}}\n' "$unchecked" "$1"
  exit 0
}
unread(){   # unread <line> [cap]: the command stays unknown: a line in the log and an ask. The line goes into the ask too, as
  # it may stay out of the log. Each line is a fixed text
  guard_log "$@"
  ask "вхід хука не прочитано, команду не перевірено ($1; лог ~/.claude/logs/bash-guard.err)"
}
died(){   # the EXIT trap: a fork that fails in this shell ends it with 128 at that line, and the command would pass with no
  # check (one that fails inside a $(...) only empties its result). No fork in here: no date in the line, no mkdir, no cap
  [ "$1" = 0 ] || [ "$1" = 2 ] && return
  { printf 'no-time HookExit %s\n' "$1" >>"${BASH_GUARD_ERRLOG:-$HOME/.claude/logs/bash-guard.err}"; } 2>/dev/null
  ask "хук зупинився, команду не перевірено (HookExit $1; лог ~/.claude/logs/bash-guard.err)"
}
trap 'died $?' EXIT
in_time(){ [ "$SECONDS" -lt "$RESCAN_SECS" ]; }
split_first(){   # split_first <text> <part>: $before and $after, the text around the first <part>. A long command stays in
  # time only this way: ${s/"$m"/ }, ${s//...} and ${s#*"$m"} in bash 3.2 try every end at every start: 16 s on 30 KB
  # against 8 ms
  before=${1%%"$2"*}; after=${1:${#before}+${#2}}
}
in=$(cat)
[ -n "$in" ] || unread 'ShapeDrift input' "$DRIFT_CAP"
cmd=$(printf '%s' "$in" | /usr/bin/jq -er '.tool_input | objects | .command | strings' 2>/dev/null); rc=$?
# jq-1.7.1 with -e: 4 is no string there, 5 is input that is not JSON (a lone \ud800 too) or that has no fields; any other
# code (usage, does not compile, missing, killed) is a dead jq. Only Monitor on a WebSocket comes with no command
case $rc in
  0) ;;
  4) printf '%s' "$in" | /usr/bin/jq -e '.tool_name == "Monitor" and .tool_input.command == null
       and (.tool_input.ws | type) == "object"' >/dev/null 2>&1 && exit 0
     unread 'ShapeDrift tool_input.command' "$DRIFT_CAP" ;;
  5) unread 'ShapeDrift input' "$DRIFT_CAP" ;;
  *) unread "JqExit $rc" ;;
esac
[ -z "$cmd" ] && exit 0
[ ${#cmd} -le $MAX_CMD ] || unread 'TimeLimit long command'
left=$cmd; cmd=""; glued=""; inword=""   # a backslash-newline continuation is one line for the rules below, a blank in its
# place. Inside a word the shell glues the parts, so then the glued text comes too, as one more line. The blank stays, as a
# comment ends at the newline whatever stands before it. A \\ before the newline: one backslash in a double-quoted script
while [[ $left == *\\$'\n'* ]]; do
  split_first "$left" "\\"$'\n'; cmd+="$before "; glued+=${before%\\}; left=$after
  [[ ${before: -1}${after:0:1} == [^[:space:]][^[:space:]] ]] && inword=1
  in_time || unread 'TimeLimit continuation lines'
done
cmd+=$left
[ -z "$inword" ] || cmd+=$'\n'$glued$left
cwd=$(printf '%s' "$in" | /usr/bin/jq -er '.cwd | strings | select(length > 0)' 2>/dev/null); rc=$?
case $rc in
  0) ;;
  4) guard_log 'ShapeDrift cwd' "$DRIFT_CAP" ;;   # a commit or merge asks below; the rest does not need the folder
  *) guard_log "JqExit $rc" ;;
esac
block(){ echo "BLOCKED by bash-guard: $1. Hand this command to the user or take a different approach; don't work around the block with a variant of the command." >&2; exit 2; }
shopt -s nocasematch
# one shell word (quoted strings may contain spaces/newlines); args never cross ; & | or an unquoted newline
W='("[^"]*"|'"'"'[^'"'"']*'"'"'|[^[:space:];&|"'"'"'])+'
A="([[:blank:]]+$W)*"
# git and its options before the subcommand: those with the value in the next word, then any other (--no-pager, -P, --git-dir=x)
G="git([[:blank:]]+((-[cC]|--(git-dir|work-tree|namespace|config-env|attr-source))[[:blank:]]+$W|-$W))*[[:blank:]]+"
E='([[:space:];&|)]|$)'
# Skipping git hooks. git takes a unique prefix of a long option (--no-veri; in am, which has no --verbose, --no-v).
# -n is --no-verify only in commit and am (push: dry run; merge, pull, rebase: no diffstat; cherry-pick, revert: no
# commit), also inside a group of short flags (-anm, am -bn): only flags without a value may stand before it, as in
# -mn the n is the message. E2 also ends at a quote, a backtick, < > or \ (bash -c "git commit -n", ssh host '...').
# core.hooksPath from -c (quoted or not), --config-env, GIT_CONFIG_KEY_<n> or GIT_CONFIG_PARAMETERS, git config;
# HUSKY=0 in any position. git is matched anywhere on the line, inside quotes too, and quotes pair one level deep,
# so text trips it as well: git commit or git am with a standalone -n later on the line (a message, echo, a #
# comment, <(git log -n 1)), a quoted form above, HUSKY=0 in echo, grep or ENV. The block shows what matched:
# reword, put the -n phrase before the git commit mention, or write such text with Write or Edit
E2='([[:space:];&|)<>\"'"'"'`]|$)'
r_nov="${G}(commit|push|merge|pull|rebase|cherry-pick|am|revert)$A[[:blank:]]+--no-v(e(r(i(fy?)?)?)?)?$E2|${G}(commit$A[[:blank:]]+-[aeiopqsvz]*|am$A[[:blank:]]+-[3bcikmqrsu]*)n($W)?$E2|-c[[:blank:]]+[\"']?core\.hookspath=|--config-env[=[:blank:]]+[\"']?core\.hookspath=|git_config_(key_[0-9]+|parameters)=[^[:space:];&|]*core\.hookspath|git[[:blank:]]+config([[:blank:]]+--(global|local|system|worktree))?[[:blank:]]+core\.hookspath[[:blank:]]+[./a-z~\$\"']|(^|[[:space:];&|(\"'])husky=[\"']?0([[:space:];&|)\"']|$)"
r_force="${G}push$A[[:blank:]]+(--force[^[:space:];&|]*|-[a-z]*f[a-z]*)$E"
r_refspec="${G}push$A[[:blank:]]+\+[a-z0-9_./:-]+"
r_commit="${G}commit$E"
# not past -C or --git-dir: the check of the branch reads the folder of the call
r_land='git([[:space:]]+(--[a-z-]+|-p))*[[:space:]]+(commit|merge)([[:space:]]|$)'
r_attr='co-authored-by:[[:space:]]*(claude|[^<]*<[^>]*@anthropic\.com>)|generated[[:space:]]+with[[:space:]]+\[?claude'
r_gh='(^|[^a-z0-9_./-])gh([[:blank:]]+-[^[:space:]]+([[:blank:]]+[^-[:space:]][^[:space:]]*)?)*[[:blank:]]+(pr|issue|release)[[:blank:]]+(create|edit|comment|review|merge|close)([[:space:]]|$)'
# commits only under the owner's git identity. Each regex ends with the identity value (last group):
# --author, -c user.*, GIT_AUTHOR_*/GIT_COMMITTER_*, git config user.* <value>
V="(\"[^\"]*\"|'[^']*'|[^[:space:];&|\"']+)"
r_id_author="${G}commit$A[[:blank:]]+--author[[:blank:]=]+$V"
r_id_c="(^|[[:space:]])-c[[:blank:]]+user\.(name|email)=$V"
r_id_cq="(^|[[:space:]])-c[[:blank:]]+[\"']user\.(name|email)=([^\"']*)[\"']"
r_id_env="(^|[[:space:];&|(\`\"'])git_(author|committer)_(name|email)=$V"
r_id_cfg="git[[:blank:]]+config([[:blank:]]+--(global|local|system|worktree|replace-all|add))*[[:blank:]]+user\.(name|email)[[:blank:]]+(\"[^\"]*\"|'[^']*'|[^-[:space:];&|<>0-9\"'][^[:space:];&|]*)"
own=""; own_loaded=""; id_other=""
owner_id(){ # 0 when the value is the owner's git user.name or user.email (global, or effective in this repo)
  if [ -z "$own_loaded" ]; then
    own=$(git config --global user.name; git config --global user.email
          if [ -n "$cwd" ] && cd "$cwd" 2>/dev/null; then git config user.name; git config user.email; fi)
    own_loaded=1
  fi
  local x f
  while IFS= read -r x; do
    [ -n "$x" ] || continue
    f=${x%% *}   # the owner's first name alone also counts (git -c user.name=<first name>)
    [[ $1 == "$x" || $1 == "$x <"* || $1 == *"<$x>"* ]] && return 0
    [ ${#f} -ge 3 ] && [[ $1 == "$f" ]] && return 0
  done <<< "$own"
  return 1
}
id_scan(){ # AI identity -> block; another identity -> remembered for an ask. $2: the text (default: the command)
  local s=${2-$cmd} n=0 v
  while [[ $s =~ $1 ]] && [ $n -lt 10 ] && in_time; do
    v=${BASH_REMATCH[${#BASH_REMATCH[@]}-1]}; split_first "$s" "${BASH_REMATCH[0]}"; s="$before $after"; n=$((n+1))
    v=${v#[\"\']}; v=${v%[\"\']}
    [[ $v =~ claude|anthropic ]] && block "an AI name in a commit or git config; commits only under the owner's name"
    owner_id "$v" || id_other=1
  done
  [[ $s =~ $1 ]] && id_other=1   # more than 10 identities in one command, or no time: not checked one by one, ask
  return 0
}
# rm -r on the home folder or a system folder, as it is or in a pair of quotes; a tilde in quotes is a folder of that name
T='(/|\$\{?home\}?|/etc|/usr|/var|/opt|/system|/library|/users|/var/www|/var/lib/docker|/users/[^/[:space:];&|]+)/?\*?'
F='(-{1,2}[a-z-]+[[:space:]]+)*'
r_rm="(^|[;&|[:space:]])rm[[:space:]]+$F(-[a-z]*r[a-z]*|--recursive)[[:space:]]+$F(~/?\*?|$T|\"$T\"/?\*?|'$T'/?\*?)([[:space:];&|]|\$)"
r_rmdata="(^|[;&|[:space:]])rm[[:blank:]]+(-[a-z]*[[:blank:]]+)*-[a-z]*r[a-z]*$A[[:blank:]]+[^;&|[:space:]]*(uploads?|pgdata|postgres-data|data/postgres|\.git|prisma/migrations|backups?|dumps?)/?\*?\"?$E"
r_docker="docker[[:blank:]]+((system|volume|image|builder)[[:blank:]]+prune|volume[[:blank:]]+rm)|compose$A[[:blank:]]+down$A[[:blank:]]+(-v|--volumes)$E"
r_prisma='prisma[[:space:]]+migrate[[:space:]]+reset|--accept-data-loss|--force-reset'
r_sql='(psql|mysql|sqlite3|prisma[[:space:]]+db[[:space:]]+execute)[^|]*(drop[[:space:]]+(table|database|schema)|truncate[[:space:]])|(^|[;&|[:space:]])dropdb[[:blank:]]'
r_del="(psql|mysql|sqlite3)[^|]*delete[[:space:]]+from[[:space:]]+(\\\\?\"[^\"\\\\]+\\\\?\"|[a-z0-9_.]+)[[:space:]]*(;|'|\"|\$)"
r_eph="(drop[[:space:]]+database|dropdb([[:blank:]]+-[^[:space:]]+)*)[[:space:]]+(if[[:space:]]+exists[[:space:]]+)?\\\\?\"?[a-z0-9_]*(test|tmp|temp|scratch|probe|shadow|rehearse|replay|dryrun|check|copy|restore|verif|audit|e2e|_ci|fresh|bootstrap|forecast|flip|lens|mig|demo|swap|bkup|upgrade|drill|zz_)[a-z0-9_]*\\\\?\"?"
# one line: a newline ends the words of curl, unless it is inside quotes; after the | a newline goes on; or a group or
# a loop with curl goes through the pipe as a whole ({ curl x; } | sh over several lines)
r_sh="[[:space:]]*(sudo[[:space:]]+)?(ba|z)?sh([[:space:]]|\$)"
r_pipe="(curl|wget)([^|"$'\n'"]|\"[^\"|]*\"|'[^'|]*')*\\|$r_sh|(curl|wget)[^|]*(\\}|\\)|done|fi)[[:space:]]*\\|$r_sh"
r_git_destroy="${G}(reset$A[[:blank:]]+--hard|clean$A[[:blank:]]+-[a-z]*f|checkout[[:blank:]]+(--[[:blank:]]+)?\.$E|restore$A[[:blank:]]+\.$E|stash[[:blank:]]+(drop|clear))"
r_envprint="(^|[;&|[:space:]])(cat|head|tail|less|more|bat)([[:blank:]]+-[^[:space:]]+)*[[:blank:]]+[^;&|[:space:]]*\.env(\.[a-z.]+)?$E"
r_envmask='\|[[:blank:]]*(cut|sed|awk|grep[[:blank:]]+-c|wc|od)([[:space:]]|$)'
r_killall='kill[[:blank:]]+-(9|kill|s[[:blank:]]+kill)[[:blank:]]+-1([[:space:];&|]|$)'
# docker compose config prints the merged config with env values (secrets) unless a listing flag is given
r_ccfg="(docker[[:blank:]]+compose|docker-compose)$A[[:blank:]]+(config|convert)$E"
r_ccfg_ok="(docker[[:blank:]]+compose|docker-compose)$A[[:blank:]]+(config|convert)$A[[:blank:]]+(-q|--quiet|--services|--volumes|--images|--profiles|--networks|--hash)$E"
r_dburl='(postgres(ql)?(\+[a-z0-9]+)?|mysql2?|mariadb|mssql|mongodb(\+srv)?|rediss?|amqps?|clickhouse|libsql|cockroachdb)://[^:/@[:space:]"'"'"']*:([^@[:space:]"'"'"']+)@([^/:@[:space:]"'"'"']+)'
r_resolve='prisma[[:space:]]+migrate[[:space:]]+resolve'
r_misc="(^|[;&|[:space:]])sudo([[:blank:]]+-[a-z]+([[:blank:]]+[^-[:space:];&|][^[:space:];&|]*)?)*[[:blank:]]+rm[[:blank:]]|chmod[[:blank:]]+(-[a-z]*r[a-z]*|--recursive)[[:blank:]]+0?777|(^|[;&|[:space:]])((npm|pnpm|yarn|bun)$A[[:blank:]]+publish|changeset[[:blank:]]+publish)([[:space:]]|$)"
ask_why(){   # why: the reason of the first ask rule that the text $1 trips, empty when none
  local t=$1 c n m after r_ex r_rest
  why=""
  [[ $t =~ $r_docker ]] && { why="деструктивна операція з docker volumes/images"; return; }
  [[ $t =~ $r_prisma ]] && { why="деструктивна prisma-операція"; return; }
  c=$t; n=0
  while [[ $c =~ $r_eph ]] && [ $n -lt 20 ] && in_time; do split_first "$c" "${BASH_REMATCH[0]}"; c="$before $after"; n=$((n+1)); done
  [[ $c =~ $r_sql ]] && { why="DROP/TRUNCATE/dropdb через клієнт БД"; return; }
  [[ $t =~ $r_del ]] && { why="DELETE без WHERE через клієнт БД"; return; }
  [[ $t =~ $r_pipe ]] && { why="виконання скрипта з інтернету (curl | sh)"; return; }
  [[ $t =~ $r_git_destroy ]] && { why="git-операція, що знищує незакомічені зміни (reset --hard / clean -f / checkout . / stash drop)"; return; }
  [[ $t =~ $r_rmdata ]] && { why="rm -r по даних проєкту (uploads/pgdata/.git/migrations/backups)"; return; }
  c=$t; n=0   # every config call needs its own listing flag
  while [[ $c =~ $r_ccfg_ok ]] && [ $n -lt 20 ] && in_time; do split_first "$c" "${BASH_REMATCH[0]}"; c="$before $after"; n=$((n+1)); done
  [[ $c =~ $r_ccfg ]] && { why="docker compose config друкує секрети з env; для перевірки -q, для списку --services, для повного виводу -o <файл> чи > файл"; return; }
  [[ $t =~ $r_resolve ]] && { why="prisma migrate resolve змінює історію міграцій; спершу migrate status і покажи розбіжність"; return; }
  [[ $t =~ $r_misc ]] && { why="sudo rm, chmod -R 777 чи publish пакета"; return; }
  if [[ $t =~ $r_envprint ]]; then
    m=${BASH_REMATCH[0]}
    split_first "$t" "$m"
    r_ex="\\.(example|sample|template|dist)$E"; r_rest="^[^;&"$'\n'"]*$r_envmask"
    [[ $m == *$'\n' ]] && after=""   # a mask counts on its line: the lines after it may be the text of a script
    if ! [[ $m =~ $r_ex ]] && ! [[ $after =~ $r_rest ]]; then
      why="друк вмісту .env (імена ключів бери з .env.example; довжину перевіряй: set -a; . ./.env; set +a; echo len=\${#VAR})"
    fi
  fi
}
# The script of a shell -c: a quote stands where the rules want a blank or the end of a command. So for the rules each script
# is one more line of the text; it may hold another shell -c. It is read up to its first closing quote
r_shc="(^|[^a-z0-9_.-])(ba|z|da|k)?sh([[:blank:]]+(-[a-z]*o[[:blank:]]+[a-z_]+|-{1,2}[a-z-]+))*[[:blank:]]+-[a-z]*c[a-z]*[[:blank:]]+(--[[:blank:]]+)?(\\\$?'([^']|'\\\\'')*'|\"([^\"\\\\]|\\\\.)*\")"
scripts(){   # scripts <text>: in $inner the scripts of its shell -c, each after a newline
  local s=$1 q e
  inner=""
  while [[ $s =~ $r_shc ]] && in_time; do
    q=${BASH_REMATCH[6]}; split_first "$s" "${BASH_REMATCH[0]}"
    q=${q#\$}
    if [ "${q:0:1}" = '"' ]; then e='s/\\(["$`\\])/\1/g'; else e="s/'\\\\''/'/g"; fi
    q=${q:1:${#q}-2}
    [[ $q != *\\* ]] || q=$(printf '%s' "$q" | /usr/bin/sed -E "$e")
    inner+=$'\n'$q; s=$after$'\n'$q
  done
  [[ $s =~ $r_shc ]] && unread 'TimeLimit shell scripts'
}
scripts "$cmd"; cmd+=$inner
# 1. Hard blocks
if [[ $cmd =~ $r_nov ]]; then
  # The match, so that text which only mentions a form can be reworded (the end holds the -n of a long match). Cut first:
  # on a whole long match this substitution takes longer than the hook has
  hit=${BASH_REMATCH[0]}
  [ ${#hit} -le 100 ] || hit="...${hit: -100}"
  block "bypassing git hooks (--no-verify or -n / core.hooksPath / HUSKY=0), matched: ${hit//[[:space:]]/ }"
fi
[[ $cmd =~ $r_force || $cmd =~ $r_refspec ]] && block "force push"
[[ $cmd =~ $r_commit && $cmd =~ $r_attr ]] && block "AI attribution in a commit"
[[ $cmd =~ $r_gh && $cmd =~ $r_attr ]] && block "AI attribution in a PR, issue or release"
for r in "$r_id_author" "$r_id_c" "$r_id_cq" "$r_id_env" "$r_id_cfg"; do id_scan "$r"; done
# Another identity only in a one-off repo under /tmp or in a heredoc that only goes to a file: no ask.
# bash-guard-dirs.py prints the parts with identity text that run anywhere else (any doubt: the whole command), then
# "end"; only they are checked again. python missing, killed or broken: one line in the error log, the ask of before
# Past RESCAN_SECS, or for a text over RESCAN_MAX bytes, the command asks as before rather than run past the hook
# timeout, where nothing asks (BASH_GUARD_RESCAN_SECS: tests only). The same holds for the ask rules in section 3
RESCAN_MAX=8000
helper(){   # helper <script>: 0 when it printed a text that ends with a line "end", in $rest; else one line in the log
  local py=/opt/homebrew/bin/python3 rc
  [ -x "$py" ] || py=/usr/bin/python3
  rest=$(printf '%s' "$in" | "$py" -I "$(dirname "$0")/$1" 2>/dev/null); rc=$?
  if [[ $rc != 0 && $rest =~ ^error\ (ShapeDrift(\ [a-z_.]+)+)$ ]]; then
    guard_log "${BASH_REMATCH[1]}" "$DRIFT_CAP"   # an input field that is not a string: doctor's input of an unknown
    # shape
  elif [ "$rc" != 0 ]; then
    [[ $rest =~ ^error\ ([A-Za-z_]+)$ ]] && rc="$rc ${BASH_REMATCH[1]}"
    guard_log "ShimExit $rc $1"
  elif [[ $rest != end && $rest != *$'\n'end ]]; then guard_log "ShimOutput $1"
  else return 0
  fi
  return 1
}
rescan(){   # the text in $rest is worth a second pass: it fits the limits above and differs from the text of the first pass.
  # Then $rest is that text with its scripts, as the first pass reads the command
  [ ${#rest} -le $RESCAN_MAX ] && in_time && [ "${rest%end}" != "$cmd"$'\n' ] || return 1
  scripts "${rest%end}"; rest=${rest%end}$inner
}
if [ -n "$id_other" ] && in_time && helper bash-guard-dirs.py && rescan; then   # a helper may take its 4 s, two of them add up
  id_other=""
  for r in "$r_id_author" "$r_id_c" "$r_id_cq" "$r_id_env" "$r_id_cfg"; do id_scan "$r" "$rest"; done
fi
[[ $cmd =~ $r_rm ]] && block "rm -r on a system or home directory"
[[ $cmd =~ $r_killall ]] && block "kill -9 -1 (all user processes)"
# 2. Secrets in staged changes: LEAKS_CODE is a secret, code 0 is no finding (no proof of a scan: outside a repo gitleaks ends
# with 0 too). With no gitleaks, no time or any other code nothing is known: a line in the log, and an ask that comes after
# the blocks of the steps below
no_verdict(){   # no_verdict <line>: a line for every commit while gitleaks is gone, so it stops at DRIFT_CAP
  guard_log "$1" "$DRIFT_CAP"
  unchecked="секрети в staged не перевірено ($1; лог ~/.claude/logs/bash-guard.err). "
}
leaks(){   # leaks <gitleaks> <seconds>: its exit code in $rc; past the seconds it is killed. Its own --timeout is no limit: long
  # plain text ignores it, and where it fires gitleaks ends with 0 and "no leaks found".
  # exec: $pid is gitleaks itself. KILL: it may ignore TERM. The timer kills it however it ends, also when its sleep cannot
  # fork, but for the TERM that stops it. A failed fork drops the locals: $pid stays global. A scan under 2 ms, no real one,
  # may leave the sleep till its time, with no output. Each has its own redirects: one on the call leaves a copy of stderr in
  # the timer, which holds the output of a hook that is killed
  # The rules are those of commit-leaks.sh, the same text gets the same verdict; a project's own config wins
  ( [ -n "$cwd" ] && cd "$cwd"; rules=(); [ -f .gitleaks.toml ] || rules=(--config "$(dirname "$0")/commit-leaks.toml")
    exec "$1" git --pre-commit --staged --redact --no-banner --exit-code "$LEAKS_CODE" "${rules[@]}" ) >/dev/null 2>&1 &
  pid=$!
  ( trap 'kill $!; trap - EXIT; exit' TERM; trap 'kill -9 "$pid"' EXIT; /bin/sleep "$2" & wait $! ) >/dev/null 2>&1 &
  timer=$!
  wait "$pid" 2>/dev/null; rc=$?
  { kill "$timer"; wait "$timer"; } 2>/dev/null
}
if [[ $cmd =~ $r_commit ]]; then
  gl=$(command -v gitleaks)   # a session may start with the bare PATH of the app; a relative one would be the repo's own
  [[ $gl == /* && -x $gl ]] || gl=/opt/homebrew/bin/gitleaks
  if [ -x "$gl" ]; then
    leaks "$gl" $((LEAKS_SECS - SECONDS))   # with no time left the timer ends at once
    case $rc in
      0) ;;
      "$LEAKS_CODE") block "gitleaks found a secret in the staged changes (check: gitleaks git --pre-commit --staged --redact)" ;;
      *) if [ "$SECONDS" -ge "$LEAKS_SECS" ]; then no_verdict 'TimeLimit gitleaks'; else no_verdict "GitleaksExit $rc"; fi ;;
    esac
  else no_verdict 'GitleaksExit 127'
  fi
fi
# with no cwd the checks of the repo below read the wrong folder or none (the line in the log is already there)
if [ -z "$cwd" ] && [[ $cmd =~ $r_commit || $cmd =~ $r_land ]]; then
  ask "commit чи merge без cwd у вході хука: ім'я git і гілку не перевірено (лог ~/.claude/logs/bash-guard.err)"
fi
# the identity git will really use (repo config, env), even without flags in the command
if [[ $cmd =~ $r_commit ]]; then
  ident=$( cd "$cwd" 2>/dev/null && { git var GIT_AUTHOR_IDENT; git var GIT_COMMITTER_IDENT; } 2>/dev/null )
  [[ $ident =~ claude|anthropic ]] && block "git signs the commit with an AI name (git var GIT_AUTHOR_IDENT); commits only under the owner's name"
fi
# 3. Ask the user
[ -n "$id_other" ] && ask "коміт чи git-налаштування з іменем, що не збігається з твоїм git user.name/user.email"
# A rule tripped: only the text that runs here counts (a script a heredoc writes, a command in a test container do not).
# bash-guard-exec.py prints that text, any doubt: the whole command; python missing, killed or broken: the ask of before
ask_why "$cmd"
if [ -n "$why" ] && in_time && helper bash-guard-exec.py && rescan; then ask_why "$rest"; fi
[ -n "$why" ] && ask "$why"
c4=$cmd   # every URL in the command: a literal password to a real remote host (domain or IP); text that does not
# run counts here too, it stays in the transcript all the same
while [[ $c4 =~ $r_dburl ]] && in_time; do
  k=${#BASH_REMATCH[@]}; pw=${BASH_REMATCH[k-2]}; host=${BASH_REMATCH[k-1]}
  split_first "$c4" "${BASH_REMATCH[0]}"; c4=$after   # a URL has no space: no match can start before this one
  # env variables, masks, placeholders and service names are fine
  if ! [[ $pw =~ ^(\$|\*|<) ]] && [[ $host =~ ^([a-z0-9-]+\.)+[a-z]{2,}$|^[0-9]{1,3}(\.[0-9]{1,3}){3}$ ]] \
     && ! [[ $host =~ ^(127\.|0\.0\.0\.0$|localhost$|host\.docker\.internal$) ]]; then
    ask "рядок підключення з паролем до віддаленого хоста $host (пароль потрапить у транскрипт; бери з env)"
  fi
done
[[ $c4 =~ $r_dburl ]] && ask "рядок підключення не перевірено: хуку забракло часу"
if [[ $cmd =~ $r_land ]]; then
  br=$( cd "$cwd"; git branch --show-current 2>/dev/null )
  if [[ $br == main || $br == master ]] && ( cd "$cwd"; { git show-ref --verify --quiet refs/heads/develop || git show-ref --verify --quiet refs/heads/dev; } ); then
    ask "commit/merge у $br, хоча є develop чи dev"
  fi
fi
[ -z "$unchecked" ] || ask "Перевірка вручну: gitleaks git --pre-commit --staged --redact"
exit 0
