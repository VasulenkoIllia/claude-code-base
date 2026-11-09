#!/bin/bash
# UserPromptSubmit: block obvious tokens, warn on likely secrets.
# Bypass: a line that starts or ends with [secret-ok] (works when typed before OR after a pasted block)
p=$(/usr/bin/jq -r '.prompt // ""')
printf '%s' "$p" | /usr/bin/grep -Eq -- '^[[:space:]]*\[secret-ok\]|\[secret-ok\][[:space:]]*$' && exit 0
hard='(^|[^A-Za-z0-9])[0-9]{8,12}:AA[A-Za-z0-9_-]{30,}|(^|[^A-Za-z0-9_-])sk-(ant-|proj-|or-)?[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{20,}|xox[abp]-[A-Za-z0-9-]{10,}|(AKIA|ASIA)[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{35}|pat[A-Za-z0-9]{14}\.[a-f0-9]{64}|cf[a-z]t_[A-Za-z0-9]{20,}|eyJ[A-Za-z0-9_-]{15,}\.eyJ[A-Za-z0-9_-]{15,}\.|-----BEGIN [A-Z ]*PRIVATE KEY-----|[sr]k_live_[A-Za-z0-9]{20,}|whsec_[A-Za-z0-9]{20,}|GOCSPX-[A-Za-z0-9_-]{20,}|ya29\.[A-Za-z0-9_-]{30,}|npm_[A-Za-z0-9]{36}|dckr_pat_[A-Za-z0-9_-]{20,}|glpat-[A-Za-z0-9_-]{20}|sb_secret_[A-Za-z0-9_-]{20,}|sbp_[a-f0-9]{40}|ntn_[A-Za-z0-9]{40,}|hf_[A-Za-z0-9]{34}|gsk_[A-Za-z0-9]{40,}|[Bb]earer[[:space:]]+[A-Za-z0-9._~+/=-]{24,}'
app4='^[[:space:]]*[a-z]{4} [a-z]{4} [a-z]{4} [a-z]{4}[[:space:]]*$'
if printf '%s' "$p" | /usr/bin/grep -Eq -- "$hard" || { printf '%s' "$p" | /usr/bin/grep -Eq -- "$app4" && printf '%s' "$p" | /usr/bin/grep -Eiq -- 'пароль|Пароль|ПАРОЛЬ|пасворд|password|app|smtp|mail|пошт'; }; then
  echo "Схоже на токен або ключ. Поклади значення в .env (на сервері: read -rs) і напиши «додав». Якщо це не секрет, додай рядок [secret-ok] на початку або в кінці" >&2
  exit 2
fi
soft='(password|passwd|secret|token|api[_-]?key|access[_-]?key|app[_ -]?password)[a-z_]*"?[[:space:]]*[:=][[:space:]]*"?[A-Za-z0-9+/_@#%!.-]{12,}|(password|passwd|pwd|пароль|Пароль|ПАРОЛЬ|пасворд)"?[[:space:]]*[:=][[:space:]]*"?[A-Za-z0-9!@#%^&*_+=.,/?~-]{8,}|(_key|_salt|_private|_credentials?|_hash)"?[[:space:]]*[:=][[:space:]]*"?[A-Za-z0-9+/_=-]{32,}|://[^:/[:space:]@]+:[^@[:space:]/]+@[^/:[:space:]]+|(пароль|password)[^a-z0-9]{0,20}[a-z]{4} [a-z]{4} [a-z]{4} [a-z]{4}|sshpass[[:space:]]+-p[[:space:]]*[^[:space:]$]{4,}|api_?hash"?[[:space:]]*[:=][[:space:]]*"?[a-f0-9]{32}'
m=$(printf '%s' "$p" | /usr/bin/grep -Ei -m 50 -- "$soft" | /usr/bin/grep -Eio -- "$soft" | /usr/bin/grep -Eiv '@(localhost|127\.0\.0\.1|db|postgres|host\.docker\.internal)$|_(ttl|expires?|expiry|length|seconds|ms)|[:=][[:space:]]*"?(your|change_?me|example|placeholder|xxxx)' | /usr/bin/head -1)
if [ -n "$m" ]; then
  printf '%s\n' '{"hookSpecificOutput":{"hookEventName":"UserPromptSubmit","additionalContext":"The user message seems to contain a secret (password, key or connection string). Do not repeat the value or write it to files; advise rotation and moving it to .env."}}'
fi
exit 0
