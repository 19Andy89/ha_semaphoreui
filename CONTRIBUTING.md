# Mitmachen / Contributing

## Deutsch

Fehler und Wünsche gerne als [Issue](https://github.com/19Andy89/ha_semaphoreui/issues) (Vorlagen vorhanden). Bitte keine Token, Passwörter oder interne Adressen posten.

Pull Requests sind willkommen. Kurz die Spielregeln:

- **Commit-Meldungen** nach [Conventional Commits](https://www.conventionalcommits.org/): `feat:` (neue Funktion → Minor-Version), `fix:`/`perf:` (Patch-Version); `docs:`, `chore:`, `test:`, `ci:`, `refactor:` lösen kein Release aus. Das Release (Tag, ZIP) baut der Workflow automatisch.
- **Tests**: `pip install -r requirements_test.txt` und `python -m pytest -q`. Neue Funktionen bitte mit Test.
- **Texte** in `translations/de.json` **und** `translations/en.json` pflegen; README und `README_en.md` gemeinsam anpassen.
- Ein Eintrag in `CHANGELOG.md` für sichtbare Änderungen.

### Branches und Dev-Releases

- **`main`** ist der geprüfte Stand. Jeder `feat:`/`fix:`-Commit dort erzeugt automatisch eine stabile Version (Tag, ZIP, Release).
- **`dev`** ist der Entwicklungsstand. Jeder Push auf `dev` baut eine **Vorabversion** (`0.19.0-dev.1`, `0.19.0-dev.2`, …) mit ZIP – ohne Release-Commit, das Repository bleibt unverändert.
- Neue Änderungen bitte als Pull Request **gegen `dev`** (oder direkt auf `dev`). Wenn eine Dev-Version auf einer echten Instanz getestet ist, kommt sie per Pull Request `dev` → `main`; daraus entsteht die stabile Version.
- **Dev-Version in Home Assistant testen:** In HACS die Integration öffnen → ⋮ → „Beta-Versionen anzeigen“ einschalten → „Erneut herunterladen“ → die gewünschte `-dev`-Version wählen → Home Assistant neu starten.
- Tests (pytest) und hassfest laufen bei jedem Push auf `dev` und bei jedem Pull Request.

## English


Bugs and ideas are welcome as [issues](https://github.com/19Andy89/ha_semaphoreui/issues) (templates provided). Please do not post tokens, passwords or internal addresses.

Pull requests are welcome. The ground rules:

- **Commit messages** follow [Conventional Commits](https://www.conventionalcommits.org/): `feat:` (new feature → minor version), `fix:`/`perf:` (patch version); `docs:`, `chore:`, `test:`, `ci:`, `refactor:` do not trigger a release. The workflow builds the release (tag, ZIP) automatically.
- **Tests**: `pip install -r requirements_test.txt` and `python -m pytest -q`. Please add a test for new features.
- Keep **texts** in both `translations/de.json` **and** `translations/en.json`; update README and `README_en.md` together.
- Add a `CHANGELOG.md` entry for user-visible changes.

### Branches and dev releases

- **`main`** is the verified state. Every `feat:`/`fix:` commit there automatically creates a stable version (tag, ZIP, release).
- **`dev`** is the development state. Every push to `dev` builds a **pre-release** (`0.19.0-dev.1`, `0.19.0-dev.2`, …) with a ZIP – without a release commit, the repository stays unchanged.
- Please open pull requests **against `dev`** (or push to `dev`). Once a dev version is tested on a real instance it goes to `main` through a pull request `dev` → `main`; that creates the stable version.
- **Testing a dev version in Home Assistant:** open the integration in HACS → ⋮ → switch on “Show beta versions” → “Redownload” → pick the `-dev` version → restart Home Assistant.
- Tests (pytest) and hassfest run on every push to `dev` and on every pull request.
