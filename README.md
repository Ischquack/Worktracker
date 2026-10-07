# Worktracker

Data pipeline for **Jobbjakt**, the job-search tool.

## NAV job feed

`.github/workflows/nav-feed.yml` runs `scripts/nav_feed.py` every two hours (03:17–21:17 UTC) and on demand. It reads NAV's official job feed ([pam-stilling-feed](https://navikt.github.io/pam-stilling-feed/)), keeps active ads in the chosen municipalities from the last 8 days, and commits them to `data/nav-ads.json`. Jobbjakt's morning run reads that file.

Only active ads are written, so ads that NAV marks inactive disappear on the next refresh, as NAV's terms require.

### Settings

| Where | Name | Purpose |
|---|---|---|
| Actions secret | `NAV_FEED_TOKEN` | Personal token from NAV. Without it the script uses NAV's rotating public test token. Request one from nav.team.arbeidsplassen@nav.no. |
| Actions variable | `NAV_MUNICIPALITIES` | Comma-separated municipality names. Default `OSLO`. |

Run it manually from the **Actions** tab ("NAV job feed" → "Run workflow").

FINN ads are not part of NAV's feed; Jobbjakt reads FINN separately.
