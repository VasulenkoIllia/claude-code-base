---
paths:
  - "**/*.{tsx,jsx,vue,svelte,html,css,scss}"
---
The project takes precedence. New and changed code only: don't rewrite or audit existing code, name a noticed violation in one line.
- Visual change: check in the browser at the sizes from the project's design doc, otherwise 390x844 and 1440x680, no horizontal scroll or clipping. Phone not checked → «телефон не перевірено» in the summary.
- Browser check of 5+ steps: an `Explore` subagent; brief: URL, sizes, criteria, login only to a local test account; back: verdict, numbers, what was not reached. Setup and fix-and-look debugging stay here.
- Height in `dvh`, not `vh`/`h-screen`; a modal `max-height: calc(100dvh - 2rem)` with its own scroll; `min-w-0` for an overflowing flex child; a table on phones: cards or scroll with a sticky column, unless the design says otherwise.
- Input fields from 16px (iOS zooms in), don't block zoom; tap targets on phones from 44px; actions not on hover only.
- Data screen: the relevant states (loading, empty, error, no permission, lots of data); form: error next to the field, submit disabled during the request.
- A client's change request: device, theme and DPR from the client's screenshots, not the sizes above; the criterion in the client's words, in numbers; a screen behind login: through a local test account.
- A claim about the look in a quiz or a letter only from a measurement, otherwise «не перевірено».
- A visible behavior change from a review: check on the client's device, a separate line in the letter.
- Reply to the client: «№. Зроблено чи ні. Причина одним реченням».
