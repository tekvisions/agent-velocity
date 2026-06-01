# Agent Velocity

**The open-source coding-agent race, live.** A leaderboard ranking open-source coding
agents by real GitHub shipping velocity — commit cadence + release recency + 4-week
trend — not by stars. Refreshed daily by an AI agent. A [Kymata Labs](https://kymatalabs-techtalevisions-projects.vercel.app/) product.

Pipeline mirrors StackTracker: `build_data.py` → `data.json` → `deploy.py`, daily via GitHub Action.
Velocity reflects public-repo commit activity (agents developed privately rank below their true pace).
