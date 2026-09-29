# Liga MX Edge

## Today Edge (API-Football)

Build the current UEFA Nations League card in Mexico City time:

```powershell
.\.venv\Scripts\python.exe scripts\build_today_edge.py
```

The builder reads `API_FOOTBALL_KEY` from the process environment, `.env`, or
the existing local Downloads env file. It creates:

- `today-edge.html`: self-contained mobile/desktop dashboard.
- `data/today_edge_YYYY-MM-DD.json`: source snapshot and model output.
- `tracking/today_edge_picks.json`: opening/closing prices and autograding log.

Re-run before kickoff to update the closing line. Re-run after the fixtures are
final to grade pending picks. In-play fixtures are displayed but never selected.
