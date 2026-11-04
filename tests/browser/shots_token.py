"""Nur die zwei Token-Bilder der Doku neu erzeugen (token-options, token-repair).

  UPDATE_SCREENSHOTS=1 CHECK_SCRIPT=tests/browser/shots_token.py bash tests/browser/run_e2e.sh
"""

from __future__ import annotations

import sys

from playwright.sync_api import sync_playwright

import check_cards as cc


def main() -> int:
    with sync_playwright() as playwright:
        cc.test_token_care(playwright)
    return 0 if all(cc.results) else 1


if __name__ == "__main__":
    sys.exit(main())
