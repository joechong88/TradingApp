# TradingApp

Minimal, modular Python scaffold for experimenting with trading strategies.

Quickstart (PowerShell):

```powershell
python -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m src.trading_app.cli.main
```

GitHub → Streamlit notes:
- Publish this repository to GitHub.
- Link the GitHub repository in Streamlit Community Cloud to auto-deploy `streamlit_app.py`.
- For CI, a GitHub Actions workflow runs tests on push; Streamlit picks up changes automatically when linked.

Project layout:

- `src/trading_app/` — package code
  - `data/` — data providers
  - `models/` — pydantic models
  - `strategies/` — strategy implementations
  - `execution/` — order executor
  - `cli/` — simple runner
  - `config/` — yaml configs
- `tests/` — pytest tests

Next steps:
- Optionally install VS Code extensions: Python, Pylance, Black, Ruff.
- Push to GitHub and connect Streamlit for deployment.
