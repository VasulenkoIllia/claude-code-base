---
paths:
  - "**/{server,api,routes,services,webhooks,integrations,sync,workers,bot,jobs,cron,connectors,adapters,clients,controllers,handlers,queue,scheduler,parser,parsers,scrapers,core,pipeline,scripts,app,modules}/**/*.{ts,js,mjs,cjs}"
  - "lib/**/*.{ts,js,mjs,cjs}"
  - "**/{src,backend}/lib/**/*.{ts,js,mjs,cjs}"
  - "**/{apps,packages}/*/lib/**/*.{ts,js,mjs,cjs}"
  - "**/*{webhook,Webhook,worker,Worker,parser,Parser}*.{ts,js,mjs}"
  - "**/*.{controller,service,guard,interceptor,filter,middleware,gateway,processor,strategy}.{ts,js}"
  - "**/src/*.{ts,js,mjs}"
---
The project takes precedence. New and changed code only: don't rewrite or audit existing code, name a noticed violation in one line.
- The server checks route and row access with the repo's existing mechanism, denial as in the repo. Upload: size limit, type by content.
- Webhook: authenticate before processing, the vendor's way (HMAC of the raw body, token, secret in the path), constant-time; fast 2xx; a repeat of the same id doesn't duplicate actions.
- Each vendor lives in one module: extend the existing client, don't add a layer for a single call; pass on normalized data, not the raw payload.
- `fetch` doesn't throw on 4xx/5xx: check `response.ok`. No empty `catch` and no silent `return null`: log (vendor, id, status, no tokens) and propagate the error; swallow only deliberately, with a comment.
- Retry only network errors, 429, 5xx (backoff, `Retry-After`); a non-idempotent write without an idempotency key is not retried. A sync reads all pages.
- Tests exist: cover failures too (timeout, 4xx/5xx, broken payload, repeat); no tests: name the manual check. Non-Light: silent-failure-hunter.
