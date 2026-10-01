# Contributing

Thanks for helping to improve this integration! It is a small hobby project, so please keep contributions focused
and easy to review.

## Before you start

- **Bugs and device reports:** open an [issue](https://github.com/prodigy7/ha_amperfied_wallbox_mqtt/issues). Please
  include your wallbox model, firmware version, Home Assistant version, and relevant debug logs or diagnostics
  (diagnostics redact passwords and tokens).
- **Pull requests:** for anything beyond a typo, open an issue first so we can agree on the approach.
- **Design policy:** this integration is deliberately read-primary (see [CLAUDE.md](CLAUDE.md)). Write actions such as
  setting the power limit, phase switching or RFID management are out of scope unless explicitly agreed in an issue.

## Pull requests

- One topic per PR, small diff, follow the existing code style. No unrelated refactoring or reformatting.
- Add or update tests in `tests/`. New test dependencies go into `requirements_test.txt` in the same PR.
- Run the test suite in a clean environment as described in [DEVELOPMENT.md](DEVELOPMENT.md); CI (pytest, hassfest,
  HACS) must pass.
- Changes to [PROTOCOL.md](PROTOCOL.md) must be verified against a real wallbox. Say what you tested and on which
  device; an admitted gap is better than a plausible guess.

## AI-assisted contributions

This project was itself built with AI assistance, and AI tools are welcome. We follow the spirit of the
[Open Home Foundation AI policy](https://developers.home-assistant.io/docs/ai_policy/):

- You are responsible for what you submit. Review and understand every change, and be able to explain it.
- Mention in the PR that you used AI and for what (one sentence is enough).
- Write PR descriptions and answers to review questions in your own words. Using AI for grammar or translation is fine.
- No autonomous agents: a human opens issues and PRs and reads the replies.
- Do not submit AI-generated claims about the wallbox protocol or security issues without reproducing them yourself.

Contributions that clearly ignore these points may be closed without review.
