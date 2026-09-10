# India Equity Research Terminal

A disciplined research process for NSE listed companies, implemented as software.

The terminal has two halves. The **workbench** runs on your own machine, pulls free market
data, computes everything computable, and proposes scores you can overrule. The **site** is
a static, read-only set of published reports that GitHub Pages serves for free.

Published pages are an educational demonstration of the scoring framework. They are not
investment advice.

## Running it

```
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
.venv/Scripts/python.exe -m app.main
```

The workbench opens at `http://127.0.0.1:8848`. It binds to the loopback address only, so it
is not reachable from your network and needs no login.

## How a report is made

1. Enter an NSE symbol. Five years of annual statements, recent quarters and five years of
   daily prices are fetched from free sources.
2. The terminal computes the core table, growth rates, forensic red flags, relative
   valuation, a discounted cash flow with a sensitivity grid, and a technical score.
3. It proposes a score out of ten for each of the seven categories and shows the figures
   behind each proposal. Moat and catalysts are left to you, because financial statements
   cannot honestly supply them.
4. You set the final scores, fill in the thesis, and answer the ten audit questions.
5. Press publish. The report becomes a page under `site/`. Commit and push to put it online.

## The scoring engine

Seven categories, weights fixed by framework 14:

| Category | Weight |
|---|---|
| Quality | 20 |
| Growth | 20 |
| Earnings | 15 |
| Valuation | 20 |
| Competitive moat | 10 |
| Catalysts | 5 |
| Risk | 10 |

Risk is scored in reverse, where ten is low risk. Technical analysis is deliberately kept
outside the hundred points and reported separately.

The total does not decide on its own. Three valuation overrides, a thesis-break rule, a
margin-of-safety gate and a portfolio-concentration rule can all overrule it, and a report
cannot be published until all ten audit questions are answered. Those rules live in
`app/core/scoring.py`, which is pure logic and covered by tests.

```
.venv/Scripts/python.exe -m pytest tests -q
```

## Data

Yahoo Finance through `yfinance` supplies fundamentals and prices at no cost and without an
account. Coverage is honest but imperfect: five years of annual statements are reliable,
quarterly data is partial, and quarterly cash flow is not published at all. The terminal
reports every gap rather than filling it with a guess.

If your machine runs antivirus software that intercepts HTTPS, `app/net.py` finds its
certificate and trusts it. It never disables verification.

## What stays private

The repository is public because free GitHub Pages requires it. These never enter version
control, and `.gitignore` enforces it:

- `terminal.db`, the local database of drafts and working notes
- `frameworks/`, the source methodology documents
- anything unpublished

Only reports you explicitly publish are written to `site/`.

## Publishing to GitHub Pages

1. Create a public repository under the `datahegemon-dotcom` account.
2. Push this project to it.
3. In the repository settings, under Pages, set the source to GitHub Actions.

The workflow in `.github/workflows/pages.yml` deploys the `site/` directory on every push to
`main`.

---

Framework designed by Nagaraj Balasubramaniam. Equity investments are subject to market
risk. This project is for educational and analytical purposes only and does not provide
buy, sell or hold recommendations.
