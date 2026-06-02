#!/usr/bin/env python3
"""Standalone detail-page generator.

Reads the EXISTING data.json (no network fetch) and (re)writes:
  - a/<slug>/index.html for every repo
  - sitemap.xml (homepage + every detail page)
  - llms.txt

Reuses generate_details() from build_data.py so the hub's normal run and this
standalone runner produce identical output. Safe to run anytime; never hits the
GitHub API.

Usage:  python3 gen_details.py
"""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))


def main() -> int:
    import build_data  # imports cleanly; module-level code only sets up auth headers
    data_path = os.path.join(HERE, "data.json")
    if not os.path.exists(data_path):
        print(f"data.json not found at {data_path}", file=sys.stderr)
        return 1
    with open(data_path) as f:
        data = json.load(f)
    n = build_data.generate_details(data)
    print(f"OK: {n} detail pages written from existing data.json", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
