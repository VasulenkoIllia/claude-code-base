---
paths:
  - "**/{.mcp.json,eas.json,credentials.json}"
---
The project takes precedence. New and changed code only: don't rewrite or audit existing code, name a noticed violation in one line.
- No secret value in these files or in git. `.mcp.json`: a `${NAME}` reference, its name in `.env.example`. `eas.json`: an EAS secret or a key path outside git. `credentials.json`: never committed. I set values and sign in (MCP OAuth, `eas login`).
- Signing keys, service-account files (`.p8`, `.p12`, `.jks`, `.keystore`): out of git and chat, never printed. One already in git: tell me, rotation is mine.
- A new MCP server or CLI with an account: name its host and if it can write or bill; connect only after my OK.
