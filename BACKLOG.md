# Backlog

Was als Nächstes geplant ist und welche Ideen noch offen sind. Erledigtes steht im [CHANGELOG](CHANGELOG.md),
bekannte Einschränkungen im README (Abschnitt „Bekannte Grenzen“). Stand: nach Version 0.2.2.

## Später (0.2.x / 0.3)

* Zeitpläne **anlegen und ändern** (Cron-Text, Template), evtl. eine eigene **Zeitplan-Karte** (heute ein Abschnitt in Projekt- und
  Template-Karte).
* Build-/Deploy-Templates (mit Build-Version) sinnvoll startbar machen.

## 0.3

* **Token automatisch erneuern** (Login mit Benutzer/Passwort statt festem Token) bzw. die Token-Laufzeit anzeigen.

## Backlog ab 2.0.0

* **Testlauf sichtbar machen:** Die Template-Karten sollen anzeigen, wenn der **letzte Lauf ein Testlauf** (Dry Run) war, damit
  man ihn vom echten Lauf unterscheiden kann. Evtl. dafür ein eigener Sensor „Letzter Lauf war Testlauf“. Das Kennzeichen
  `dry_run` steckt schon im Bericht; die Handlungsbedarf-Box zeigt „(Testlauf)“ bereits.

## Ideen ohne Termin

* Live-Updates per WebSocket statt Abfrage.
* Mehrfachauswahl und Secret-Eingaben der Survey-Variablen als Dialog im Dashboard (heute nur über die Aktion).
* Parallelstart je Template: Das Feld `allow_parallel_tasks` der Semaphore-API ist eine Annahme aus der API-Beschreibung und
  noch nicht gegen eine echte Instanz geprüft.
