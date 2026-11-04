# Sicherheitsrichtlinie / Security policy

## Deutsch

### Sicherheitslücke melden

Bitte melde Sicherheitslücken **nicht** als öffentliches Issue.

Nutze stattdessen die private Meldung von GitHub: im Repository unter **Security → Report a vulnerability**
(<https://github.com/19Andy89/hacs_semphoreui/security/advisories/new>).

Bitte nenne dabei:

- die betroffene Version der Integration (siehe `manifest.json` bzw. Release),
- eine kurze Beschreibung und die Schritte zum Nachstellen,
- die möglichen Auswirkungen.

Ich antworte in der Regel innerhalb von 7 Tagen. Das Projekt wird in der Freizeit gepflegt – eine feste Frist für eine Korrektur kann ich nicht zusagen.

### Unterstützte Versionen

Korrekturen gibt es nur für die jeweils **neueste Version**. Bitte aktualisiere zuerst darauf.

### Was zählt dazu – und was nicht

Interessant sind z. B. ausgelesene oder protokollierte Zugangsdaten (Token, Passwort), das Umgehen der Verschlüsselung in der Konfiguration
oder unerwünschte Aktionen auf dem Semaphore-Server.

Nicht Teil dieses Projekts sind Lücken in Semaphore UI selbst (bitte dort melden: <https://github.com/semaphoreui/semaphore>)
oder in Home Assistant.

Zur Einordnung: Token und Passwort werden in der Home-Assistant-Konfiguration verschlüsselt abgelegt. Der Schlüssel liegt im selben `.storage`-Ordner.
Das schützt vor einer versehentlich weitergegebenen Konfigurationsdatei, nicht vor Zugriff auf den gesamten Ordner oder ein vollständiges Backup
(Details im README, Abschnitt „Wie sicher liegen Token und Passwort?“).

## English

### Reporting a vulnerability

Please do **not** open a public issue for security problems.

Use GitHub's private reporting instead: in the repository under **Security → Report a vulnerability**
(<https://github.com/19Andy89/hacs_semphoreui/security/advisories/new>).

Please include:

- the affected version of the integration (see `manifest.json` or the release),
- a short description and steps to reproduce,
- the possible impact.

I usually answer within 7 days. This is a spare-time project, so I cannot promise a fixed deadline for a fix.

### Supported versions

Fixes are only provided for the **latest version**. Please update first.

### Scope

Of interest are, for example, leaked or logged credentials (token, password), bypassing the encryption of the stored configuration,
or unwanted actions on the Semaphore server.

Vulnerabilities in Semaphore UI itself (report them at <https://github.com/semaphoreui/semaphore>) or in Home Assistant are out of scope.

For context: token and password are stored encrypted in Home Assistant's configuration. The key lives in the same `.storage` folder.
This protects against an accidentally shared config file, not against access to the whole folder or a full backup
(see the README, section “How safe are token and password?”).
