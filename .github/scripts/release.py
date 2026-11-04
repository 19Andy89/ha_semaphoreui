#!/usr/bin/env python3
"""Berechnet die nächste Version aus den Commit-Meldungen (Conventional Commits) und veröffentlicht sie.

Regeln (solange die Hauptversion 0 ist, also in der Beta):
  * ``feat!:`` / ``fix!:`` / ``BREAKING CHANGE`` im Text -> Minor-Sprung (0.3.x -> 0.4.0; ab 1.0 ein Major-Sprung)
  * ``feat:``                                            -> Minor-Sprung (0.3.x -> 0.4.0)
  * ``fix:`` / ``perf:``                                 -> Patch-Sprung (0.3.0 -> 0.3.1)
  * alles andere (docs, chore, test, refactor, ci, ...)  -> kein Release

Steht in ``manifest.json`` schon eine **höhere** Version als im letzten Tag, wird genau diese veröffentlicht (von Hand gesetzt).

Aufruf: ``release.py [--dry-run]``. Setzt die Ausgaben ``version`` und ``released`` für GitHub Actions.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "custom_components/semaphore_ui/manifest.json"
CARD = ROOT / "custom_components/semaphore_ui/frontend/semaphore-ui-card.js"
HEADER = re.compile(r"^(?P<type>[a-z]+)(\([^)]*\))?(?P<bang>!)?: (?P<text>.+)$")
TITLES = {"breaking": "Inkompatible Änderungen", "feat": "Neu", "fix": "Behoben", "perf": "Schneller"}


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True, text=True).stdout.strip()


def parse(version: str) -> tuple[int, int, int]:
    major, minor, patch = (int(x) for x in version.split("."))
    return major, minor, patch


def latest_tag() -> str | None:
    tags = [t for t in git("tag", "--list", "v[0-9]*").splitlines() if re.fullmatch(r"v\d+\.\d+\.\d+", t)]
    return max(tags, key=lambda t: parse(t[1:])) if tags else None


def commits_since(tag: str | None) -> list[tuple[str, str]]:
    """(Betreff, vollständiger Text) aller Commits seit dem Tag, ohne Release-Commits."""
    rng = f"{tag}..HEAD" if tag else "HEAD"
    out = git("log", rng, "--format=%H%x1f%B%x1e")
    result = []
    for block in out.split("\x1e"):
        if not block.strip():
            continue
        _sha, _, message = block.strip().partition("\x1f")
        subject = message.strip().splitlines()[0] if message.strip() else ""
        if subject.startswith("chore(release)"):
            continue
        result.append((subject, message))
    return result


def classify(commits: list[tuple[str, str]]) -> tuple[str | None, dict[str, list[str]]]:
    notes: dict[str, list[str]] = {}
    level = None
    rank = {None: 0, "patch": 1, "minor": 2, "major": 3}
    for subject, message in commits:
        match = HEADER.match(subject)
        breaking = bool(match and match["bang"]) or "BREAKING CHANGE" in message
        kind = match["type"] if match else ""
        text = match["text"] if match else subject
        if breaking:
            notes.setdefault("breaking", []).append(text)
            new = "major"
        elif kind == "feat":
            notes.setdefault("feat", []).append(text)
            new = "minor"
        elif kind in ("fix", "perf"):
            notes.setdefault(kind, []).append(text)
            new = "patch"
        else:
            continue
        if rank[new] > rank[level]:
            level = new
    return level, notes


def bump(version: str, level: str) -> str:
    major, minor, patch = parse(version)
    if level == "major" and major >= 1:
        return f"{major + 1}.0.0"
    if level in ("major", "minor"):  # in 0.x ist auch ein Bruch nur ein Minor-Sprung
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def write_version(version: str) -> None:
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    data["version"] = version
    MANIFEST.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    source = CARD.read_text(encoding="utf-8")
    source, count = re.subn(r'(SEMAPHORE_CARD_VERSION = ")[^"]*(")', rf"\g<1>{version}\g<2>", source)
    assert count == 1, "SEMAPHORE_CARD_VERSION nicht gefunden"
    CARD.write_text(source, encoding="utf-8")


def release_notes(notes: dict[str, list[str]]) -> str:
    lines = []
    for key in ("breaking", "feat", "fix", "perf"):
        if notes.get(key):
            lines += [f"### {TITLES[key]}", *(f"- {n}" for n in notes[key]), ""]
    lines.append("Installation: `semaphore_ui.zip` enthält nur `custom_components/semaphore_ui` (HACS lädt sie selbst).")
    return "\n".join(lines)


def changelog_section(version: str) -> str | None:
    """Abschnitt „## <version> …“ aus CHANGELOG.md (ohne die Überschrift)."""
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    match = re.search(rf"^## {re.escape(version)}\b[^\n]*\n(.*?)(?=^## |\Z)", text, re.S | re.M)
    return match.group(1).strip() if match else None


def output(**values: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            for key, value in values.items():
                handle.write(f"{key}={value}\n")
    for key, value in values.items():
        print(f"{key}={value}")


def main() -> int:
    dry = "--dry-run" in sys.argv
    tag = latest_tag()
    base = tag[1:] if tag else "0.0.0"
    current = json.loads(MANIFEST.read_text(encoding="utf-8"))["version"]
    commits = commits_since(tag)
    level, notes = classify(commits)

    if parse(current) > parse(base):  # Version von Hand angehoben: genau diese veröffentlichen
        version, reason = current, "manifest.json ist höher als der letzte Tag"
        if not notes:
            notes = {"feat": [s for s, _ in commits[:20]]}
    elif level:
        version, reason = bump(base, level), f"{level} laut Commit-Meldungen seit {tag}"
    else:
        print(f"Kein Release: seit {tag} gibt es keine feat/fix/perf-Commits ({len(commits)} Commits).")
        output(released="false", version=base)
        return 0

    print(f"Neue Version {version} ({reason})")
    body = release_notes(notes)
    if parse(current) > parse(base):
        body = (changelog_section(version) or body) + "\n\n" + body.splitlines()[-1]
    Path(ROOT / "release_notes.md").write_text(body, encoding="utf-8")
    if dry:
        print(body[:400])
        output(released="false", version=version)
        return 0
    if version != current:
        write_version(version)
        git("add", str(MANIFEST), str(CARD))
        git("-c", "user.name=github-actions[bot]", "-c", "user.email=41898282+github-actions[bot]@users.noreply.github.com",
            "commit", "-m", f"chore(release): v{version}")
    output(released="true", version=version)
    return 0


if __name__ == "__main__":
    sys.exit(main())
