# Protected Browser Session Data

Browser identity/session data is a hard protection boundary.

## Always blocked by default

- Browser profile cookies, local storage, session storage, login databases, and sessionstore backups.
- OpenAI/ChatGPT session records when they appear in browser or app-support data.
- Keychain material and `.ssh` identity material.
- App support files that clearly contain token/session state.

## Required behavior

- Read-only inspection is allowed when needed to classify risk.
- Cleanup plans must mark these targets as `protected_session` and `protection=blocked`.
- Generic cache cleanup, browser cleanup, profile reset, or app-leftover cleanup must not remove these paths.
- Do not offer a normal confirmation bypass for protected browser/session/key data.
- Shared reports must not include raw cookie, token, session, login DB, keychain, or private profile paths.
