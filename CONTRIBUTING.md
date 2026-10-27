# Contributing

Thanks for helping. Architecture notes, the module map, coding conventions and recipes (add a step, an agent, a language) are in [DEVELOPER.md](DEVELOPER.md); read the "Conventions you must follow" section first.

## Ground rules

- **Tests with every behaviour change.** Add a pytest case; the suite must stay green.
- **User-facing text is English**; other languages go through the i18n catalogs (`python scripts/i18n_check.py` shows gaps).
- **No real secrets** in code, tests, docs or screenshots. Use obvious placeholders (`AKIAXXXXXXXXXXXXXXXX`, `changeme`).
- The server never calls a model and never needs an API key; please keep it that way.

## Run the checks before a pull request

```bash
python -m pytest -q
python scripts/i18n_check.py
cd dashboard && npm install && npm run build
```

## Pull requests

There is no gitflow: branch from `main`, open the pull request against `main`. Keep it focused, say what changed and why, and how you tested it.
