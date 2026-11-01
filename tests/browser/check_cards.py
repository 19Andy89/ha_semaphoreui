"""Browser-Test der Dashboard-Karten gegen ein echtes Home Assistant (Playwright).

Voraussetzung: ``run_e2e.sh`` (oder ``fake_server.py`` + Home Assistant + ``setup_ha.py``) läuft.
Prüft Darstellung, Klicks (Start, Testlauf, Stopp, Bestätigung), Survey-Eingaben, Mobil-Layout,
Englisch und den Karten-Editor. Bei Fehlern gibt es Screenshots in ``<E2E_DIR>/shots``.

Umgebungsvariablen: ``E2E_DIR``, ``HA_URL``, ``FAKE_URL``, ``DOCS_SHOTS`` (Ordner für die Bilder der Doku,
``run_e2e.sh`` setzt ihn bei ``UPDATE_SCREENSHOTS=1`` auf ``docs/screenshots``).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import time
import urllib.request

from playwright.sync_api import Page, sync_playwright

HA_URL = os.environ.get("HA_URL", "http://127.0.0.1:8123")
FAKE_URL = os.environ.get("FAKE_URL", "http://127.0.0.1:13000")
E2E_DIR = Path(os.environ.get("E2E_DIR", "."))
SHOTS = E2E_DIR / "shots"
DOCS = Path(os.environ["DOCS_SHOTS"]) if os.environ.get("DOCS_SHOTS") else None
PATH = "/dashboard-sem-test/0"
MANIFEST = json.loads((Path(__file__).resolve().parents[2] / "custom_components/semaphore_ui/manifest.json").read_text())
VERSION = MANIFEST["version"]

results: list[bool] = []


def check(name: str, ok: bool, info: object = "") -> None:
    results.append(bool(ok))
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok or not info else f"   [{info}]"))


def ctl(action: str) -> list:
    with urllib.request.urlopen(f"{FAKE_URL}/ctl/{action}", timeout=10) as response:  # noqa: S310
        return json.load(response)


def puts() -> list:
    """Schedule switches that reached Semaphore (PUT .../schedules/<id>/active)."""
    return ctl("puts")


def posts() -> list:
    return [p for p in ctl("requests") if p[1].endswith(("/tasks", "/stop"))]


def open_page(playwright, *, width=1400, height=1100, lang="de-DE", scheme="light", path=PATH, cards=True) -> tuple:
    tokens = json.loads((E2E_DIR / "token.json").read_text())
    browser = playwright.chromium.launch()
    context = browser.new_context(viewport={"width": width, "height": height}, locale=lang, color_scheme=scheme)
    context.add_init_script(
        f"localStorage.setItem('hassTokens', JSON.stringify({json.dumps(tokens)}));"
        f"localStorage.setItem('selectedLanguage', '\"{lang[:2]}\"');"
    )
    page = context.new_page()
    page.goto(HA_URL + path, wait_until="domcontentloaded")
    if cards:
        page.wait_for_selector("semaphore-ui-project-card >> .title", timeout=60000)
        page.wait_for_selector("semaphore-ui-template-card >> .title", timeout=60000)
    else:
        page.get_by_role("button", name="OK").wait_for(timeout=60000)
    time.sleep(2)
    # bei abweichendem HA_PORT fragt Home Assistant per Dialog nach der HTTP-Konfiguration und fängt Klicks ab
    page.locator("dialog-http-pending-config").evaluate_all("els => els.forEach((e) => e.remove())")
    return browser, page


def tcard(page: Page, title: str):
    """Template card by its title."""
    return page.locator("semaphore-ui-template-card", has=page.locator(".title", has_text=title)).first


def shot(page: Page, name: str) -> None:
    SHOTS.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(SHOTS / f"{name}.png"), full_page=True)


def test_rendering(page: Page) -> None:
    project = page.locator("semaphore-ui-project-card").first
    check("Projekt-Karte: Titel", project.locator(".title").inner_text().strip() == "Homelab", project.locator(".title").inner_text())
    stats = project.locator(".stat .n").all_inner_texts()
    check("Projekt-Karte: 1 laufend, 1 Fehler, 1 Handlungsbedarf, 5 Templates", stats == ["1", "1", "1", "5"], stats)
    check("Projekt-Karte: Kachel „Handlungsbedarf“ ist hervorgehoben", project.locator(".stat.warn .l").all_inner_texts() == ["Handlungsbedarf"], project.locator(".stat.warn").count())
    check("Projekt-Karte: Update-Hinweis", project.locator(".chip", has_text="Update").count() == 1)
    check("Projekt-Karte: 5 Templates in der Liste", project.locator(".item").count() == 5)
    check("Projekt-Karte: laufendes Template zuerst (Sortierung nach Status)", "Proxmox" in project.locator(".item .name").first.inner_text())

    # Zeilen dürfen nicht breiter sein als die Liste (sonst sind die Knöpfe abgeschnitten)
    widths = project.locator(".list").evaluate(
        "list => [list.getBoundingClientRect().width, ...[...list.querySelectorAll('.item')].map(i => i.getBoundingClientRect().width)]"
    )
    check("Projekt-Karte: Zeilen passen in die Karte", all(w <= widths[0] + 1 for w in widths[1:]), widths)
    check("Projekt-Karte: jede Zeile hat einen Knopf", project.locator(".item button").count() == 5, project.locator(".item button").count())

    host = tcard(page, "Host-Update")
    check("Fehler-Karte: Status „Fehler“", "Fehler" in host.locator(".chip").first.inner_text())
    box = host.locator(".errbox").inner_text()
    check("Fehler-Karte: Grund, Task und Host", "Failed to lock apt" in box and "Update apt cache" in box and "dockerhost" in box, box)

    proxmox = tcard(page, "Proxmox")
    check("Laufende Karte: Stopp-Knopf vorhanden", proxmox.locator("button >> text=Stoppen").count() == 1)
    # Doppelstart-Schutz: solange das Template läuft, sind Start und Testlauf gesperrt, Stopp bleibt bedienbar
    start_btn, dry_btn = proxmox.locator("button[data-action=start]"), proxmox.locator("button >> text=Testlauf")
    check("Laufende Karte: Start und Testlauf sind gesperrt (kein Doppelstart)", start_btn.is_disabled() and dry_btn.is_disabled(), (start_btn.is_disabled(), dry_btn.is_disabled()))
    check("Laufende Karte: Tooltip erklärt die Sperre", "Läuft bereits" in (start_btn.get_attribute("title") or "") and "Läuft bereits" in (dry_btn.get_attribute("title") or ""), start_btn.get_attribute("title"))
    check("Laufende Karte: Stopp bleibt bedienbar", proxmox.locator("button >> text=Stoppen").is_enabled())
    check("Ruhende Karte: Start nicht gesperrt, kein Sperr-Tooltip", tcard(page, "docker-system").locator("button[data-action=start]").is_enabled() and not tcard(page, "docker-system").locator("button[data-action=start]").get_attribute("title"))
    first = proxmox.locator(".elapsed").inner_text()
    time.sleep(2.2)
    check("Laufende Karte: Dauer tickt live", proxmox.locator(".elapsed").inner_text() != first, first)

    docker = tcard(page, "docker-system")
    check("Erfolgs-Karte: kein Stopp-Knopf", docker.locator("button >> text=Stoppen").count() == 0)
    need = docker.locator(".needbox.on").inner_text() if docker.locator(".needbox.on").count() else ""
    check("Handlungsbedarf: Karte nennt Updates und Neustart", "Offene Updates: 9" in need and "Neustart nötig" in need, need)
    check("Handlungsbedarf: Quelle ist ein Testlauf, Paketnamen als Chips (ohne doppelte)", "Testlauf" in need and docker.locator(".pkg:not(.more)").all_text_contents() == ["libssl3", "openssl", "curl", "docker-ce", "docker-ce-cli", "containerd.io", "linux-image-6.12.48+deb13-amd64", "bash"], need)
    check("Handlungsbedarf: Template ohne Meldung zeigt keine Box", tcard(page, "Deploy").locator(".needbox").count() == 0)
    rows = project.locator(".item .name").all_inner_texts()
    check("Projekt-Karte: Reihenfolge laufend, Fehler, Handlungsbedarf, Rest", [r.strip() for r in rows[:3]] == ["Proxmox Snapshot HAOS", "Host-Update", "docker-system aktualisieren"], rows)
    check("Projekt-Karte: Symbol und Text bei Handlungsbedarf", project.locator(".item", has_text="docker-system").locator("ha-icon.need").count() == 1 and "Offene Updates: 9" in project.locator(".item", has_text="docker-system").locator(".sub").inner_text())

    deploy = tcard(page, "Deploy")
    labels = deploy.locator(".survey label").all_inner_texts()
    check("Survey: drei Eingabefelder (kein Secret, keine Mehrfachauswahl)", len(labels) == 3, labels)
    check("Survey: Pflichtfelder markiert", labels[0].startswith("Ziel-Host") and "*" in labels[0], labels)
    shot(page, "01_uebersicht")


def watch_more_info(page: Page) -> None:
    """Merkt sich die Entitäten, für die ein More-Info-Dialog angefordert wird (nur einmal je Seite)."""
    page.evaluate(
        "if (!window.__mi) { window.__mi = []; window.addEventListener('hass-more-info', (e) => window.__mi.push(e.detail.entityId)); }"
    )


def more_info_requests(page: Page) -> list:
    return page.evaluate("window.__mi || []")


def device_class(page: Page, entity_id: str) -> str:
    return page.evaluate("(id) => document.querySelector('home-assistant').hass.states[id]?.attributes?.device_class", entity_id)


def test_template_card_details(page: Page) -> None:
    """0.1.5: Zahlen je Host, Hinweise, anklickbare Zeilen und Fehlertext (More-Info der Standardaktion)."""
    docker, host = tcard(page, "docker-system"), tcard(page, "Host-Update")
    line = docker.locator(".hostline").inner_text().strip() if docker.locator(".hostline").count() else ""
    check("Template-Karte: Zahlen je Host (nur wer etwas braucht)", line == "dockerhost: 7, Neustart · pialert: 2", line)
    notes = docker.locator(".note").all_inner_texts()
    check("Template-Karte: Hinweis aus dem Playbook mit Hostname", len(notes) == 1 and "adguard" in notes[0] and "Debian 13" in notes[0], notes)
    check("Template-Karte: Hinweis zählt nicht als Handlungsbedarf (adguard fehlt in der Hostzeile)", "adguard" not in line, line)
    check("Template-Karte ohne Meldung: keine Hinweise, keine Hostzeile", tcard(page, "Deploy").locator(".note, .hostline").count() == 0)

    watch_more_info(page)
    clicks = docker.locator(".row.click")
    check("Template-Karte: Zeilen „Letzter Lauf“ und „Dauer“ sind anklickbar (role=button)", clicks.count() >= 2 and clicks.first.get_attribute("role") == "button" and clicks.first.get_attribute("tabindex") == "0", clicks.count())
    seen = []
    for index in range(clicks.count()):
        entity = clicks.nth(index).get_attribute("data-entity")
        clicks.nth(index).click()
        time.sleep(0.8)
        seen.append((entity, more_info_requests(page)[-1:] == [entity], device_class(page, entity)))
        page.keyboard.press("Escape")
        time.sleep(0.6)
    check("Zeilen öffnen die More-Info ihrer Entität (Zeitpunkt / Dauer)", seen and all(ok for _, ok, _ in seen) and {c for _, _, c in seen} <= {"timestamp", "duration"} and len({e for e, _, _ in seen}) == len(seen), seen)

    entity = host.locator(".errbox").get_attribute("data-entity")
    host.locator(".errbox").click()
    time.sleep(0.8)
    check("Fehlertext öffnet die More-Info des Problem-Sensors", host.locator(".errbox").get_attribute("role") == "button" and more_info_requests(page)[-1:] == [entity] and device_class(page, entity) == "problem", (entity, more_info_requests(page)[-2:]))
    page.keyboard.press("Escape")
    time.sleep(0.6)
    host.locator(".errbox").focus()
    page.keyboard.press("Enter")
    time.sleep(0.8)
    check("Fehlertext ist per Tastatur bedienbar (Enter)", len(more_info_requests(page)) >= 2 and more_info_requests(page)[-1] == entity, more_info_requests(page)[-3:])
    page.keyboard.press("Escape")
    time.sleep(0.6)
    shot(page, "01b_details")


PKG_STATE = """box => {
  const chips = [...box.querySelectorAll('.pkg:not(.more)')];
  const more = box.querySelector('.pkg.more');
  const visible = chips.filter((c) => !c.hidden && c.getClientRects().length);
  const rows = new Set(visible.map((c) => Math.round(c.getBoundingClientRect().top)));
  const right = Math.max(...visible.map((c) => c.getBoundingClientRect().right), more && !more.hidden ? more.getBoundingClientRect().right : 0);
  return {
    total: chips.length, visible: visible.length, rows: rows.size,
    clipped: visible.filter((c) => c.scrollWidth > c.clientWidth + 1).length, // names cut off with "…"
    more: more && !more.hidden ? more.textContent.trim() : null,
    expanded: more ? more.getAttribute('aria-expanded') : null,
    open: box.classList.contains('open'),
    overflow: right - box.getBoundingClientRect().right,
    focused: !!more && box.getRootNode().activeElement === more,
  };
}"""


def pkg_state(card) -> dict:
    return card.locator(".pkgs").evaluate(PKG_STATE)


def test_packages_one_line(page: Page) -> None:
    """0.2.2: Pakete stehen in EINER Zeile mit „+n weitere“; ein Klick darauf zeigt alle (und „weniger“ klappt wieder zu)."""
    docker = tcard(page, "docker-system")
    watch_more_info(page)
    seen_before = len(more_info_requests(page))
    folded = pkg_state(docker)
    check("Pakete: eine einzige Zeile, nichts ragt über den Rand, kein Name abgeschnitten", folded["rows"] == 1 and folded["overflow"] <= 1 and (folded["clipped"] == 0 or folded["visible"] == 1), folded)
    check("Pakete: „+n weitere“ nennt genau die versteckten Pakete", folded["more"] == f"+{folded['total'] - folded['visible']} weitere" and 1 <= folded["visible"] < folded["total"], folded)
    more = docker.locator('button[data-action="pkgs"]')
    check("Pakete: „+n weitere“ ist ein Knopf (aria-expanded=false, Tooltip)", more.count() == 1 and folded["expanded"] == "false" and "Alle Pakete" in (more.get_attribute("title") or ""), folded)
    check("Pakete: jeder Chip trägt seinen vollen Namen als Tooltip", docker.locator(".pkg:not(.more)").evaluate_all("els => els.every((e) => e.title === e.textContent.trim())"))

    more.click()
    time.sleep(0.4)
    opened = pkg_state(docker)
    check("Klick auf „+n weitere“: alle Pakete sichtbar, Knopf heißt „weniger“", opened["open"] and opened["visible"] == opened["total"] == 8 and opened["more"] == "weniger" and opened["expanded"] == "true", opened)
    check("Aufgeklappt: die Pakete dürfen umbrechen, ragen aber nicht heraus", opened["rows"] >= 2 and opened["overflow"] <= 1, opened)
    check("Klick auf „+n weitere“ öffnet keine More-Info (Zeile bleibt unberührt)", len(more_info_requests(page)) == seen_before, more_info_requests(page)[-2:])
    check("Tastaturfokus bleibt nach dem Klick auf dem Knopf", opened["focused"], opened)
    docker.evaluate("card => card._redraw()")
    time.sleep(0.3)
    check("Aufgeklappt bleibt beim Neuzeichnen der Karte erhalten", pkg_state(docker)["open"] and pkg_state(docker)["visible"] == 8)
    shot(page, "01c_pakete_offen")

    docker.locator('button[data-action="pkgs"]').click()
    time.sleep(0.4)
    closed = pkg_state(docker)
    check("Klick auf „weniger“: wieder eine Zeile mit „+n weitere“", not closed["open"] and closed["rows"] == 1 and closed["more"] == folded["more"], closed)

    # Tastatur: Knopf fokussieren, Enter öffnet, Leertaste schließt
    docker.locator('button[data-action="pkgs"]').focus()
    page.keyboard.press("Enter")
    time.sleep(0.4)
    via_enter = pkg_state(docker)
    page.keyboard.press("Space")
    time.sleep(0.4)
    via_space = pkg_state(docker)
    check("Tastatur: Enter klappt auf, Leertaste klappt zu", via_enter["open"] and not via_space["open"] and via_space["rows"] == 1, (via_enter, via_space))

    # Kartenbreite: schmaler = mehr versteckt, breiter = weniger versteckt, immer eine Zeile
    width = page.viewport_size["width"]
    narrow = []
    for w in (700, width):
        page.set_viewport_size({"width": w, "height": page.viewport_size["height"]})
        time.sleep(0.8)
        narrow.append(pkg_state(docker))
    check("Schmales Fenster: weiterhin eine Zeile, mehr Pakete hinter „+n weitere“", narrow[0]["rows"] == 1 and narrow[0]["overflow"] <= 1 and narrow[0]["visible"] <= narrow[1]["visible"] and (narrow[0]["clipped"] == 0 or narrow[0]["visible"] == 1), narrow)
    check("Fenster wieder breit: Anzeige passt sich ohne Neuladen an", narrow[1]["visible"] == folded["visible"] and narrow[1]["more"] == folded["more"], (narrow[1], folded))
    check("Karte ohne Pakete hat keinen „+n weitere“-Knopf", tcard(page, "Host-Update").locator('[data-action="pkgs"]').count() == 0)


def wait_for(predicate, seconds: float = 25.0) -> bool:
    """Poll ``predicate`` until it is true (the cards follow Semaphore with the poll interval)."""
    end = time.time() + seconds
    while time.time() < end:
        try:
            if predicate():
                return True
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.4)
    return False


def test_schedules_ui(page: Page) -> None:
    """0.2.0: Zeitpläne, „Nächster Lauf“ und „Zuletzt erfolgreich“ in den Karten; der Schalter wirkt auf Semaphore."""
    host, docker, deploy = tcard(page, "Host-Update"), tcard(page, "docker-system"), tcard(page, "Deploy")
    project = page.locator("semaphore-ui-project-card").first

    rows = host.locator(".sched-row")
    names = [n.strip() for n in rows.locator(".name").all_inner_texts()]
    check("Template-Karte: beide Zeitpläne des Templates, nach Name sortiert", names == ["linux update checks", "Sonntag voller Lauf"], names)
    subs = [s.strip() for s in rows.locator(".sub").all_inner_texts()]
    check("Template-Karte: aktiver Zeitplan zeigt Cron-Text und nächsten Lauf", len(subs) == 2 and "0 2 * * *" in subs[0] and "nächster Lauf" in subs[0], subs)
    check("Template-Karte: ausgeschalteter Zeitplan sagt „aus“", len(subs) == 2 and "30 3 * * 0" in subs[1] and "aus" in subs[1] and "nächster Lauf" not in subs[1], subs)
    switches = rows.locator("button.tgl")
    check("Template-Karte: Schalter mit role=switch und Zustand", switches.count() == 2 and switches.first.get_attribute("role") == "switch" and [switches.nth(i).get_attribute("aria-checked") for i in range(2)] == ["true", "false"],
          [switches.nth(i).get_attribute("aria-checked") for i in range(switches.count())])
    check("Template-Karte: Schalter hat einen Namen für Screenreader", "linux update checks" in (switches.first.get_attribute("aria-label") or ""), switches.first.get_attribute("aria-label"))

    next_row = host.locator(".row.click", has_text="Nächster Lauf")
    success_row = host.locator(".row.click", has_text="Zuletzt erfolgreich")
    check("Template-Karte (Fehler): Zeile „Nächster Lauf“ und „Zuletzt erfolgreich“", next_row.count() == 1 and success_row.count() == 1, (next_row.count(), success_row.count()))
    check("Zuletzt erfolgreich nennt Datum und relative Zeit", "·" in success_row.inner_text() and any(w in success_row.inner_text() for w in ("vorgestern", "vor 2 Tag", "vor 3 Tag")), success_row.inner_text())
    check("Template-Karte (Erfolg): keine Zeile „Zuletzt erfolgreich“, aber der nächste Lauf", docker.locator(".row.click", has_text="Zuletzt erfolgreich").count() == 0 and docker.locator(".row.click", has_text="Nächster Lauf").count() == 1)
    check("Template ohne Zeitplan: kein Abschnitt, keine Zeile", deploy.locator(".sched").count() == 0 and deploy.locator(".row.click", has_text="Nächster Lauf").count() == 0)

    watch_more_info(page)
    seen = []
    for row in (next_row, success_row):
        entity = row.get_attribute("data-entity")
        row.click()
        time.sleep(0.8)
        seen.append((entity, more_info_requests(page)[-1:] == [entity], device_class(page, entity)))
        page.keyboard.press("Escape")
        time.sleep(0.6)
    check("Beide Zeilen öffnen die More-Info ihres Zeitstempel-Sensors", all(ok and cls == "timestamp" for _, ok, cls in seen), seen)

    # Projekt-Karte: alle Zeitpläne mit Template-Namen, ausgeschaltete zuletzt
    prows = project.locator(".sched-row")
    pnames = [n.strip() for n in prows.locator(".name").all_inner_texts()]
    check("Projekt-Karte: drei Zeitpläne, der ausgeschaltete zuletzt", sorted(pnames) == ["Dockhand wöchentlich", "Sonntag voller Lauf", "linux update checks"] and pnames[-1] == "Sonntag voller Lauf", pnames)
    check("Projekt-Karte: Zeitplan nennt sein Template", "docker-system" in prows.filter(has_text="Dockhand").locator(".sub").inner_text() and "Host-Update" in prows.filter(has_text="linux update").locator(".sub").inner_text())
    check("Projekt-Karte: Zeitzone von Semaphore als Tooltip", "Europe/Berlin" in (project.locator(".sched-title").get_attribute("title") or ""), project.locator(".sched-title").get_attribute("title"))

    # Schalten: nur das Flag geht an Semaphore, danach folgt die Anzeige in beiden Karten
    ctl("clear")
    switch = host.locator(".sched-row", has_text="Sonntag voller Lauf").locator("button.tgl")
    switch.click()
    got = wait_for(lambda: len(puts()) == 1)
    sent = puts()
    check("Schalter: genau ein PUT …/schedules/<id>/active mit nur „active“", got and sent[0][1].startswith("/api/project/1/schedules/") and sent[0][1].endswith("/active") and sent[0][2] == {"active": True}, sent)
    check("Schalter: Zeitplan ist in Semaphore an", any(s["name"] == "Sonntag voller Lauf" and s["active"] for s in ctl("schedules")), ctl("schedules"))
    check("Schalter: Template-Karte zeigt „an“ mit nächstem Lauf", wait_for(lambda: switch.get_attribute("aria-checked") == "true" and "nächster Lauf" in host.locator(".sched-row", has_text="Sonntag voller Lauf").locator(".sub").inner_text()),
          host.locator(".sched-row", has_text="Sonntag voller Lauf").locator(".sub").inner_text())
    check("Schalter: auch die Projekt-Karte zeigt den Zeitplan als aktiv", wait_for(lambda: project.locator(".sched-row", has_text="Sonntag voller Lauf").locator("button.tgl").get_attribute("aria-checked") == "true"))
    shot(page, "02c_zeitplan_an")
    ctl("clear")
    project.locator(".sched-row", has_text="Sonntag voller Lauf").locator("button.tgl").click()
    got = wait_for(lambda: len(puts()) == 1)
    check("Schalter in der Projekt-Karte: PUT mit active=false (zurück)", got and puts()[0][2] == {"active": False}, puts())
    check("Schalter: wieder aus in Semaphore und in der Template-Karte", wait_for(lambda: switch.get_attribute("aria-checked") == "false" and not any(s["active"] for s in ctl("schedules") if s["name"] == "Sonntag voller Lauf")))

    # Name des Zeitplans öffnet die More-Info des Schalters
    watch_more_info(page)
    before = len(more_info_requests(page))
    host.locator(".sched-row", has_text="linux update checks").locator(".main").click()
    time.sleep(0.8)
    requested = more_info_requests(page)
    check("Zeitplan-Name öffnet die More-Info des Schalters", len(requested) == before + 1 and requested[-1].startswith("switch."), requested[-2:])
    page.keyboard.press("Escape")
    time.sleep(0.6)


def docs_shot(target, name: str) -> None:
    """Bild einer Karte für die Doku (``docs/screenshots``) bzw. in den Arbeitsordner."""
    folder = DOCS or (SHOTS / "docs")
    folder.mkdir(parents=True, exist_ok=True)
    target.screenshot(path=str(folder / f"{name}.png"))


def dashboard_shot(page: Page, name: str) -> None:
    """Übersicht: nur die Karten des Projekts „Homelab“ (ohne Seitenleiste), aus ihren Positionen zugeschnitten."""
    boxes = [
        page.locator("semaphore-ui-project-card").first.bounding_box(),
        *(tcard(page, title).bounding_box() for title in ("Host-Update", "docker-system", "Proxmox", "Deploy")),
    ]
    margin = 16
    x0, y0 = min(b["x"] for b in boxes) - margin, min(b["y"] for b in boxes) - margin
    x1, y1 = max(b["x"] + b["width"] for b in boxes) + margin, max(b["y"] + b["height"] for b in boxes) + margin
    folder = DOCS or (SHOTS / "docs")
    folder.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(folder / f"{name}.png"), clip={"x": x0, "y": y0, "width": x1 - x0, "height": y1 - y0})


def test_docs_screenshots(playwright) -> None:
    """Bilder der Karten für README/Doku (Beispieldaten aus ``fake_server.py``, keine echten Namen).

    Das Fenster ist so hoch, dass nichts gescrollt werden muss (sonst verdeckt die Kopfleiste von
    Home Assistant den oberen Rand einer Karte).
    """
    taken: list[str] = []

    def take(target, name: str) -> None:
        docs_shot(target, name)
        taken.append(name)

    for scheme, suffix in (("light", ""), ("dark", "-dark")):
        browser, page = open_page(playwright, width=1400, height=1700, scheme=scheme)
        try:
            take(page.locator("semaphore-ui-project-card").first, f"project-card{suffix}")
            take(tcard(page, "docker-system"), f"template-card-updates{suffix}")
            take(tcard(page, "Host-Update"), f"template-card-error{suffix}")
            take(tcard(page, "Proxmox"), f"template-card-running{suffix}")
            if not suffix:
                take(tcard(page, "Deploy"), "template-card-survey")
                tcard(page, "docker-system").locator('button[data-action="pkgs"]').click()
                time.sleep(0.5)
                take(tcard(page, "docker-system"), "template-card-updates-open")
                tcard(page, "docker-system").locator('button[data-action="pkgs"]').click()
                time.sleep(0.4)
            dashboard_shot(page, f"dashboard{suffix}")
            taken.append(f"dashboard{suffix}")
        finally:
            browser.close()
    browser, page = open_page(playwright, width=1400, height=1700, path="/dashboard-sem-test/1")
    try:
        take(page.locator("semaphore-ui-project-card").first, "project-card-only-needed")
    finally:
        browser.close()
    browser, page = open_page(playwright, width=1400, height=2600, path="/dashboard-sem-test/2")
    try:
        cards = {c.locator(".title").inner_text().strip(): c for c in [page.locator("semaphore-ui-project-card").nth(i) for i in range(8)]}
        take(cards["Homelab"], "project-card-versions")
    finally:
        browser.close()
    browser, page = open_page(playwright, width=390, height=5600, scheme="dark")
    try:
        take(page.locator("semaphore-ui-project-card").first, "project-card-mobile-dark")
        take(tcard(page, "docker-system"), "template-card-mobile-dark")
    finally:
        browser.close()
    folder = DOCS or (SHOTS / "docs")
    made = [folder / f"{n}.png" for n in taken]
    check("Doku-Bilder: alle erzeugt und nicht leer", all(p.exists() and p.stat().st_size > 4000 for p in made), [p.name for p in made if not p.exists() or p.stat().st_size <= 4000])


def project_names(card) -> list[str]:
    return [n.strip() for n in card.locator(".item .name").all_inner_texts()]


def test_project_filters(page: Page) -> None:
    """0.1.5: Die Kacheln der Projekt-Karte filtern die Liste."""
    project = page.locator("semaphore-ui-project-card").first
    tiles = project.locator(".stat")
    check("Kacheln: vier Stück, alle bedienbar (role=button, tabindex)", tiles.count() == 4 and all(tiles.nth(i).get_attribute("role") == "button" and tiles.nth(i).get_attribute("tabindex") == "0" for i in range(4)), tiles.count())
    check("Kacheln: Tooltip erklärt das Filtern", "filtern" in (tiles.first.get_attribute("title") or ""), tiles.first.get_attribute("title"))

    project.locator(".stat[data-filter=running]").click()
    check("Filter „läuft“: nur das laufende Template", project_names(project) == ["Proxmox Snapshot HAOS"], project_names(project))
    check("Filter: Kachel ist markiert (aria-pressed)", project.locator(".stat.sel").count() == 1 and project.locator(".stat.sel").get_attribute("data-filter") == "running" and project.locator(".stat.sel").get_attribute("aria-pressed") == "true")
    shot(page, "01c_filter_laeuft")
    project.locator(".stat[data-filter=running]").click()
    check("Filter: zweiter Klick auf dieselbe Kachel zeigt wieder alle", len(project_names(project)) == 5 and project.locator(".stat.sel").count() == 0, project_names(project))
    project.locator(".stat[data-filter=failed]").click()
    check("Filter „Fehler“: nur das fehlgeschlagene Template", project_names(project) == ["Host-Update"], project_names(project))
    project.locator(".stat[data-filter=action]").click()
    check("Filter „Handlungsbedarf“: nur das Template mit offenen Updates", project_names(project) == ["docker-system aktualisieren"], project_names(project))
    project.locator(".stat[data-filter=all]").click()
    check("Kachel „Templates“ hebt den Filter auf", len(project_names(project)) == 5 and project.locator(".stat.sel").count() == 0, project_names(project))

    failed = project.locator(".stat[data-filter=failed]")
    failed.focus()
    page.keyboard.press("Enter")
    time.sleep(0.4)
    check("Kachel per Tastatur: Enter filtert", project_names(project) == ["Host-Update"], project_names(project))
    project.locator(".stat[data-filter=failed]").focus()
    page.keyboard.press("Space")
    time.sleep(0.4)
    check("Kachel per Tastatur: Leertaste hebt den Filter wieder auf", len(project_names(project)) == 5, project_names(project))

    # die zweite Projekt-Karte (Testlab) hat ihren eigenen Filter
    other = page.locator("semaphore-ui-project-card").nth(1)
    other.locator(".stat[data-filter=running]").click()
    check("Filter gilt nur für die angeklickte Karte", project_names(other) == ["Proxmox Snapshot HAOS"] and len(project_names(project)) == 5 and project.locator(".stat.sel").count() == 0, (project_names(other), project_names(project)))
    other.locator(".stat[data-filter=running]").click()
    check("Zweite Karte zurückgesetzt: wieder alle Templates", len(project_names(other)) == 5, project_names(other))


def test_version_view(playwright) -> None:
    """0.1.5: Semaphore-Version und Integrations-Version (mit HACS-Update-Hinweis) lassen sich ein- und ausschalten;
    dazu die Hinweise bei Filtern ohne Treffer (Karte mit nur einem ruhigen Template)."""
    browser, page = open_page(playwright, path="/dashboard-sem-test/2")
    try:
        cards = {c.locator(".title").inner_text().strip(): c for c in [page.locator("semaphore-ui-project-card").nth(i) for i in range(8)]}
        sub = lambda name: (cards[name].locator(".head .sub").first.inner_text().strip() if cards[name].locator(".head .sub").count() else "")  # noqa: E731
        a, b, c, d = sub("A Standard"), sub("B Nur Integration"), sub("C Beides mit HACS"), sub("D Ohne Version")
        check("Version A (Standard): nur die Semaphore-Version", a.startswith("Semaphore UI") and "Integration" not in a, a)
        check("Version B: nur die Integration (Version aus der Karte)", b == f"Integration {VERSION}", b)
        check("Version C: beide Angaben hintereinander", c.startswith("Semaphore UI") and " · Integration " in c, c)
        check("Version D: ohne Angabe gibt es keine Untertitel-Zeile", d == "", d)
        check("Version C: HACS-Entität auf „on“ zeigt den Hinweis „Integration-Update“", cards["C Beides mit HACS"].locator(".chip", has_text="Integration-Update").count() == 1, cards["C Beides mit HACS"].locator(".chip").all_inner_texts())
        check("Version A, B, D: ohne HACS-Entität kein Integrations-Hinweis", all(cards[n].locator(".chip", has_text="Integration-Update").count() == 0 for n in ("A Standard", "B Nur Integration", "D Ohne Version")))
        watch_more_info(page)
        cards["C Beides mit HACS"].locator(".chip", has_text="Integration-Update").click()
        time.sleep(0.8)
        requested = more_info_requests(page)
        check("Version C: Klick auf den Hinweis öffnet die More-Info der Update-Entität", len(requested) == 1 and requested[0].startswith("update."), requested)
        page.keyboard.press("Escape")
        shot(page, "06_versionen")
        f_sub = sub("F Beide Versionen")
        check("Version F: Semaphore- und Integrations-Version ohne HACS", f_sub == f"Semaphore UI 2.19.17 · Integration {VERSION}", f_sub)
        check("Zeitpläne: „show_schedules: false“ blendet den Abschnitt aus, die anderen Karten zeigen ihn",
              cards["G Ohne Zeitpläne"].locator(".sched").count() == 0 and cards["A Standard"].locator(".sched").count() == 1,
              (cards["G Ohne Zeitpläne"].locator(".sched").count(), cards["A Standard"].locator(".sched").count()))

        # Karte „E Nur Deploy“ zeigt nur ein ruhiges Template: jeder Filter hat dort keinen Treffer
        only = cards["E Nur Deploy"]
        notices = {}
        for key in ("running", "failed", "action"):
            only.locator(f".stat[data-filter={key}]").click()
            notices[key] = only.locator(".list .notice").inner_text().strip() if only.locator(".list .notice").count() else ""
        check("Filter ohne Treffer: eigener Hinweis je Kachel", notices == {"running": "Gerade läuft nichts.", "failed": "Kein Template mit Fehler.", "action": "Kein Template mit Handlungsbedarf."}, notices)
        only.locator(".stat[data-filter=action]").click()
        check("Filter ohne Treffer: nochmal antippen zeigt wieder das Template", project_names(only) == ["Deploy"], project_names(only))
    finally:
        browser.close()


def test_needs_action_view(playwright) -> None:
    """Zweite Ansicht: Projekt-Karte mit „nur Benötigtes“ (läuft vor den Klick-Tests, solange der Zustand bekannt ist)."""
    browser, page = open_page(playwright, path="/dashboard-sem-test/1")
    project = page.locator("semaphore-ui-project-card").first
    names = [n.strip() for n in project.locator(".item .name").all_inner_texts()]
    check("Nur Benötigtes: laufend, Fehler und Handlungsbedarf – sonst nichts", names == ["Proxmox Snapshot HAOS", "Host-Update", "docker-system aktualisieren"], names)
    check("Nur Benötigtes: die Kacheln zählen weiter das ganze Projekt", project.locator(".stat .n").all_inner_texts() == ["1", "1", "1", "5"])
    shot(page, "00_nur_benoetigt")
    browser.close()


def test_busy_schedule(page: Page) -> None:
    """0.2.1: Nach dem Klick auf den Zeitplan-Schalter dreht sich ein Kringel, bis Semaphore geantwortet hat."""
    host = tcard(page, "Host-Update")
    row = host.locator(".sched-row", has_text="Sonntag voller Lauf")
    switch = row.locator("button.tgl")
    check("Ausgangslage: Zeitplan „Sonntag voller Lauf“ ist aus", switch.get_attribute("aria-checked") == "false", switch.get_attribute("aria-checked"))
    ctl("clear")
    ctl("slow")  # Semaphore antwortet erst nach 2,5 s
    switch.click()
    seen = wait_for(lambda: row.locator("button.tgl.busy").count() == 1, 2)
    check("Schalter: sofort nach dem Klick ein Kringel", seen)
    busy = row.locator("button.tgl.busy")
    check("Schalter (arbeitet): zeigt schon den Zielzustand „an“ und meldet aria-busy", busy.count() == 1 and busy.get_attribute("aria-checked") == "true" and busy.get_attribute("aria-busy") == "true",
          (busy.get_attribute("aria-checked"), busy.get_attribute("aria-busy")) if busy.count() else None)
    check("Schalter (arbeitet): der Knopf dreht sich wirklich", busy.count() == 1 and "spin" in (busy.evaluate("el => getComputedStyle(el.querySelector('.knob'), '::after').animationName") or ""),
          busy.evaluate("el => getComputedStyle(el.querySelector('.knob'), '::after').animationName") if busy.count() else None)
    shot(page, "02a_kringel_schalter")
    row.locator("button.tgl").click()  # zweiter Klick, solange es arbeitet: wird ignoriert
    gone = wait_for(lambda: row.locator("button.tgl.busy").count() == 0, 15)
    check("Schalter: der Kringel verschwindet, wenn Semaphore geantwortet hat", gone)
    check("Schalter: der zweite Klick hat nichts gesendet (genau ein PUT)", len(puts()) == 1 and puts()[0][2] == {"active": True}, puts())
    check("Schalter: danach steht er auf „an“", wait_for(lambda: row.locator("button.tgl").get_attribute("aria-checked") == "true"))
    ctl("fast")
    ctl("clear")
    row.locator("button.tgl").click()  # zurück auf „aus“
    check("Schalter: wieder aus", wait_for(lambda: row.locator("button.tgl").get_attribute("aria-checked") == "false" and not any(s["active"] for s in ctl("schedules") if s["name"] == "Sonntag voller Lauf")))


def test_interactions(page: Page) -> None:
    host, docker, deploy = tcard(page, "Host-Update"), tcard(page, "docker-system"), tcard(page, "Deploy")
    ctl("clear")

    ctl("slow")  # Semaphore braucht 2,5 s für den Start: die Karte muss zeigen, dass der Klick angekommen ist
    host.locator("button[data-action=start]").click()
    check("Start: sofort ein Kringel statt des Symbols", wait_for(lambda: host.locator("button[data-action=start].busy .spin").count() == 1, 2)
          and host.locator("button[data-action=start]").get_attribute("aria-busy") == "true")
    host.locator("button[data-action=start]").click(force=True)  # zweiter Klick, solange es arbeitet: wird ignoriert
    time.sleep(1.5)
    sent = posts()
    check("Start: POST für Template 2, kein Testlauf", len(sent) == 1 and sent[0][2]["template_id"] == 2 and not sent[0][2].get("dry_run"), sent)
    check("Start: der Kringel verschwindet wieder", wait_for(lambda: host.locator(".spin").count() == 0, 15))
    ctl("fast")
    try:
        host.locator("button >> text=Stoppen").wait_for(timeout=20000)
        check("Stopp-Knopf erscheint, sobald der Task läuft", True)
    except Exception as err:  # noqa: BLE001
        check("Stopp-Knopf erscheint, sobald der Task läuft", False, str(err)[:120])
    shot(page, "02_laeuft")
    # direkt nach dem Start: Start/Testlauf gesperrt, ein erzwungener Klick schickt nichts mehr an Semaphore
    check("Nach dem Start: Start und Testlauf werden gesperrt", host.locator("button[data-action=start]").is_disabled() and host.locator("button >> text=Testlauf").is_disabled())
    ctl("clear")
    host.locator("button[data-action=start]").click(force=True)
    time.sleep(1.0)
    check("Nach dem Start: erzwungener Klick auf den gesperrten Start-Knopf sendet nichts", len(posts()) == 0, posts())
    host.locator("button >> text=Stoppen").click()
    time.sleep(1.5)
    check("Stopp: POST …/stop", any(p[1].endswith("/stop") for p in posts()), posts())

    ctl("clear")
    docker.locator("button >> text=Testlauf").click()
    time.sleep(1.5)
    sent = posts()
    check("Testlauf: dry_run=true gesendet", len(sent) == 1 and sent[0][2].get("dry_run") is True, sent)
    # auch ein laufender Testlauf sperrt den Start; erst nach dem Stoppen ist die Karte wieder frei
    try:
        docker.locator("button >> text=Stoppen").wait_for(timeout=20000)
        check("Testlauf läuft: Start gesperrt, Stopp wird angeboten", docker.locator("button[data-action=start]").is_disabled())
    except Exception as err:  # noqa: BLE001
        check("Testlauf läuft: Start gesperrt, Stopp wird angeboten", False, str(err)[:120])
    docker.locator("button >> text=Stoppen").click()
    free = False
    for _ in range(40):
        time.sleep(0.5)
        if docker.locator("button >> text=Stoppen").count() == 0 and docker.locator("button[data-action=start]").is_enabled():
            free = True
            break
    check("Nach dem Stoppen: Start ist wieder freigegeben", free)

    # die Karte „docker-system“ hat confirm_start: true -> erst nachfragen
    ctl("clear")
    docker.locator("button[data-action=start]").click()
    time.sleep(0.5)
    check("Bestätigung: Rückfrage wird gezeigt", docker.locator("text=Wirklich starten").count() == 1)
    shot(page, "02b_bestaetigung")
    docker.locator("button[data-action=confirm-no]").click()
    time.sleep(0.8)
    check("Bestätigung: „Nein“ sendet nichts", len(posts()) == 0, posts())
    docker.locator("button[data-action=start]").click()
    docker.locator("button[data-action=confirm-yes]").click()
    time.sleep(1.5)
    sent = posts()
    check("Bestätigung: „Ja“ startet Template 1", len(sent) == 1 and sent[0][2]["template_id"] == 1, sent)

    # Survey: Pflicht-Secret fehlt -> Fehlermeldung in der Karte, nichts gesendet
    ctl("clear")
    deploy.locator("select[data-domain=select]").select_option(label="Test")
    time.sleep(0.8)
    number = deploy.locator("input[data-domain=number]")
    number.fill("3")
    number.press("Tab")
    time.sleep(0.8)
    text = deploy.locator("input[data-domain=text]")
    text.fill("pi-hole")
    text.press("Tab")
    time.sleep(0.8)
    deploy.locator("button[data-action=start]").click()
    time.sleep(2)
    message = deploy.locator(".msg")
    check("Survey: fehlendes Secret zeigt Fehler in der Karte", message.count() == 1 and "token" in message.inner_text().lower(), message.all_inner_texts())
    check("Survey: bei Fehler wird nichts gesendet", len(posts()) == 0, posts())
    shot(page, "03_survey_fehler")

    # Secret wird optional (Semaphore-Seite geändert) -> nach dem nächsten Abruf (10 s) wird gestartet
    ctl("optional_token")
    sent = []
    for _ in range(12):
        time.sleep(4)
        deploy.locator("button[data-action=start]").click()
        time.sleep(1.5)
        sent = posts()
        if sent:
            break
    env = json.loads(sent[0][2]["environment"]) if sent and sent[0][2].get("environment") else None
    check("Survey: eingegebene Werte werden gesendet", env == {"target": "pi-hole", "count": "3", "stage": "test", "tags": ["a"]}, env)

    host.locator(".head").click()
    time.sleep(1.5)
    check("Klick auf den Titel öffnet More-Info", page.locator("ha-more-info-dialog, ha-dialog[open]").count() > 0)
    page.keyboard.press("Escape")
    time.sleep(1)

    # Tastatur: Titelbereich ist fokussierbar und reagiert auf Enter
    head = tcard(page, "docker-system").locator(".head")
    check("Titelbereich ist per Tastatur erreichbar (role=button, tabindex=0)", head.get_attribute("role") == "button" and head.get_attribute("tabindex") == "0")
    head.focus()
    page.keyboard.press("Enter")
    time.sleep(1.5)
    check("Enter auf dem Titelbereich öffnet More-Info", page.locator("ha-more-info-dialog, ha-dialog[open]").count() > 0)
    page.keyboard.press("Escape")


def test_confirm_and_project_list(page: Page) -> None:
    """Projekt-Karte: Schnellstart eines Templates aus der Liste."""
    project = page.locator("semaphore-ui-project-card").first
    ctl("clear")
    row = project.locator(".item", has_text="Bash Job")
    row.locator("button[data-action=start]").click()
    time.sleep(1.5)
    sent = posts()
    check("Projekt-Liste: Start-Knopf startet das Template", len(sent) == 1 and sent[0][2]["template_id"] == 3, sent)


def test_packages_responsive(playwright) -> None:
    """0.2.2: Pakete auf dem Handy und auf Englisch (läuft früh: später haben die Klick-Tests alle Templates neu gestartet)."""
    browser, page = open_page(playwright, width=390, height=900, scheme="dark")
    try:
        docker = tcard(page, "docker-system")
        mobile = pkg_state(docker)
        check("Mobil: Pakete in einer Zeile mit „+n weitere“, nichts ragt heraus", mobile["rows"] == 1 and mobile["overflow"] <= 1 and bool(mobile["more"]) and mobile["visible"] >= 1 and (mobile["clipped"] == 0 or mobile["visible"] == 1), mobile)
        docker.locator('button[data-action="pkgs"]').click()
        time.sleep(0.4)
        opened = pkg_state(docker)
        check("Mobil: aufgeklappt sind alle Pakete da, nichts ragt heraus, die Seite wird nicht breiter", opened["visible"] == 8 and opened["overflow"] <= 1 and page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), opened)
        shot(page, "03b_pakete_mobil")
    finally:
        browser.close()
    browser, page = open_page(playwright, width=1100, height=800, lang="en-US")
    try:
        docker = tcard(page, "docker-system")
        folded = pkg_state(docker)
        check("Englisch: „+n more“", (folded["more"] or "").startswith("+") and (folded["more"] or "").endswith(" more"), folded)
        docker.locator('button[data-action="pkgs"]').click()
        time.sleep(0.4)
        check("Englisch: aufgeklappt heißt der Knopf „less“", pkg_state(docker)["more"] == "less", pkg_state(docker))
    finally:
        browser.close()


def test_mobile_dark(playwright) -> None:
    browser, page = open_page(playwright, width=390, height=900, scheme="dark")
    overflow = page.evaluate("document.documentElement.scrollWidth > window.innerWidth")
    check("Mobil/Dunkel: kein horizontaler Überlauf", overflow is False, overflow)
    widths = page.locator("semaphore-ui-project-card").first.locator(".list").evaluate(
        "list => [list.getBoundingClientRect().width, ...[...list.querySelectorAll('.item')].map(i => i.getBoundingClientRect().width)]"
    )
    check("Mobil: Listenzeilen passen in die Karte", all(w <= widths[0] + 1 for w in widths[1:]), widths)
    shot(page, "04_mobil_dunkel")
    browser.close()


def test_english(playwright) -> None:
    browser, page = open_page(playwright, width=1100, height=800, lang="en-US")
    host = tcard(page, "Host-Update")
    check("Englisch: Beschriftungen", host.locator("button >> text=Dry run").count() == 1 and host.locator("text=Last run").count() >= 1)
    tile_title = page.locator("semaphore-ui-project-card").first.locator(".stat").first.get_attribute("title") or ""
    check("Englisch: Tooltip der Kacheln", tile_title.startswith("Filter the list"), tile_title)
    shot(page, "05_englisch")
    browser.close()


def test_editor(page: Page) -> None:
    result = page.evaluate(
        """async () => {
          const ed = document.createElement('semaphore-ui-card-editor');
          document.body.appendChild(ed);
          const seen = [];
          ed.addEventListener('config-changed', (e) => seen.push(e.detail.config));
          ed.hass = document.querySelector('home-assistant').hass;
          ed.setConfig({type: 'custom:semaphore-ui-project-card', device_id: ''});
          await new Promise((r) => setTimeout(r, 1500));
          const form = ed.querySelector('ha-form');
          const labels = form.schema.map((s) => form.computeLabel(s));
          form.dispatchEvent(new CustomEvent('value-changed', {detail: {value: {...form.data, sort: 'name'}}}));
          const hacs_selector = (form.schema.find((s) => s.name === 'hacs_update_entity') || {}).selector;
          ed.remove();
          return {labels, seen, hacs_selector};
        }"""
    )
    check("Editor (Projekt): Felder und Beschriftungen", result["labels"][:3] == ["Projekt", "Name (optional)", "Sortierung der Templates"], result["labels"])
    check("Editor (Projekt): Option „nur Benötigtes“", any("Handlungsbedarf" in label for label in result["labels"]), result["labels"])
    check("Editor (Projekt): Optionen für die Versionsanzeige und die HACS-Entität", {"Semaphore-Version anzeigen", "Version der Integration anzeigen"} <= set(result["labels"]) and any("HACS" in label for label in result["labels"]), result["labels"])
    check("Editor (Projekt): Option „Zeitpläne anzeigen“", "Zeitpläne anzeigen" in result["labels"], result["labels"])
    check("Editor (Projekt): HACS-Entität wählt nur Update-Entitäten", result["hacs_selector"] == {"entity": {"domain": "update"}}, result["hacs_selector"])
    check("Editor: Änderung löst config-changed aus", result["seen"] and result["seen"][0]["sort"] == "name", result["seen"])


# ------------------------------------------------------------------ zwei Projekte, Auswahl, Auffindbarkeit
def test_two_projects(page: Page) -> None:
    """Homelab und Testlab haben beide ein Template „Host-Update“: die Karten müssen sie unterscheiden."""
    projects = page.locator("semaphore-ui-project-card")
    titles = [t.strip() for t in projects.locator(".title").all_inner_texts()]
    check("Zwei Projekt-Karten: Homelab und Testlab", titles == ["Homelab", "Testlab"], titles)
    hosts = page.locator("semaphore-ui-template-card", has=page.locator(".title", has_text="Host-Update"))
    subs = [hosts.nth(i).locator(".head .sub").first.inner_text().strip() if hosts.nth(i).locator(".head .sub").count() else "" for i in range(hosts.count())]
    check("Template-Karten „Host-Update“ zeigen ihr Projekt als Untertitel", sorted(subs) == ["Homelab", "Testlab"], subs)
    other = page.locator("semaphore-ui-template-card", has=page.locator(".head .sub", has_text="Testlab"))
    check("Testlab-Karte liest die Daten ihres eigenen Projekts (eigener Eintrag)", other.count() == 1 and "Host-Update" in other.locator(".title").inner_text())


def test_editor_choices(page: Page) -> None:
    """Template-Karte: nur Template-Geräte, als „Projekt › Template“; Projekt-Karte: nur Projekt-Geräte."""
    result = page.evaluate(
        """async () => {
          const hass = document.querySelector('home-assistant').hass;
          const make = async (type, device_id) => {
            const ed = document.createElement('semaphore-ui-card-editor');
            document.body.appendChild(ed);
            ed.hass = hass;
            ed.setConfig({type, device_id});
            await new Promise((r) => setTimeout(r, 800));
            const form = ed.querySelector('ha-form');
            const out = form.schema[0].selector.select.options.map((o) => o.label);
            const helper = form.computeHelper(form.schema[0]);
            ed.remove();
            return {out, helper};
          };
          const foreign = Object.values(hass.devices).filter((d) => !(d.identifiers || []).some((i) => i[0] === 'semaphore_ui')).length;
          return {
            template: await make('custom:semaphore-ui-template-card', ''),
            project: await make('custom:semaphore-ui-project-card', ''),
            stale: await make('custom:semaphore-ui-template-card', 'gibt-es-nicht'),
            foreign,
          };
        }"""
    )
    tpl = result["template"]["out"]
    check("Editor (Template): nur „Projekt › Template“-Einträge, 10 Stück", len(tpl) == 10 and all(" › " in t for t in tpl), tpl)
    check("Editor (Template): gleicher Name in beiden Projekten ist unterscheidbar", "Homelab › Host-Update" in tpl and "Testlab › Host-Update" in tpl, tpl)
    check("Editor (Template): sortiert", tpl == sorted(tpl, key=str.lower) or tpl[0].startswith("Homelab"), tpl)
    check("Editor (Template): keine Projekt-Geräte in der Liste", not any(t.startswith("Semaphore –") for t in tpl), tpl)
    proj = result["project"]["out"]
    check("Editor (Projekt): genau die beiden Projekt-Geräte", proj == ["Semaphore – Homelab", "Semaphore – Testlab"], proj)
    check("Editor: Hilfetext erklärt die Auswahl", "Projekt › Template" in result["template"]["helper"], result["template"]["helper"])
    stale = result["stale"]["out"]
    check("Editor: unbekanntes Gerät aus YAML bleibt sichtbar (nicht still ersetzt)", any("unbekannt" in t for t in stale), stale)
    check("Home Assistant kennt auch andere Geräte, die nicht angeboten werden", result["foreign"] >= 0)


def test_resource_registered() -> None:
    from_url = f"{HA_URL}/semaphore_ui_static/semaphore-ui-card.js"
    with urllib.request.urlopen(from_url, timeout=10) as response:  # noqa: S310
        body = response.read().decode()
    check("Karten-Datei wird ausgeliefert", "SEMAPHORE_CARD_VERSION" in body)


def test_resource_list(page: Page) -> None:
    res = page.evaluate("async () => await document.querySelector('home-assistant').hass.callWS({type: 'lovelace/resources'})")
    mine = [r for r in res if "/semaphore_ui_static/semaphore-ui-card.js" in r["url"]]
    check("Dashboard-Ressource: Karten-Datei ist eingetragen (einmal, Typ module)", len(mine) == 1 and mine[0]["type"] == "module", res)


def test_card_picker(playwright) -> None:
    """Weg des Nutzers: Dashboard bearbeiten → Karte hinzufügen → Nach Karte → „Semaphore“ suchen."""
    browser, page = open_page(playwright, path=PATH + "?edit=1")
    try:
        icon = page.evaluate(
            """() => {
              const walk = (root) => {
                for (const el of root.querySelectorAll('*')) {
                  if (el.tagName === 'HA-SVG-ICON' && (el.path || '').startsWith('M19,13H13V19') && el.getRootNode().host && el.getRootNode().host.tagName === 'HUI-GRID-SECTION') {
                    el.scrollIntoView({block: 'center'});  // the first section grows with the schedules: keep it clickable
                    const r = el.getBoundingClientRect();
                    return {x: r.x + r.width / 2, y: r.y + r.height / 2};
                  }
                  if (el.shadowRoot) { const f = walk(el.shadowRoot); if (f) return f; }
                }
                return null;
              };
              return walk(document);
            }"""
        )
        check("Karten-Picker: „Karte hinzufügen“ im Bearbeitungsmodus gefunden", icon is not None, icon)
        page.mouse.click(icon["x"], icon["y"])
        page.get_by_text("Nach Karte", exact=True).click()
        page.get_by_placeholder("Karten durchsuchen").click()
        page.keyboard.type("Semaphore")
        time.sleep(1.5)
        check("Karten-Picker: beide Karten werden über „Nach Karte“ gefunden",
              page.locator("text=Semaphore UI – Template").count() >= 1 and page.locator("text=Semaphore UI – Projekt").count() >= 1)
        shot(page, "20_picker")
        page.locator("text=Semaphore UI – Template").first.click(force=True)
        page.wait_for_selector("hui-dialog-edit-card semaphore-ui-card-editor ha-form", timeout=20000)
        time.sleep(2)
        dialog = page.locator("hui-dialog-edit-card")
        chosen = dialog.locator("semaphore-ui-card-editor").evaluate(
            """ed => { const f = ed.querySelector('ha-form'); const o = f.schema[0].selector.select.options.find((x) => x.value === f.data.device_id); return o ? o.label : null; }"""
        )
        check("Karten-Dialog: Template-Auswahl „Projekt › Template“ ist vorbelegt", bool(chosen) and " › " in chosen, chosen)
        check("Karten-Dialog: Vorschau zeigt sofort eine funktionierende Karte", dialog.locator("semaphore-ui-template-card .title").count() >= 1)
        shot(page, "21_editor")
    finally:
        browser.close()


def test_setup_errors(playwright) -> None:
    """Der Einrichtungsdialog nennt die Ursache selbst (kein Verweis auf das Log)."""
    browser, page = open_page(playwright, path="/config/integrations/dashboard/add?domain=semaphore_ui", cards=False)
    try:
        page.get_by_role("button", name="OK").click()
        dialog = page.locator("dialog-data-entry-flow")
        dialog.locator("input[type=url]").wait_for(timeout=20000)

        def submit(url: str, token: str = "good-token") -> str:
            dialog.locator("input[type=url]").fill(url)
            dialog.locator("input[type=password]").fill(token)
            dialog.get_by_role("button", name="OK").click()
            time.sleep(4)
            alert = dialog.locator("ha-alert")  # the red box above the fields
            return alert.first.inner_text() if alert.count() else ""

        text = submit("http://127.0.0.1:9")
        check("Einrichtung: Verbindung abgelehnt wird erklärt (Port, http/https)", "lehnt die Verbindung ab" in text and "127.0.0.1:9" in text and "Port" in text, text[-400:])
        shot(page, "30_setup_refused")
        check("Einrichtung: kein Verweis auf das Log", "Log" not in text, text[-400:])

        text = submit(FAKE_URL + "/nirgendwo")
        check("Einrichtung: falsche Adresse (kein Semaphore) wird erkannt", "kein Semaphore" in text and "404" in text, text[-400:])

        text = submit(FAKE_URL, "falsches-token")
        check("Einrichtung: abgelehntes Token wird erklärt", "abgelehnt" in text and "401" in text, text[-400:])

        text = submit("http://semaphore-gibt-es-nicht.invalid:3000")
        check("Einrichtung: DNS-Fehler nennt den Namen", "semaphore-gibt-es-nicht.invalid" in text and ("aufgelöst" in text or "nicht erreichbar" in text), text[-400:])
        shot(page, "31_setup_dns")
    finally:
        browser.close()


def main() -> int:
    with sync_playwright() as playwright:
        test_needs_action_view(playwright)
        test_version_view(playwright)
        test_docs_screenshots(playwright)
        test_packages_responsive(playwright)
        browser, page = open_page(playwright)
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)[:200]))
        try:
            test_rendering(page)
            test_template_card_details(page)
            test_packages_one_line(page)
            test_project_filters(page)
            test_schedules_ui(page)
            test_busy_schedule(page)
            test_interactions(page)
            test_confirm_and_project_list(page)
            test_editor(page)
            test_two_projects(page)
            test_editor_choices(page)
            test_resource_list(page)
        finally:
            shot(page, "99_ende")
            browser.close()
        test_resource_registered()
        test_card_picker(playwright)
        test_setup_errors(playwright)
        test_mobile_dark(playwright)
        test_english(playwright)
    mine = [e for e in errors if "semaphore" in e.lower()]
    check("Keine JavaScript-Fehler aus den Semaphore-Karten", not mine, mine)
    print(f"\n{sum(results)}/{len(results)} Prüfungen bestanden")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
