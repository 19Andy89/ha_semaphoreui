# Changelog

## 0.3.0 (alpha) – Token-Pflege
- **Ablauf des API-Tokens wird angezeigt:** neuer Sensor „API-Token gültig bis“ (Diagnose, Projekt-Gerät) mit Attributen
  (`token_found`, `token_name`, `created`, `never_expires`, `auto_renew`, `renew_days_before`, `stored_login`, `last_renewed`, `renew_error`).
  Gelesen wird einmal pro Stunde über `GET /api/user/tokens` (Semaphore ab 2.18.2); ohne Ablaufdatum oder ohne Listenzugriff bleibt alles wie bisher.
- **Automatisch erneuern (Option, Standard an):** Bleiben weniger als 7 Tage (einstellbar, höchstens die halbe Laufzeit), legt die
  Integration **mit dem Token selbst** ein neues an (gleiche Laufzeit, Name „Home Assistant (semaphore_ui)“), prüft es und stellt um.
  Kein Passwort nötig. Das **alte Token bleibt bestehen** und läuft von selbst ab.
- **Reparaturen:** „API-Token läuft bald ab“ (nur bei ausgeschalteter Erneuerung; **Beheben** erneuert sofort) und „API-Token konnte nicht
  erneuert werden“ (mit Grund).
- **Notfall-Login (optional):** Mit gespeichertem Benutzer/Passwort (Optionen, Erneut authentifizieren oder Reparatur) ersetzt die
  Integration ein Token, das Semaphore schon ablehnt: anmelden, Token anlegen, abmelden. Höchstens alle 10 Minuten ein Versuch;
  Passwort liegt unverschlüsselt in der Konfiguration (in der Diagnose geschwärzt); kein zweiter Faktor (MFA).
- **Erneut authentifizieren** und die Reparatur „Token abgelehnt“ akzeptieren jetzt ein Token **oder** Benutzer und Passwort.
- Diagnose: Abschnitt `token` (ohne Token und Passwort). Neue Übersetzungen (de/en).
- Release: Ein Tag `vX.Y.Z` baut per GitHub Actions `semaphore_ui.zip` (nur `custom_components/semaphore_ui`) und legt ein Release an;
  `hacs.json` nutzt `zip_release`. Der Backlog liegt jetzt in den GitHub-Issues.
- Tests: 257 pytest-Tests (neu: `test_tokens.py`), Browser-Test mit 170 Prüfungen (neu: Sensor, Optionen, Reparatur „Beheben“ legt ein neues Token an).
  **Nicht an einer echten Instanz mit ablaufendem Token geprüft.**

## 0.2.3 (alpha) – Playbook konsolidiert
- **Beispiel-Playbook** liegt jetzt einheitlich unter `playbooks/update-linux.yml` (die bisherige Kopie `examples/update-linux.yml` wurde entfernt). Inhalt unverändert zur 0.2.2-Version (adaptive Speicherplatz-Prüfung, `disk_*`-Metriken im `HA_RESULT`).
- Doku und Tests auf den neuen Pfad umgestellt.

## 0.2.2 (alpha) – Pakete in einer Zeile
- **Template-Karte:** Die Paketnamen der Box „Offene Updates“ stehen jetzt in **einer** Zeile. Was nicht hineinpasst, fasst „+n weitere“
  zusammen (vorher brach die Liste um und zeigte „+1 weiteres“ als eigene Marke). Ein **Klick auf „+n weitere“** zeigt alle Pakete,
  „weniger“ klappt wieder zu (Knopf mit `aria-expanded`, per Tastatur bedienbar, der Fokus bleibt darauf). Die Zahl der sichtbaren
  Namen passt sich der Kartenbreite an (Fenstergröße, Handy) und die aufgeklappte Ansicht bleibt beim Neuzeichnen erhalten.
  Ein Klick darauf öffnet keine More-Info. Jeder Name hat seinen vollen Text als Tooltip. Passt alles in eine Zeile, gibt es keinen Knopf.
- Doku-Bilder: neu `template-card-updates-open.png` (aufgeklappt); die Beispieldaten haben jetzt 8 Pakete, damit „+5 weitere“ zu sehen ist.
- Tests: 218 pytest-Tests, Browser-Test mit 157 Prüfungen (neu: eine Zeile, „+n weitere“ stimmt mit den versteckten Paketen überein,
  auf-/zuklappen per Maus und Tastatur, Fokus, Fenster verkleinern/vergrößern, Handy, Englisch „+n more“/„less“).

## 0.2.1 (alpha) – Reparaturen, Template-Filter, Kringel
- **Reparaturen** unter *Einstellungen → System → Reparaturen*: „API-Token abgelehnt“ (sofort; **Beheben** fragt nach einem neuen Token,
  prüft es, speichert es und lädt neu), „Semaphore ist nicht erreichbar“ (erst wenn es 10 Minuten ohne Unterbrechung dauert, auch während
  Home Assistant das Setup wiederholt) und „Projekt nicht gefunden“ (HTTP 404/403, ebenfalls 10 Minuten). Sie verschwinden von selbst, sobald
  Semaphore wieder antwortet, und beim Entfernen des Eintrags.
- **Template-Filter** in den Optionen: „Templates in Home Assistant anzeigen“. Abgewählte Templates bekommen keine Geräte, Entitäten und
  Zeitplan-Schalter (vorhandene werden entfernt); gespeichert werden die abgewählten, neue Templates erscheinen weiter. Zähler des
  Projekts zählen nur die angehakten, Attribut `excluded` am Zähler „Anzahl Templates“, Diagnose nennt die Auswahl.
- **Kringel in den Karten:** Nach dem Klick auf Starten, Testlauf, Stopp oder einen Zeitplan-Schalter zeigt die Karte einen drehenden
  Ring (am Schalter schon mit dem Zielzustand), bis Semaphore geantwortet hat; ein zweiter Klick in der Zeit wird ignoriert.
- Ein abgelehntes Token beim Schalten eines Zeitplans oder Starten eines Templates zeigt jetzt die verständliche Meldung mit Hinweis auf
  den neuen Token-Dialog (statt „Token rejected (HTTP 401)“), startet „Erneut authentifizieren“ und meldet die Reparatur.
- Tests: 218 pytest-Tests (neu: `test_filter.py`, `test_repairs.py`), Browser-Test mit 139 Prüfungen (neu: Kringel an Schalter und Start;
  der Semaphore-Nachbau kann Schreibaufrufe verzögern). Das Ausschalten eines Zeitplans ist an einer echten Instanz (2.19.17) bestätigt.

## 0.2.0 (alpha) – Zeitpläne
- **Zeitpläne von Semaphore in Home Assistant**: je Zeitplan ein **Schalter** (`switch`, am Gerät des Templates), der nur das Kennzeichen
  `active` an Semaphore schickt (`PUT …/schedules/<id>/active`); Cron-Text und Template bleiben unberührt. Fehler (z. B. fehlende
  Berechtigung) erscheinen als verständliche Meldung, der Schalter bleibt dann, wie er war. Neue/gelöschte Zeitpläne in Semaphore
  legen Schalter an bzw. entfernen sie.
- **„Nächster Lauf“** (je Template) und **„Nächster geplanter Lauf“** (Projekt) als Zeitstempel-Sensoren. Die Integration wertet den
  Cron-Text wie Semaphore aus (`robfig/cron`: fünf Felder, `@daily` & Co., Monats-/Wochentagsnamen, `TZ=`-Präfix, Regel für Tag und
  Wochentag) und nutzt die Zeitzone aus Semaphore (`schedule_timezone` in `/api/info`, sonst UTC). Einmalige Zeitpläne zeigen ihren
  Zeitpunkt; ausgeschaltete und `@every …` haben keinen nächsten Lauf.
- **„Zuletzt erfolgreich“** je Template (Zeitstempel, Attribute `task_id`, `started`, `duration`, `dry_run`). Der Verlauf des Templates wird nur
  gelesen, wenn der letzte Lauf nicht erfolgreich war, und dann einmal je neuem letzten Lauf.
- **Karten**: Template-Karte mit „Nächster Lauf“, „Zuletzt erfolgreich“ und den Zeitplänen samt Schalter; Projekt-Karte mit allen
  Zeitplänen des Projekts (früheste zuerst, ausgeschaltete zuletzt). Option `show_schedules` (Standard: an) in beiden Karten und im Editor.
- **Bilder in der Doku**: README zeigt die Karten (`docs/screenshots/`, hell/dunkel, Smartphone). Der Browser-Test erzeugt sie;
  mit `UPDATE_SCREENSHOTS=1` werden sie ins Repo geschrieben.
- **Beispiel-Playbook** unverändert in `playbooks/update-linux.yml`.
- Der Browser-Test findet die Schaltfläche „Karte hinzufügen“ jetzt auch, wenn der erste Abschnitt höher als das Fenster ist.
- Tests: 198 pytest-Tests (neu: `test_schedule.py`, `test_schedules.py`), Browser-Test mit 129 Prüfungen (neu: Zeitpläne in beiden Karten,
  Schalter wirkt auf Semaphore, „Nächster Lauf“/„Zuletzt erfolgreich“ öffnen die More-Info, Bilder der Doku).

## 0.1.5 (alpha) – „Mehr sehen, mehr anklicken“
- **Laufende Templates mit Namen**: Der Sensor „Laufende Tasks“ hat neue Attribute (`templates`, `task_ids`, `details`), dazu gibt
  es den neuen Projekt-Sensor **„Template läuft“** (`binary_sensor`). Beides sieht auch Läufe, die in Semaphore selbst
  (Zeitplan, Weboberfläche) gestartet wurden.
- **`HA_RESULT` mit Hinweisen**: neuer Schlüssel `notes` (Text oder Liste, auch `note`) – z. B. „Debian 13 ist verfügbar“. Wird
  angezeigt (Karte, Attribut `notes`, Push-Text), zählt aber nicht als Handlungsbedarf. Höchstens 10 Hinweise zu je 200 Zeichen.
- **Template-Karte**: bei mehreren Hosts die Zahl je Host („dockerhost: 3, Neustart · pialert: 2“), Hinweise des Playbooks, und
  die Zeilen **Letzter Lauf** / **Dauer** sowie der **Fehlertext** öffnen per Klick (oder Enter/Leertaste) die Standard-Ansicht
  (More-Info) des jeweiligen Sensors.
- **Projekt-Karte**: Die **Kacheln filtern die Liste** (Läuft / Mit Fehler / Handlungsbedarf, nochmal antippen = alle; eigener
  Hinweis ohne Treffer). Neue Optionen **`show_version`** (Semaphore-Version, Standard an), **`show_integration_version`**
  (Version der Integration, Standard aus) und **`hacs_update_entity`** (Update-Entität aus HACS → Hinweis „Integration-Update“).
  Die beiden Hinweis-Chips im Kopf stehen untereinander, damit der Titel Platz behält.
- **Beispiel-Playbook** `playbooks/update-linux.yml` (getestet in den Formaten `yaml`/`json` und im Testlauf): Die Debian-Prüfung läuft
  **vor** `HA_RESULT`, damit „Debian 13 ist verfügbar“ als Hinweis (`notes`) mitgeschickt werden kann; neuer Testfall mit der
  echten Ausgabe. Der Code der Integration ist dabei unverändert.
- **Doku**: „`HA_RESULT` in drei Schritten“, Hinweise zu Zeitplänen in Semaphore (Cron `0 2 * * *` statt `* 2 * * *`, UTC,
  Testlauf per zweitem Template mit `--check`, Läufe aus Zeitplänen werden erkannt).
- Tests: 137 pytest-Tests (neu: Hinweise, `test_running_overview.py`), Browser-Test mit 105 Prüfungen (neu: Hosts, Hinweise,
  anklickbare Zeilen, Kachel-Filter inkl. Tastatur, Versionsanzeigen, Hinweis ohne Treffer).

## 0.1.4 (alpha) – Kein Doppelstart
- **Ein Template startet nicht zweimal**: Solange für ein Template ein Lauf **wartet oder läuft**, sind **Starten** und
  **Testlauf** gesperrt – in der Template-Karte (Knöpfe ausgegraut, Hinweis „Läuft bereits – erst abwarten oder stoppen“;
  **Stoppen** bleibt bedienbar), bei den Buttons und bei der Aktion `semaphore_ui.run_template`. Die Aktion bzw. der Button
  antwortet mit einer verständlichen Meldung (Template, Task-Nr., Hinweis auf die Option) statt einen zweiten Lauf anzulegen.
  Prüfung und Start sind je Template durch eine Sperre verbunden: Zwei fast gleichzeitige Klicks/Automationen erzeugen nur einen Lauf.
  Der Schutz sieht auch Läufe, die in Semaphore selbst (Zeitplan, Weboberfläche) gestartet wurden – nach dem nächsten Abruf.
- **Option „Mehrfachstart erlauben“** (Zahnrad am Eintrag, Standard: aus) hebt die Sperre auf. Außerdem gilt: Erlaubt das Template
  in Semaphore „Parallele Tasks“ (`allow_parallel_tasks`), ist der Start immer möglich.
- **„Läuft“-Sensor** hat neue Attribute: `task_ids` (alle wartenden/laufenden Tasks des Templates) und `parallel_allowed`
  (ob ein weiterer Start erlaubt wäre) – die Karte nutzt sie, du kannst sie in Automationen als Bedingung verwenden.
- Tests: 130 pytest-Tests (neu: `test_parallel_guard.py`, 8 Tests, u. a. gleichzeitige Starts, Option, Template-Flag, Testlauf,
  Läufe aus Semaphore); Browser-Test mit 73 Prüfungen (Sperre in der Karte, erzwungener Klick sendet nichts, Freigabe nach dem Stoppen).

## 0.1.3 (alpha) – „Nur anzeigen, was gerade gebraucht wird“
- **Handlungsbedarf per `HA_RESULT`**: Gibt ein Playbook am Ende `HA_RESULT {"updates": 3, "reboot_required": false}` aus,
  lesen die Entitäten das aus dem Log des letzten beendeten Laufs (Testlauf oder echter Lauf): Template-Sensoren
  **Handlungsbedarf** und **Offene Updates**, Projekt-Sensor **Templates mit Handlungsbedarf**; `ha_result` im Bericht
  (Ereignis, Aktion, Zusammenfassung), Zeile im Push-Text, Angaben in der Diagnose. Die Template-Entitäten entstehen erst bei der
  ersten Meldung und bleiben danach. Ansible-Baustein für apt-Hosts im README (getestet, auch mit `--check`).
- **Karten**: Template-Karte mit Box „Offene Updates: 3 · Neustart nötig“ (Prüfzeit, Testlauf, Paketnamen); Projekt-Karte mit
  Kachel „Handlungsbedarf“, Hinweis in der Liste, Sortierung (laufend, Fehler, Handlungsbedarf) und Option `only_needed`
  (nur Templates mit Handlungsbedarf, Fehler oder laufendem Task).
- **Fehlergrund auch im `yaml`-Ausgabeformat von Ansible** (`fatal: … FAILED! =>` mit dem Ergebnis als YAML-Block darunter):
  bisher stand dort nur „failed“. Fand sich beim Aufnehmen echter Logs.
- **Log wird erneut gelesen**, wenn Semaphore beim ersten Mal nicht antwortet (bis zu 5 Versuche) – Fehlergrund und
  `HA_RESULT` fehlen dadurch nicht dauerhaft.
- Tests: 122 pytest-Tests (neu: `test_ha_result.py` mit echten Ansible-Logs, `test_action_needed.py`); Browser-Test mit
  Ansicht „nur Benötigtes“ (65 Prüfungen).

## 0.1.2 (alpha) – Rückmeldungen aus dem ersten Praxistest
- **Fehler bei der Einrichtung stehen im Dialog** (DNS, Port abgelehnt, Zeitüberschreitung, SSL, Rechner nicht erreichbar,
  ungültige Adresse, „kein Semaphore unter dieser Adresse“ mit HTTP-Status, Token abgelehnt, Projekt nicht gefunden) –
  auch bei „Neu konfigurieren“ und „Erneut authentifizieren“. Kein Gang ins Log mehr nötig.
- **Versionsvergleich**: Build-Zusatz wie `2.19.17-f8cefe6-1792391878` wird ignoriert (kein falsches „Update verfügbar“);
  Rohfassung als Attribut `installed_version_reported` und in der Diagnose.
- **Problem-Sensoren erklären sich**: „Template mit Fehler“ (Projekt), „Templates mit Fehler“ und „Letzter Lauf
  fehlgeschlagen“ (Template) haben Attribute: welches Template, Task-Nr., Zeit, Grund, fehlgeschlagener Schritt, Host,
  Link zum Task (`explanation`, `failed_runs`, `reason`, `failed_task`, `host`, …).
- **Karten leichter zu finden und zu wählen**: Auswahl im Editor als Liste „Projekt › Template“ (nur passende Geräte),
  Hilfetexte, erstes Gerät vorbelegt, Vorschau im Karten-Dialog, Projektname unter dem Titel bei mehreren Projekten.
  Die Karten-Datei wird zusätzlich als **Dashboard-Ressource** eingetragen (YAML-Modus bleibt unberührt); die Diagnose
  zeigt, wie die Registrierung lief. README: Weg über „Nach Karte“ (der Dialog öffnet im Tab „Nach Entität“).
- **Eigenes Symbol** (CC0) für die Integration unter `brand/`.
- Tests: 85 pytest-Tests; Browser-Test mit zwei Projekten, Karten-Auswahl, Ressource und Fehlerdialog (56 Prüfungen).

## 0.1.1 (alpha)
- **Dashboard-Karten** werden mitgeliefert und automatisch geladen (keine Ressource eintragen):
  - `custom:semaphore-ui-template-card` – ein Template: Status, letzter Lauf, Dauer (live), Fehlergrund mit Task und Host,
    Parameter, Eingabefelder der Survey-Variablen, Starten / Testlauf / Stoppen, optional mit Rückfrage.
  - `custom:semaphore-ui-project-card` – Projekt-Übersicht: Erreichbarkeit, Update-Hinweis, Zähler, zuletzt gelaufener Task,
    Template-Liste mit Schnellstart/Stopp (Sortierung: Status, Name oder letzter Lauf).
  - Visueller Karten-Editor, hell/dunkel, schmale Bildschirme, Sections-Layout, Deutsch/Englisch, Tastaturbedienung.
- **Neu konfigurieren** (URL, Token, SSL-Prüfung ändern, ohne den Eintrag zu löschen).
- **Diagnose** zum Herunterladen (Token und Adresse geschwärzt, keine Task-Ausgaben).
- **Logbuch**: Start und Ende von Tasks mit dem fertigen Kurztext.
- Geräte von in Semaphore gelöschten Templates lassen sich in Home Assistant entfernen.
- Neu: `tests/test_extras.py` und der optionale Browser-Test `tests/browser/` (echtes Home Assistant + Chromium).

## 0.1.0 (alpha)
- Config-Flow: URL + API-Token, danach Projekt aus der API wählen; Re-Auth-Dialog bei abgelehntem Token.
- Projekt-Gerät: Verfügbarkeit, Semaphore-Update-Status, Anzahl Templates, laufende Tasks,
  zuletzt gelaufenes Template (+ Status, Startzeit), Templates mit Fehler, Event-Entität „Tasks“.
- Pro Template ein Gerät: Status, zuletzt gestartet/beendet, Dauer, Zusammenfassung (JSON-Bericht),
  Läuft/Fehler, Buttons Starten/Testlauf/Stoppen.
- Survey-Variablen: Eingabe-Entitäten (Text/Zahl/Auswahl) je Variable, vom Starten-Button verwendet; Aktion mit
  Feld `survey` (auch Select und Secret); Defaults und Pflichtfelder werden vor dem Start geprüft.
- Aktion `semaphore_ui.run_template` (optional mit Warten und Antwort = Bericht).
- Bus-Ereignisse `semaphore_ui_task_started` / `semaphore_ui_task_finished` mit fertigem Bericht
  (Start, Dauer, Ergebnis, Fehlergrund, `title`/`text` für Push).

## Geplant
Siehe [BACKLOG.md](BACKLOG.md).
