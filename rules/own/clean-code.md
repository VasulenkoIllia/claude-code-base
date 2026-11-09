---
paths:
  - "**/*.{ts,tsx,js,jsx,mjs,cjs,py,vue,svelte}"
---
The project takes precedence. New and changed code only: don't rewrite or audit existing code, name a noticed violation in one line.
- Before a new helper or component, search for an existing one (Grep, LSP) and use it. Don't copy a block over ~8 lines or a business rule (calculation, access, validation); moving existing code only with my OK.
- New code: function or hook ≤100 lines, component ≤200 and <10 `useState`, nesting ≤3, file ≤400. Don't bloat a long existing function: new logic goes to a helper; don't add a new responsibility to a file over 400 lines, don't let any file grow past 800.
- Move a calculation or mapping over ~10 lines out of a function with I/O into a pure one.
- Before optimizing: a baseline measured under acceptance conditions.
- Interface, factory, generic, layer only with ≥2 implementations or consumers, as in neighboring modules, or for a «Люки» item of the «## Розмір» card; nothing from its «Не додаємо».
- Names: the domain term as in the repo, boolean `is/has`, unit (`timeoutMs`), no `tmp`/`obj`/`data2` outside tests. Thresholds and limits in a named constant or config.
- Remove what the change left unused (a file: only name it); no commented-out code and no just-in-case exports. A comment explains why, not what.
- In «Перевірено»: the review (agents, findings) or «рев'ю не робилось».
