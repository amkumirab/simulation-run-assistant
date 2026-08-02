# Contributing

Thank you for considering a contribution. Small, focused changes are easiest to
review and maintain.

## Development setup

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python -m unittest discover -s tests -v
```

On Windows PowerShell, activate the environment with
`.venv\Scripts\Activate.ps1`.

## Pull requests

Before opening a pull request:

1. Create an issue describing the behavior change.
2. Keep solver-specific code behind the adapter interface.
3. Add or update tests for state transitions and failure cases.
4. Run `python -m unittest discover -s tests -v`.
5. Do not commit simulation licenses, credentials, proprietary models, or large
   generated artifacts.

For feature-sized work, prefer one branch and a short sequence of reviewable
commits over a single large commit.

By participating in this project, you agree to follow the
[Code of Conduct](CODE_OF_CONDUCT.md).
