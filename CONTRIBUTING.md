# Mitmachen / Contributing

## Deutsch

Fehler und Wünsche gerne als [Issue](https://github.com/19Andy89/hacs_semphoreui/issues) (Vorlagen vorhanden). Bitte keine Token, Passwörter oder interne Adressen posten.

Pull Requests sind willkommen. Kurz die Spielregeln:

- **Commit-Meldungen** nach [Conventional Commits](https://www.conventionalcommits.org/): `feat:` (neue Funktion → Minor-Version), `fix:`/`perf:` (Patch-Version); `docs:`, `chore:`, `test:`, `ci:`, `refactor:` lösen kein Release aus. Das Release (Tag, ZIP) baut der Workflow automatisch.
- **Tests**: `pip install -r requirements_test.txt` und `python -m pytest -q`. Neue Funktionen bitte mit Test.
- **Texte** in `translations/de.json` **und** `translations/en.json` pflegen; README und `README_en.md` gemeinsam anpassen.
- Ein Eintrag in `CHANGELOG.md` für sichtbare Änderungen.

## English

Bugs and ideas are welcome as [issues](https://github.com/19Andy89/hacs_semphoreui/issues) (templates provided). Please do not post tokens, passwords or internal addresses.

Pull requests are welcome. The ground rules:

- **Commit messages** follow [Conventional Commits](https://www.conventionalcommits.org/): `feat:` (new feature → minor version), `fix:`/`perf:` (patch version); `docs:`, `chore:`, `test:`, `ci:`, `refactor:` do not trigger a release. The workflow builds the release (tag, ZIP) automatically.
- **Tests**: `pip install -r requirements_test.txt` and `python -m pytest -q`. Please add a test for new features.
- Keep **texts** in both `translations/de.json` **and** `translations/en.json`; update README and `README_en.md` together.
- Add a `CHANGELOG.md` entry for user-visible changes.
