/**
 * Semaphore UI cards for Home Assistant (shipped with the semaphore_ui integration).
 *
 *   custom:semaphore-ui-template-card   one template: status, start / dry run / stop,
 *                                       last run, duration, failure reason, "needs action"
 *                                       (pending updates reported by the playbook), survey inputs
 *   custom:semaphore-ui-project-card    the whole project: availability, update, counters,
 *                                       last task and all templates with quick start
 *
 * Both are found by `device_id`; the entities of the device are recognised by their
 * translation key, so nothing has to be configured by hand. Plain JavaScript, no build step.
 */
const SEMAPHORE_CARD_VERSION = "0.6.0";
const SEMAPHORE_DOMAIN = "semaphore_ui";

const TEXTS = {
  de: {
    start: "Starten",
    dry_run: "Testlauf",
    dry_run_hint: "Der letzte Lauf war ein Testlauf (es wurde nichts verändert)",
    stop: "Stoppen",
    last_run: "Letzter Lauf",
    duration: "Dauer",
    never: "Noch nie ausgeführt",
    running_since: "Gestartet",
    error: "Fehler",
    task: "Task",
    host: "Host",
    parameters: "Parameter",
    open: "In Semaphore öffnen",
    confirm: "Wirklich starten?",
    already_running: "Läuft bereits – erst abwarten oder stoppen",
    yes: "Ja",
    no: "Nein",
    offline: "Semaphore nicht erreichbar",
    update: "Update verfügbar",
    running_n: "Laufend",
    failed_n: "Mit Fehler",
    templates_n: "Templates",
    action_n: "Handlungsbedarf",
    checked: "Geprüft",
    reboot_short: "Neustart",
    more_n: "+{n} weitere",
    updates_n: "{n} Updates",
    update_1: "1 Update",
    pkgs_omitted: "{n} weitere Pakete nicht aufgelistet",
    host_ok: "aktuell",
    host_action: "Handlungsbedarf",
    disk_free: "frei",
    disk_used: "belegt",
    disk_need: "Updates brauchen",
    less: "weniger",
    show_all: "Alle Pakete anzeigen",
    show_less: "Weniger Pakete anzeigen",
    nothing_needed: "Gerade ist nichts zu tun.",
    none_running: "Gerade läuft nichts.",
    none_failed: "Kein Template mit Fehler.",
    none_action: "Kein Template mit Handlungsbedarf.",
    filter_hint: "Anzeige filtern – nochmal antippen zeigt alle",
    integration: "Integration",
    integration_update: "Integration-Update",
    last_success: "Zuletzt erfolgreich",
    next_run: "Nächster Lauf",
    schedules: "Zeitpläne",
    schedule_off: "aus",
    busy: "Wird ausgeführt …",
    schedule_once: "einmalig",
    schedule_next: "nächster Lauf",
    schedule_tz: "Zeitzone",
    schedule_switch: "Zeitplan {name} ein- oder ausschalten",
    last_task: "Zuletzt gelaufen",
    no_templates: "Keine Templates gefunden",
    choose_device_t: "Bitte im Karten-Editor das Template wählen (Eintrag „Projekt › Template“).",
    choose_device_p: "Bitte im Karten-Editor das Projekt wählen (Eintrag „Semaphore – Projektname“).",
    device_missing: "Gerät nicht gefunden – wurde die Integration entfernt?",
    wrong_device: "Das ist kein passendes Semaphore-Gerät.",
    required: "Pflichtfeld",
    select_placeholder: "– wählen –",
    status: {
      never_run: "Noch nie ausgeführt",
      waiting: "Wartet",
      starting: "Startet",
      waiting_confirmation: "Wartet auf Bestätigung",
      confirmed: "Bestätigt",
      running: "Läuft",
      stopping: "Wird gestoppt",
      success: "Erfolgreich",
      error: "Fehler",
      stopped: "Abgebrochen",
      rejected: "Abgelehnt",
    },
    ed: {
      device_id_t: "Template",
      device_id_p: "Projekt",
      help_device_t: "Jedes Template aus Semaphore ist ein eigenes Gerät. Angezeigt wird „Projekt › Template“.",
      help_device_p: "Jedes Semaphore-Projekt ist ein eigenes Gerät („Semaphore – Projektname“). Die Karte zeigt alle Templates dieses Projekts.",
      no_devices: "Es gibt noch keine Semaphore-Geräte. Bitte zuerst unter Einstellungen → Geräte & Dienste die Integration „Semaphore UI“ einrichten.",
      unknown_device: "(unbekanntes Gerät)",
      name: "Name (optional)",
      show_survey: "Eingabefelder (Survey-Variablen) zeigen",
      show_details: "Fehlergrund und Parameter zeigen",
      confirm_start: "Start bestätigen lassen",
      sort: "Sortierung der Templates",
      sort_name: "Name",
      sort_status: "Status (Laufend/Fehler zuerst)",
      sort_last_run: "Letzter Lauf",
      show_never_run: "Templates ohne Lauf zeigen",
      show_start: "Start-Knopf in der Liste zeigen",
      only_needed: "Nur Templates mit Handlungsbedarf, Fehler oder laufendem Lauf zeigen",
      show_version: "Semaphore-Version anzeigen",
      show_integration_version: "Version der Integration anzeigen",
      hacs_update_entity: "Update-Entität der Integration (HACS), optional",
      show_schedules: "Zeitpläne anzeigen",
    },
  },
  en: {
    start: "Start",
    dry_run: "Dry run",
    dry_run_hint: "The last run was a dry run (nothing was changed)",
    stop: "Stop",
    last_run: "Last run",
    duration: "Duration",
    never: "Never run",
    running_since: "Started",
    error: "Error",
    task: "Task",
    host: "Host",
    parameters: "Parameters",
    open: "Open in Semaphore",
    confirm: "Really start?",
    already_running: "Already running – wait for it or stop it first",
    yes: "Yes",
    no: "No",
    offline: "Semaphore not reachable",
    update: "Update available",
    running_n: "Running",
    failed_n: "Failed",
    templates_n: "Templates",
    action_n: "Needs action",
    checked: "Checked",
    reboot_short: "reboot",
    more_n: "+{n} more",
    updates_n: "{n} updates",
    update_1: "1 update",
    pkgs_omitted: "{n} more packages not listed",
    host_ok: "up to date",
    host_action: "action needed",
    disk_free: "free",
    disk_used: "used",
    disk_need: "updates need",
    less: "less",
    show_all: "Show all packages",
    show_less: "Show fewer packages",
    nothing_needed: "Nothing to do right now.",
    none_running: "Nothing is running.",
    none_failed: "No template with an error.",
    none_action: "No template needs action.",
    filter_hint: "Filter the list - tap again to show all",
    integration: "Integration",
    integration_update: "Integration update",
    last_success: "Last success",
    next_run: "Next run",
    schedules: "Schedules",
    schedule_off: "off",
    busy: "Working …",
    schedule_once: "once",
    schedule_next: "next run",
    schedule_tz: "Time zone",
    schedule_switch: "Switch schedule {name} on or off",
    last_task: "Last run",
    no_templates: "No templates found",
    choose_device_t: "Please choose the template in the card editor (entry \"Project › Template\").",
    choose_device_p: "Please choose the project in the card editor (entry \"Semaphore – project name\").",
    device_missing: "Device not found - was the integration removed?",
    wrong_device: "This is not a suitable Semaphore device.",
    required: "Required",
    select_placeholder: "- choose -",
    status: {
      never_run: "Never run",
      waiting: "Waiting",
      starting: "Starting",
      waiting_confirmation: "Waiting for confirmation",
      confirmed: "Confirmed",
      running: "Running",
      stopping: "Stopping",
      success: "Success",
      error: "Error",
      stopped: "Stopped",
      rejected: "Rejected",
    },
    ed: {
      device_id_t: "Template",
      device_id_p: "Project",
      help_device_t: "Every template of Semaphore is its own device. Shown as \"Project › Template\".",
      help_device_p: "Every Semaphore project is its own device (\"Semaphore – project name\"). The card shows all templates of this project.",
      no_devices: "There are no Semaphore devices yet. Please set up the \"Semaphore UI\" integration first (Settings → Devices & services).",
      unknown_device: "(unknown device)",
      name: "Name (optional)",
      show_survey: "Show input fields (survey variables)",
      show_details: "Show failure reason and parameters",
      confirm_start: "Ask for confirmation before starting",
      sort: "Sort templates by",
      sort_name: "Name",
      sort_status: "Status (running/failed first)",
      sort_last_run: "Last run",
      show_never_run: "Show templates that never ran",
      show_start: "Show start button in the list",
      only_needed: "Show only templates that need action, failed or are running",
      show_version: "Show the Semaphore version",
      show_integration_version: "Show the version of the integration",
      hacs_update_entity: "Update entity of the integration (HACS), optional",
      show_schedules: "Show schedules",
    },
  },
};

const STATUS_STYLE = {
  success: { icon: "mdi:check-circle", color: "var(--success-color, #43a047)" },
  error: { icon: "mdi:alert-circle", color: "var(--error-color, #db4437)" },
  running: { icon: "mdi:play-circle", color: "var(--info-color, #039be5)", pulse: true },
  starting: { icon: "mdi:rocket-launch", color: "var(--info-color, #039be5)", pulse: true },
  stopping: { icon: "mdi:stop-circle-outline", color: "var(--warning-color, #ffa600)", pulse: true },
  waiting: { icon: "mdi:timer-sand", color: "var(--warning-color, #ffa600)" },
  confirmed: { icon: "mdi:check", color: "var(--warning-color, #ffa600)" },
  waiting_confirmation: { icon: "mdi:account-clock", color: "var(--warning-color, #ffa600)" },
  stopped: { icon: "mdi:stop-circle", color: "var(--warning-color, #ffa600)" },
  rejected: { icon: "mdi:close-circle", color: "var(--warning-color, #ffa600)" },
  never_run: { icon: "mdi:minus-circle-outline", color: "var(--disabled-text-color, #9e9e9e)" },
};
const ACTIVE = new Set(["waiting", "starting", "waiting_confirmation", "confirmed", "running", "stopping"]);
const SORT_RANK = { running: 0, starting: 0, stopping: 0, waiting: 1, waiting_confirmation: 1, confirmed: 1, error: 2, never_run: 4 };

/* ------------------------------------------------------------------ helpers */
const esc = (value) =>
  String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

const langOf = (hass) => ((hass && (hass.locale?.language || hass.language)) || "en").toLowerCase().startsWith("de") ? "de" : "en";
const tx = (hass) => TEXTS[langOf(hass)];

function fmtDuration(seconds, hass) {
  if (seconds === null || seconds === undefined || isNaN(seconds)) return "";
  const s = Math.max(0, Math.round(seconds));
  const lang = langOf(hass);
  const [h, m, sec] = [Math.floor(s / 3600), Math.floor((s % 3600) / 60), s % 60];
  const unit = lang === "de" ? { h: "Std", m: "Min", s: "s" } : { h: "h", m: "min", s: "s" };
  if (h) return `${h} ${unit.h} ${String(m).padStart(2, "0")} ${unit.m}`;
  if (m) return sec ? `${m} ${unit.m} ${String(sec).padStart(2, "0")} ${unit.s}` : `${m} ${unit.m}`;
  return `${sec} ${unit.s}`;
}

function fmtDate(iso, hass) {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d)) return "";
  return new Intl.DateTimeFormat(hass.locale?.language || langOf(hass), { dateStyle: "short", timeStyle: "short" }).format(d);
}

function fmtRelative(iso, hass) {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d)) return "";
  const diff = (d.getTime() - Date.now()) / 1000;
  const rtf = new Intl.RelativeTimeFormat(hass.locale?.language || langOf(hass), { numeric: "auto" });
  const abs = Math.abs(diff);
  if (abs < 60) return rtf.format(Math.round(diff), "second");
  if (abs < 3600) return rtf.format(Math.round(diff / 60), "minute");
  if (abs < 86400) return rtf.format(Math.round(diff / 3600), "hour");
  if (abs < 86400 * 30) return rtf.format(Math.round(diff / 86400), "day");
  return fmtDate(iso, hass);
}

/** Entities of one device, indexed as "domain:translation_key" (+ the survey inputs). */
function entitiesOfDevice(hass, deviceId) {
  const byKey = {};
  const survey = [];
  for (const [entityId, ent] of Object.entries(hass.entities || {})) {
    if (ent.device_id !== deviceId || ent.platform !== SEMAPHORE_DOMAIN) continue;
    const domain = entityId.split(".")[0];
    if (ent.translation_key) {
      byKey[`${domain}:${ent.translation_key}`] = entityId;
    } else if (["text", "number", "select"].includes(domain)) {
      survey.push(entityId);
    }
  }
  survey.sort((a, b) => (hass.states[a]?.attributes.order ?? 0) - (hass.states[b]?.attributes.order ?? 0) || a.localeCompare(b));
  return { byKey, survey };
}

function projectDevices(hass) {
  return Object.values(hass.devices || {}).filter(
    (d) => (d.identifiers || []).some((i) => i[0] === SEMAPHORE_DOMAIN) && d.model === "Project"
  );
}
function templateDevicesOf(hass, projectDeviceId) {
  const project = hass.devices?.[projectDeviceId];
  if (!project) return [];
  const entries = new Set(project.config_entries || []);
  return Object.values(hass.devices || {}).filter(
    (d) => d.model === "Template" && (d.config_entries || []).some((e) => entries.has(e)) && (d.identifiers || []).some((i) => i[0] === SEMAPHORE_DOMAIN)
  );
}
const deviceName = (d) => d?.name_by_user || d?.name || "";

/** All devices of this integration with the given model ("Project" or "Template"). */
function semaphoreDevices(hass, model) {
  return Object.values(hass.devices || {}).filter(
    (d) => d.model === model && (d.identifiers || []).some((i) => i[0] === SEMAPHORE_DOMAIN)
  );
}
/** Name of the Semaphore project a template (or project) device belongs to. */
function projectNameOf(hass, device) {
  const entries = new Set(device?.config_entries || []);
  const project = semaphoreDevices(hass, "Project").find((p) => (p.config_entries || []).some((e) => entries.has(e)));
  return project ? deviceName(project).replace(/^Semaphore\s*[–-]\s*/, "") : "";
}
/** Choices of the card editor: "Homelab › Host-Update" (templates) or "Semaphore – Homelab" (projects). */
function deviceOptions(hass, model) {
  const options = semaphoreDevices(hass, model).map((d) => {
    const project = model === "Template" ? projectNameOf(hass, d) : "";
    return { value: d.id, label: project ? `${project} › ${deviceName(d)}` : deviceName(d) };
  });
  return options.sort((a, b) => a.label.localeCompare(b.label, undefined, { numeric: true, sensitivity: "base" }));
}

const STYLE = `
  :host { display: block; }
  ha-card { padding: 16px; overflow: hidden; }
  .head { display: flex; align-items: center; gap: 12px; cursor: pointer; }
  .head .ic { --mdc-icon-size: 32px; flex: none; }
  .head .titles { flex: 1; min-width: 0; }
  .head .chips { display: flex; flex-direction: column; align-items: flex-end; gap: 4px; flex: none; }
  .title { font-size: 1.2em; font-weight: 500; line-height: 1.25; overflow: hidden; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow-wrap: anywhere; }
  .sub { color: var(--secondary-text-color); font-size: 0.9em; }
  .chip { display: inline-flex; align-items: center; gap: 4px; padding: 2px 10px; border-radius: 12px; font-size: 0.85em; font-weight: 500; white-space: nowrap;
          background: color-mix(in srgb, var(--chip-color, var(--primary-color)) 18%, transparent); color: var(--chip-color, var(--primary-color)); }
  .chip ha-icon { --mdc-icon-size: 16px; }
  .chip.dry { flex-direction: column; align-items: flex-start; gap: 0; padding: 2px 10px 3px; border: 1px dashed color-mix(in srgb, var(--chip-color) 55%, transparent);
              background: color-mix(in srgb, var(--chip-color) 8%, transparent); color: color-mix(in srgb, var(--chip-color) 80%, var(--secondary-text-color)); }
  .chip.dry .dry-l { font-size: 0.75em; font-weight: 600; letter-spacing: 0.04em; text-transform: uppercase; opacity: 0.85; line-height: 1.3; }
  .chip.dry .dry-s { display: inline-flex; align-items: center; gap: 4px; }
  .pulse { animation: pulse 1.6s ease-in-out infinite; }
  @keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.45; } }
  @media (prefers-reduced-motion: reduce) { .pulse { animation: none; } }
  [data-action="more-info"]:focus-visible { outline: 2px solid var(--primary-color); outline-offset: 2px; border-radius: 8px; }
  .rows { margin-top: 12px; display: grid; grid-template-columns: minmax(0, 1fr); gap: 6px; }
  .row { display: flex; justify-content: space-between; gap: 12px; font-size: 0.95em; }
  .row .k { color: var(--secondary-text-color); flex: none; }
  .row .v { text-align: right; min-width: 0; overflow-wrap: anywhere; }
  .row.click { cursor: pointer; margin: 0 -6px; padding: 2px 6px; border-radius: 6px; }
  .row.click:hover { background: color-mix(in srgb, var(--primary-text-color) 6%, transparent); }
  .errbox[data-action="more-info"] { cursor: pointer; }
  .notes { margin-top: 6px; display: grid; gap: 4px; }
  .note { display: flex; gap: 6px; align-items: flex-start; font-size: 0.85em; color: var(--secondary-text-color); overflow-wrap: anywhere; }
  .note ha-icon { --mdc-icon-size: 16px; flex: none; margin-top: 1px; }
  .hosts { margin-top: 8px; display: grid; }
  .host { padding: 8px 0; min-width: 0; }
  .host + .host { border-top: 1px solid color-mix(in srgb, var(--warning-color, #ffa600) 45%, var(--divider-color, #ccc)); }
  .needbox.off .host + .host { border-top-color: var(--divider-color, #ccc); }
  .host:first-child { padding-top: 2px; }
  .host:last-child { padding-bottom: 0; }
  .host .hh { display: flex; flex-wrap: wrap; gap: 4px 10px; align-items: baseline; }
  .host .hn { font-weight: 600; color: var(--primary-text-color); }
  .host .hs { color: var(--secondary-text-color); font-size: 0.9em; }
  .host .hs.need { color: var(--primary-text-color); }
  .host .disks, .host .pkgs, .host .notes { margin-top: 4px; }
  .disks { margin-top: 6px; display: grid; gap: 4px; }
  .disk { display: grid; grid-template-columns: 16px minmax(0, 1fr); column-gap: 6px; row-gap: 3px; align-items: start; font-size: 0.85em; color: var(--secondary-text-color); overflow-wrap: anywhere; }
  .needbox .disk ha-icon { --mdc-icon-size: 16px; margin-top: 1px; color: var(--secondary-text-color); }
  .disk .dtext { min-width: 0; }
  .disk .bar { grid-column: 2; width: 100%; max-width: 160px; height: 6px; border-radius: 3px; background: var(--divider-color, #e0e0e0); overflow: hidden; }
  .disk .bar i { display: block; height: 100%; background: var(--success-color, #43a047); }
  .disk .bar.warn i { background: var(--warning-color, #ffa600); }
  .disk .bar.crit i { background: var(--error-color, #db4437); }
  .errbox { margin-top: 12px; padding: 8px 12px; border-radius: 8px; font-size: 0.9em; overflow-wrap: anywhere;
            background: color-mix(in srgb, var(--error-color, #db4437) 12%, transparent); border-left: 4px solid var(--error-color, #db4437); }
  .errbox .meta { color: var(--secondary-text-color); margin-top: 4px; }
  .needbox { margin-top: 12px; display: flex; gap: 10px; align-items: flex-start; padding: 8px 12px; border-radius: 8px; cursor: pointer; overflow-wrap: anywhere;
             background: color-mix(in srgb, var(--warning-color, #ffa600) 14%, transparent); border-left: 4px solid var(--warning-color, #ffa600); }
  .needbox.off { background: transparent; border-left-color: var(--success-color, #43a047); color: var(--secondary-text-color); }
  .needbox ha-icon { --mdc-icon-size: 22px; flex: none; color: var(--warning-color, #ffa600); }
  .needbox.off ha-icon { color: var(--success-color, #43a047); }
  .needbox .t { min-width: 0; }
  .needbox .what { font-weight: 500; }
  .needbox .meta { color: var(--secondary-text-color); font-size: 0.9em; margin-top: 2px; }
  .needbox:focus-visible { outline: 2px solid var(--primary-color); outline-offset: 2px; }
  /* packages: ONE line while folded (the script hides what does not fit and writes "+n more"), all of them wrapped when open */
  .pkgs { margin-top: 6px; display: flex; flex-wrap: nowrap; gap: 4px; overflow: hidden; }
  .pkgs.open { flex-wrap: wrap; }
  .pkg { flex: none; font-size: 0.8em; padding: 1px 8px; border-radius: 10px; background: var(--secondary-background-color); max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .pkgs.open .pkg, .pkgs.one .pkg:first-child { flex: 0 1 auto; min-width: 0; } /* "one": only the first name is left - it may shrink to make room for "+n more" */
  .pkg[hidden] { display: none; }
  button.pkg { font: inherit; font-size: 0.8em; border: 0; margin: 0; color: var(--primary-color); font-weight: 500; cursor: pointer;
               background: color-mix(in srgb, var(--primary-color) 14%, transparent); flex: none; }
  button.pkg:hover { background: color-mix(in srgb, var(--primary-color) 24%, transparent); }
  button.pkg:focus-visible { outline: 2px solid var(--primary-color); outline-offset: 1px; }
  .item .need { --mdc-icon-size: 16px; margin-left: 6px; vertical-align: text-bottom; color: var(--warning-color, #ffa600); }
  .params { margin-top: 8px; display: flex; flex-wrap: wrap; gap: 6px; }
  .param { font-size: 0.8em; padding: 1px 8px; border-radius: 10px; background: var(--secondary-background-color); }
  .survey { margin-top: 14px; display: grid; gap: 10px; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); }
  .survey label { display: grid; gap: 4px; font-size: 0.85em; color: var(--secondary-text-color); }
  .survey .req { color: var(--error-color, #db4437); }
  .survey input, .survey select { font: inherit; color: var(--primary-text-color); background: var(--card-background-color, #fff);
            border: 1px solid var(--divider-color); border-radius: 8px; padding: 8px 10px; min-width: 0; }
  .survey input:focus, .survey select:focus { outline: 2px solid var(--primary-color); outline-offset: -1px; }
  .actions { margin-top: 14px; display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
  button.btn { font: inherit; display: inline-flex; align-items: center; gap: 6px; padding: 8px 14px; border-radius: 18px; border: 1px solid var(--divider-color);
               background: var(--card-background-color, #fff); color: var(--primary-text-color); cursor: pointer; min-height: 36px; }
  button.btn.primary { background: var(--primary-color); color: var(--text-primary-color, #fff); border-color: transparent; }
  button.btn.danger { color: var(--error-color, #db4437); }
  button.btn:disabled { opacity: 0.45; cursor: default; }
  button.btn ha-icon { --mdc-icon-size: 18px; }
  button.btn:focus-visible { outline: 2px solid var(--primary-color); outline-offset: 2px; }
  a.link { margin-left: auto; color: var(--secondary-text-color); display: inline-flex; align-items: center; gap: 4px; font-size: 0.85em; text-decoration: none; }
  a.link ha-icon { --mdc-icon-size: 16px; }
  .msg { margin-top: 10px; font-size: 0.9em; color: var(--error-color, #db4437); overflow-wrap: anywhere; }
  .notice { padding: 16px; color: var(--secondary-text-color); }
  /* project card */
  .stats { margin-top: 12px; display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; text-align: center; }
  .stat { padding: 8px 4px; border-radius: 10px; background: color-mix(in srgb, var(--primary-text-color) 6%, transparent); cursor: pointer; border: 2px solid transparent; }
  .stat:hover { background: color-mix(in srgb, var(--primary-text-color) 10%, transparent); }
  .stat.sel { border-color: var(--primary-color); }
  .stat:focus-visible { outline: 2px solid var(--primary-color); outline-offset: 2px; }
  .stat .n { font-size: 1.4em; font-weight: 500; line-height: 1.2; }
  .stat .l { font-size: 0.8em; color: var(--secondary-text-color); }
  .stats.four { grid-template-columns: repeat(4, 1fr); }
  .stat.warn .n { color: var(--warning-color, #ffa600); }
  .stat.bad .n { color: var(--error-color, #db4437); }
  .stat.busy .n { color: var(--info-color, #039be5); }
  .last { margin-top: 12px; display: flex; gap: 10px; align-items: center; padding: 8px 12px; border-radius: 10px; background: color-mix(in srgb, var(--primary-text-color) 6%, transparent); cursor: pointer; }
  .last ha-icon { --mdc-icon-size: 24px; flex: none; }
  .last .t { min-width: 0; }
  .list { margin-top: 12px; display: grid; grid-template-columns: minmax(0, 1fr); }
  .item { display: flex; align-items: center; gap: 10px; padding: 8px 0; border-top: 1px solid var(--divider-color); }
  .item:first-child { border-top: none; }
  .item .ic { --mdc-icon-size: 24px; flex: none; }
  .item .ic.dry { --mdc-icon-size: 20px; padding: 2px; border: 1.5px dashed currentColor; border-radius: 50%; opacity: 0.6; }
  .item .main { flex: 1; min-width: 0; cursor: pointer; }
  .item .name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .item .sub { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .sched { margin-top: 12px; border-top: 1px solid var(--divider-color); padding-top: 6px; }
  .sched-title { color: var(--secondary-text-color); font-size: 0.85em; font-weight: 500; margin: 4px 0 2px; }
  .sched-row { display: flex; align-items: center; gap: 12px; padding: 5px 0; }
  .sched-row .main { flex: 1; min-width: 0; cursor: pointer; }
  .sched-row .name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .sched-row .sub { overflow-wrap: anywhere; }  /* template, cron and next run may take two lines */
  .tgl { flex: none; position: relative; width: 38px; height: 22px; border-radius: 11px; border: 0; padding: 0; cursor: pointer;
         background: var(--switch-unchecked-track-color, var(--disabled-color, #9e9e9e)); transition: background 0.15s; }
  .tgl .knob { position: absolute; top: 3px; left: 3px; width: 16px; height: 16px; border-radius: 50%; background: #fff;
               box-shadow: 0 1px 2px rgba(0, 0, 0, 0.35); transition: left 0.15s; }
  .tgl.on { background: var(--switch-checked-track-color, var(--primary-color)); }
  .tgl.on .knob { left: 19px; }
  .tgl:disabled { opacity: 0.45; cursor: default; }
  .tgl:focus-visible { outline: 2px solid var(--primary-color); outline-offset: 2px; }
  /* working: the click arrived, Semaphore has not answered yet */
  .spin { flex: none; display: inline-block; width: 18px; height: 18px; box-sizing: border-box; border-radius: 50%;
          border: 2px solid color-mix(in srgb, currentColor 25%, transparent); border-top-color: currentColor; animation: spin 0.8s linear infinite; }
  button.icon .spin { margin: 2px; width: 18px; height: 18px; }
  .tgl.busy { cursor: progress; }
  .tgl.busy .knob::after { content: ""; position: absolute; inset: 2px; border-radius: 50%; box-sizing: border-box;
          border: 2px solid color-mix(in srgb, var(--primary-color) 25%, transparent); border-top-color: var(--primary-color); animation: spin 0.8s linear infinite; }
  button.busy { cursor: progress; }
  @keyframes spin { to { transform: rotate(360deg); } }
  @media (prefers-reduced-motion: reduce) { .spin, .tgl.busy .knob::after { animation-duration: 3s; } }
  button.icon { all: unset; cursor: pointer; display: inline-flex; padding: 6px; border-radius: 50%; color: var(--primary-text-color); }
  button.icon:hover, button.icon:focus-visible { background: var(--secondary-background-color); }
  button.icon:disabled { opacity: 0.35; cursor: default; }
  button.icon ha-icon { --mdc-icon-size: 22px; }
  .banner { margin-top: 12px; padding: 6px 12px; border-radius: 8px; font-size: 0.9em; display: flex; gap: 8px; align-items: center; }
  .banner.off { background: color-mix(in srgb, var(--error-color, #db4437) 14%, transparent); color: var(--error-color, #db4437); }
  .banner ha-icon { --mdc-icon-size: 18px; }
`;

class SemaphoreBaseCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._sig = "";
    this._message = "";
    this._confirmUntil = 0;
    this._busy = new Map(); // entity id -> target state, while its action runs (spinner, no second click)
    this._ticker = null;
    this.shadowRoot.addEventListener("click", (ev) => this._onClick(ev));
    this.shadowRoot.addEventListener("change", (ev) => this._onChange(ev));
    // the clickable header areas are no <button>s: make them work with Enter / Space, too
    this.shadowRoot.addEventListener("keydown", (ev) => {
      if ((ev.key === "Enter" || ev.key === " ") && ev.target.matches && ev.target.matches('[data-action="more-info"], [data-action="filter"]')) {
        ev.preventDefault();
        this._onClick(ev);
      }
    });
    this.shadowRoot.addEventListener("focusout", () => {
      // render the update that was held back - but not while focus just moved to another field
      if (this._renderPending) setTimeout(() => this._maybeRender(false), 0);
    });
  }

  setConfig(config) {
    if (!config || typeof config !== "object") throw new Error("Invalid configuration");
    this._config = { ...this.constructor.defaults, ...config };
    this._sig = "";
    if (this._hass) this._update();
  }

  set hass(hass) {
    this._hass = hass;
    this._update();
  }

  connectedCallback() {
    this._startTicker();
    this._observeSize();
  }
  disconnectedCallback() {
    clearInterval(this._ticker);
    this._ticker = null;
    if (this._ro) this._ro.disconnect();
    this._ro = null;
  }
  _startTicker() {
    if (this._ticker) return;
    this._ticker = setInterval(() => this._tick(), 1000);
  }
  _tick() {}

  getCardSize() {
    return 4;
  }
  getGridOptions() {
    return { columns: 12, min_columns: 6 };
  }

  _fire(type, detail) {
    this.dispatchEvent(new CustomEvent(type, { detail, bubbles: true, composed: true }));
  }
  _moreInfo(entityId) {
    if (entityId) this._fire("hass-more-info", { entityId });
  }
  _state(entityId) {
    return entityId ? this._hass.states[entityId] : undefined;
  }
  _val(entityId) {
    const s = this._state(entityId);
    return s ? s.state : undefined;
  }
  _setMessage(text) {
    this._message = text;
    clearTimeout(this._msgTimer);
    this._msgTimer = setTimeout(() => {
      this._message = "";
      this._sig = "";
      this._update();
    }, 9000);
    this._sig = "";
    this._update();
  }
  async _call(domain, service, data) {
    try {
      await this._hass.callService(domain, service, data);
      return true;
    } catch (err) {
      // Home Assistant shows its own toast for a failed action; the card adds the reason inline.
      this._setMessage(await this._errorText(err));
      return false;
    }
  }

  /** Runs ``fn`` with a spinner on the control of ``entity``; a second click meanwhile is ignored. */
  async _busyRun(entity, target, fn) {
    if (this._busy.has(entity)) return false;
    this._busy.set(entity, target);
    this._redraw();
    try {
      return await fn();
    } finally {
      this._busy.delete(entity);
      this._redraw();
    }
  }
  _redraw() {
    this._sig = "";
    this._update();
  }
  /** Icon of a button - or a spinner while its action runs. */
  _ico(entity, icon, style = "") {
    if (this._busy.has(entity)) return `<span class="spin" role="status" aria-label="${esc(tx(this._hass).busy)}"></span>`;
    return `<ha-icon icon="${icon}"${style ? ` style="${style}"` : ""}></ha-icon>`;
  }
  _busyAttrs(entity) {
    return this._busy.has(entity) ? ' aria-busy="true"' : "";
  }

  /** Localised text of a failed action (the frontend has to load the integration's translations first). */
  async _errorText(err) {
    const e = err && err.error ? err.error : err || {};
    if (e.translation_key && e.translation_domain && this._hass.loadBackendTranslation) {
      try {
        const localize = await this._hass.loadBackendTranslation("exceptions", e.translation_domain);
        const args = [];
        for (const [k, v] of Object.entries(e.translation_placeholders || {})) args.push(k, String(v));
        const text = localize(`component.${e.translation_domain}.exceptions.${e.translation_key}.message`, ...args);
        if (text) return text;
      } catch (_) {
        /* fall back to the English message */
      }
    }
    return e.message || String(err);
  }

  _update() {
    if (!this._hass || !this._config) return;
    this._maybeRender(false);
  }
  _maybeRender(force) {
    const active = this.shadowRoot.activeElement;
    if (!force && active && ["INPUT", "SELECT"].includes(active.tagName)) {
      this._renderPending = true; // do not steal the focus while somebody types
      return;
    }
    const sig = this._signature();
    if (sig === this._sig && !force) return;
    this._sig = sig;
    this._renderPending = false;
    if (active && active.getAttribute && active.getAttribute("data-action") === "pkgs") this._focusPkgs = active.dataset.key || "";
    this.shadowRoot.innerHTML = `<style>${STYLE}</style>${this._html()}`;
    for (const el of this.shadowRoot.querySelectorAll('[data-action="more-info"], [data-action="filter"]')) {
      el.setAttribute("role", "button");
      el.setAttribute("tabindex", "0");
    }
    this._afterRender();
  }
  _afterRender() {}

  /** One schedule: a switch (turns it on/off in Semaphore) and "name / cron / next run". */
  _scheduleRow(item, T, hass, withTemplate) {
    const sw = item.entity_id ? this._state(item.entity_id) : null;
    const usable = !!sw && sw.state !== "unavailable";
    const busy = !!item.entity_id && this._busy.has(item.entity_id);
    const on = busy ? !!this._busy.get(item.entity_id) : !!item.active; // working: show where it is going
    const bits = [];
    if (withTemplate && item.template) bits.push(item.template);
    bits.push(item.type === "run_at" ? T.schedule_once : item.cron);
    if (!on) bits.push(T.schedule_off);
    else if (item.next_run) bits.push(`${T.schedule_next} ${fmtRelative(item.next_run, hass)}`);
    const text = bits.filter(Boolean).join(" · ");
    const when = on && item.next_run ? fmtDate(item.next_run, hass) : "";
    const label = T.schedule_switch.replace("{name}", item.name);
    return `<div class="sched-row">
      <button class="tgl${on ? " on" : ""}${busy ? " busy" : ""}" role="switch" aria-checked="${on}" aria-label="${esc(label)}" title="${esc(busy ? tx(hass).busy : label)}"${busy ? ' aria-busy="true"' : ""} data-action="schedule" data-entity="${esc(item.entity_id || "")}" ${usable ? "" : "disabled"}><span class="knob"></span></button>
      <div class="main"${item.entity_id ? ` data-action="more-info" data-entity="${esc(item.entity_id)}"` : ""}>
        <div class="name">${esc(item.name)}</div><div class="sub" title="${esc(when ? `${text} (${when})` : text)}">${esc(text)}</div>
      </div></div>`;
  }
  _toggleSchedule(entity) {
    if (!entity) return;
    const turnOn = this._val(entity) !== "on";
    return this._busyRun(entity, turnOn, () => this._call("switch", turnOn ? "turn_on" : "turn_off", { entity_id: entity }));
  }

  _chip(status, hass, dry = false) {
    const st = STATUS_STYLE[status] || STATUS_STYLE.never_run;
    const T = tx(hass);
    const label = esc(T.status[status] || status);
    // a dry run: two-part badge "Dry run / Successful" in lighter colours (it was only a test)
    if (dry) {
      return `<span class="chip dry ${st.pulse ? "pulse" : ""}" style="--chip-color:${st.color}" title="${esc(T.dry_run_hint)}"><span class="dry-l" data-dry="1">${esc(T.dry_run)}</span><span class="dry-s"><ha-icon icon="${st.icon}"></ha-icon>${label}</span></span>`;
    }
    return `<span class="chip ${st.pulse ? "pulse" : ""}" style="--chip-color:${st.color}"><ha-icon icon="${st.icon}"></ha-icon>${label}</span>`;
  }
}

/* ======================================================== template card */
class SemaphoreTemplateCard extends SemaphoreBaseCard {
  static get defaults() {
    return { show_survey: true, show_details: true, confirm_start: false, show_schedules: true };
  }
  static getConfigElement() {
    return document.createElement("semaphore-ui-card-editor");
  }
  static getStubConfig(hass) {
    const device = Object.values(hass.devices || {}).find(
      (d) => d.model === "Template" && (d.identifiers || []).some((i) => i[0] === SEMAPHORE_DOMAIN)
    );
    return { type: "custom:semaphore-ui-template-card", device_id: device ? device.id : "" };
  }
  getCardSize() {
    return 5;
  }

  _ents() {
    return entitiesOfDevice(this._hass, this._config.device_id);
  }
  _signature() {
    const c = this._config;
    if (!c.device_id) return "nodevice";
    const { byKey, survey } = this._ents();
    const ids = [...Object.values(byKey), ...survey];
    const parts = ids.map((id) => {
      const s = this._hass.states[id];
      return s ? `${id}=${s.state}|${s.state === "unavailable" ? "" : JSON.stringify(s.attributes)}` : `${id}=?`;
    });
    return [JSON.stringify(c), this._message, this._confirmUntil > Date.now(), langOf(this._hass), Math.floor(Date.now() / 60000), ...parts].join("\n");
  }

  _html() {
    const hass = this._hass;
    const T = tx(hass);
    const c = this._config;
    if (!c.device_id) return `<ha-card><div class="notice">${esc(T.choose_device_t)}</div></ha-card>`;
    const device = hass.devices?.[c.device_id];
    if (!device) return `<ha-card><div class="notice">${esc(T.device_missing)}</div></ha-card>`;
    const { byKey, survey } = this._ents();
    if (!byKey["sensor:status"]) return `<ha-card><div class="notice">${esc(T.wrong_device)}</div></ha-card>`;

    const status = this._val(byKey["sensor:status"]) || "never_run";
    const known = STATUS_STYLE[status] ? status : "never_run";
    const st = STATUS_STYLE[known];
    const summary = this._state(byKey["sensor:summary"]);
    const rep = (summary && summary.attributes) || {};
    const running = ACTIVE.has(status);
    const unavailable = this._val(byKey["sensor:status"]) === "unavailable";
    const startedIso = this._val(byKey["sensor:last_started"]);
    const durationRaw = this._val(byKey["sensor:last_duration"]);
    const duration = durationRaw && !isNaN(Number(durationRaw)) ? Number(durationRaw) : rep.duration_seconds;
    const title = c.name || deviceName(device);
    // with more than one project the name alone can be ambiguous: show where the template lives
    const projectName = projectDevices(hass).length > 1 ? projectNameOf(hass, device) || rep.project : "";
    const projectSub = projectName ? `<div class="sub">${esc(projectName)}</div>` : "";

    // A row opens the standard dialog (more-info) of the entity behind it - history, attributes, settings.
    const row = (label, valueHtml, entityId) =>
      `<div class="row${entityId ? " click" : ""}"${entityId ? ` data-action="more-info" data-entity="${entityId}"` : ""}><span class="k">${esc(label)}</span>${valueHtml}</div>`;
    const rows = [];
    if (status === "never_run") {
      rows.push(row(T.last_run, `<span class="v">${esc(T.never)}</span>`));
    } else {
      if (startedIso && startedIso !== "unknown" && startedIso !== "unavailable") {
        rows.push(
          row(running ? T.running_since : T.last_run, `<span class="v" title="${esc(fmtDate(startedIso, hass))}">${esc(fmtDate(startedIso, hass))} · ${esc(fmtRelative(startedIso, hass))}</span>`, byKey["sensor:last_started"])
        );
      }
      if (running && startedIso) {
        rows.push(row(T.duration, `<span class="v elapsed" data-since="${esc(startedIso)}"></span>`, byKey["sensor:last_duration"]));
      } else if (duration !== undefined && duration !== null && duration !== "") {
        rows.push(row(T.duration, `<span class="v">${esc(fmtDuration(duration, hass))}</span>`, byKey["sensor:last_duration"]));
      }
    }

    // Last success (interesting when the last run did not succeed) and the next scheduled run.
    const hasTime = (v) => !!v && v !== "unknown" && v !== "unavailable";
    const successIso = this._val(byKey["sensor:last_success"]);
    if (status !== "success" && hasTime(successIso)) {
      const dry = ((this._state(byKey["sensor:last_success"]) || {}).attributes || {}).dry_run;
      rows.push(
        row(T.last_success, `<span class="v" title="${esc(fmtDate(successIso, hass))}">${esc(fmtDate(successIso, hass))} · ${esc(fmtRelative(successIso, hass))}${dry ? ` (${esc(T.dry_run)})` : ""}</span>`, byKey["sensor:last_success"])
      );
    }
    const nextIso = this._val(byKey["sensor:next_run"]);
    if (hasTime(nextIso)) {
      rows.push(row(T.next_run, `<span class="v" title="${esc(fmtDate(nextIso, hass))}">${esc(fmtDate(nextIso, hass))} · ${esc(fmtRelative(nextIso, hass))}</span>`, byKey["sensor:next_run"]));
    }

    const needHtml = this._needBox(byKey["binary_sensor:needs_action"], T, hass);

    let details = "";
    if (c.show_details) {
      if (status === "error" && rep.error && rep.error.reason) {
        const meta = [rep.error.failed_task && `${T.task}: ${rep.error.failed_task}`, rep.error.host && `${T.host}: ${rep.error.host}`].filter(Boolean);
        const problemId = byKey["binary_sensor:problem"];
        details += `<div class="errbox"${problemId ? ` data-action="more-info" data-entity="${problemId}"` : ""}><div>${esc(rep.error.reason)}</div>${meta.length ? `<div class="meta">${meta.map(esc).join(" · ")}</div>` : ""}</div>`;
      }
      const params = rep.parameters && typeof rep.parameters === "object" ? Object.entries(rep.parameters) : [];
      if (params.length) {
        details += `<div class="params" title="${esc(T.parameters)}">${params.map(([k, v]) => `<span class="param">${esc(k)}=${esc(Array.isArray(v) ? v.join(",") : v)}</span>`).join("")}</div>`;
      }
    }

    let schedHtml = "";
    const schedItems = ((this._state(byKey["sensor:next_run"]) || {}).attributes || {}).schedules;
    if (c.show_schedules !== false && Array.isArray(schedItems) && schedItems.length) {
      schedHtml = `<div class="sched"><div class="sched-title">${esc(T.schedules)}</div>${schedItems.map((item) => this._scheduleRow(item, T, hass, false)).join("")}</div>`;
    }

    let surveyHtml = "";
    if (c.show_survey && survey.length) {
      surveyHtml = `<div class="survey">${survey.map((id) => this._surveyField(id, T)).join("")}</div>`;
    }

    const startId = byKey["button:start"];
    const dryId = byKey["button:dry_run"];
    const stopId = byKey["button:stop"];
    const can = (id) => id && this._val(id) !== "unavailable" && !unavailable;
    // A second start would be refused by the integration (or queued by Semaphore): show it as not possible.
    const runSensor = this._state(byKey["binary_sensor:running"]);
    const parallel = !!(runSensor && runSensor.attributes && runSensor.attributes.parallel_allowed);
    const locked = running && !parallel;
    const lockTitle = locked ? ` title="${esc(T.already_running)}"` : "";
    const confirming = this._confirmUntil > Date.now() && !locked;
    let startBtn = "";
    if (startId) {
      startBtn = confirming
        ? `<button class="btn primary${this._busy.has(startId) ? " busy" : ""}" data-action="confirm-yes" data-entity="${startId}"${this._busyAttrs(startId)}>${this._ico(startId, "mdi:check")}${esc(T.confirm)} ${esc(T.yes)}</button>
           <button class="btn" data-action="confirm-no">${esc(T.no)}</button>`
        : `<button class="btn primary${this._busy.has(startId) ? " busy" : ""}" data-action="start" data-entity="${startId}"${this._busyAttrs(startId)} ${can(startId) && !locked ? "" : "disabled"}${lockTitle}>${this._ico(startId, "mdi:play")}${esc(T.start)}</button>`;
    }
    const dryBtn = dryId && !confirming ? `<button class="btn${this._busy.has(dryId) ? " busy" : ""}" data-action="press" data-entity="${dryId}"${this._busyAttrs(dryId)} ${can(dryId) && !locked ? "" : "disabled"}${lockTitle}>${this._ico(dryId, "mdi:flask-outline")}${esc(T.dry_run)}</button>` : "";
    const stopBtn = stopId && running && !confirming ? `<button class="btn danger${this._busy.has(stopId) ? " busy" : ""}" data-action="press" data-entity="${stopId}"${this._busyAttrs(stopId)} ${can(stopId) ? "" : "disabled"}>${this._ico(stopId, "mdi:stop")}${esc(T.stop)}</button>` : "";
    const link = rep.url ? `<a class="link" href="${esc(rep.url)}" target="_blank" rel="noopener"><ha-icon icon="mdi:open-in-new"></ha-icon>${esc(T.open)}</a>` : "";

    return `<ha-card>
      <div class="head" data-action="more-info" data-entity="${byKey["sensor:status"]}">
        <ha-icon class="ic ${st.pulse ? "pulse" : ""}" icon="${st.icon}" style="color:${st.color}"></ha-icon>
        <div class="titles"><div class="title">${esc(title)}</div>${projectSub}</div>
        ${this._chip(known, hass, !!rep.dry_run && known !== "never_run")}
      </div>
      <div class="rows">${rows.join("")}</div>
      ${needHtml}
      ${details}
      ${schedHtml}
      ${surveyHtml}
      <div class="actions">${startBtn}${dryBtn}${stopBtn}${link}</div>
      ${this._message ? `<div class="msg" role="alert">${esc(this._message)}</div>` : ""}
    </ha-card>`;
  }

  /** What the playbook reported (HA_RESULT): pending updates / restart needed - or "nothing to do". */
  _needBox(entityId, T, hass) {
    const state = entityId ? this._state(entityId) : null;
    if (!state || !["on", "off"].includes(state.state)) return "";
    const a = state.attributes || {};
    const on = state.state === "on";
    const meta = [];
    if (a.checked) meta.push(`${T.checked} ${fmtRelative(a.checked, hass)}${a.dry_run ? ` (${T.dry_run})` : ""}`);
    const allHosts = Object.entries(a.hosts || {}).filter(([, h]) => h && typeof h === "object");
    const multi = allHosts.length > 1;
    const lang = langOf(hass);
    const num = (n, digits = 1) => new Intl.NumberFormat(hass.locale?.language || lang, { maximumFractionDigits: digits }).format(n);
    const size = (mib) => (mib >= 1024 ? `${num(mib / 1024)} GiB` : `${num(mib, 0)} MiB`);

    // hint lines ("Debian 13 is out"), shown whether or not something is to do
    const noteLines = (items) =>
      items.length
        ? `<div class="notes">${items
            .slice(0, 3)
            .map((n) => `<div class="note"><ha-icon icon="mdi:information-outline"></ha-icon><span>${n.host ? `<b>${esc(n.host)}:</b> ` : ""}${esc(n.text)}</span></div>`)
            .join("")}${items.length > 3 ? `<div class="note"><span>${esc(T.more_n.replace("{n}", items.length - 3))}</span></div>` : ""}</div>`
        : "";

    // disk of one host (root file system), if the playbook reports it
    const hasDisk = (h) => ["disk_free_mib", "disk_used_percent", "disk_required_mib"].some((k) => typeof h[k] === "number");
    const diskRow = (name, h) => {
      const parts = [];
      if (typeof h.disk_free_mib === "number") parts.push(`${size(h.disk_free_mib)} ${T.disk_free}`);
      if (typeof h.disk_used_percent === "number") parts.push(`${num(h.disk_used_percent)} % ${T.disk_used}`);
      if (h.disk_required_mib > 0) parts.push(`${T.disk_need} ${size(h.disk_required_mib)}`);
      const pct = typeof h.disk_used_percent === "number" ? Math.min(100, h.disk_used_percent) : null;
      const level = pct === null ? "" : pct >= 90 ? "crit" : pct >= 80 ? "warn" : "";
      const label = `${name ? `${name}: ` : ""}${parts.join(" · ")}`;
      return `<div class="disk"><ha-icon icon="mdi:harddisk"></ha-icon><span class="dtext">${name ? `<b>${esc(name)}:</b> ` : ""}${esc(parts.join(" · "))}</span>${pct === null ? "" : `<span class="bar ${level}" role="img" aria-label="${esc(label)}"><i style="width:${pct}%"></i></span>`}</div>`;
    };

    // package chips; all are rendered, _fitPackages() folds them into one line and writes "+n more" into the button
    const pkgBox = (names, key, omitted = 0) => {
      if (!names.length) return "";
      const open = this._isOpen(key);
      const tail = omitted > 0 ? `<div class="note"><span>${esc(T.pkgs_omitted.replace("{n}", num(omitted, 0)))}</span></div>` : "";
      return `<div class="pkgs${open ? " open" : ""}" data-key="${esc(key)}">${names.map((n) => `<span class="pkg" title="${esc(n)}">${esc(n)}</span>`).join("")}${
        names.length > 1
          ? `<button type="button" class="pkg more" data-action="pkgs" data-key="${esc(key)}" aria-expanded="${open}" title="${esc(open ? T.show_less : T.show_all)}" hidden>${esc(open ? T.less : "")}</button>`
          : ""
      }</div>${tail}`;
    };

    let inner;
    if (!multi) {
      // one host (or none): as before
      const notes = (Array.isArray(a.notes) ? a.notes : []).filter((n) => n && typeof n === "object" && n.text).map((n) => ({ text: n.text }));
      const diskHtml = allHosts.length && hasDisk(allHosts[0][1]) ? `<div class="disks">${diskRow("", allHosts[0][1])}</div>` : "";
      const names = on && Array.isArray(a.packages) ? a.packages : [];
      inner = `${diskHtml}${pkgBox(names, "", allHosts.length ? allHosts[0][1].packages_omitted || 0 : 0)}${noteLines(notes)}`;
    } else {
      // several hosts: one block per host, separated by a thin line
      const shown = allHosts.slice(0, 8);
      const blocks = shown.map(([name, h]) => {
        const status = [];
        if (h.updates) status.push((h.updates === 1 ? T.update_1 : T.updates_n.replace("{n}", num(h.updates, 0))));
        if (h.reboot_required) status.push(T.reboot_short);
        const need = !!h.needed;
        const text = status.length ? status.join(", ") : need ? T.host_action : T.host_ok;
        const own = Array.isArray(h.notes) ? h.notes.filter(Boolean).map((t) => ({ text: String(t) })) : [];
        const names = Array.isArray(h.packages) ? h.packages : [];
        return `<div class="host"><div class="hh"><span class="hn">${esc(name)}</span><span class="hs${need ? " need" : ""}">${esc(text)}</span></div>${hasDisk(h) ? `<div class="disks">${diskRow("", h)}</div>` : ""}${pkgBox(names, name, h.packages_omitted || 0)}${noteLines(own)}</div>`;
      });
      if (allHosts.length > shown.length) blocks.push(`<div class="host"><span class="hs">${esc(T.more_n.replace("{n}", allHosts.length - shown.length))}</span></div>`);
      inner = `<div class="hosts">${blocks.join("")}</div>`;
    }
    return `<div class="needbox ${on ? "on" : "off"}" data-action="more-info" data-entity="${entityId}">
      <ha-icon icon="${on ? "mdi:package-up" : "mdi:check-circle-outline"}"></ha-icon>
      <div class="t"><div class="what">${esc(a.explanation || T.action_n)}</div>${meta.length ? `<div class="meta">${meta.map(esc).join(" · ")}</div>` : ""}${inner}</div>
    </div>`;
  }

  _surveyField(entityId, T) {
    const s = this._hass.states[entityId];
    if (!s) return "";
    const domain = entityId.split(".")[0];
    const device = this._hass.devices?.[this._config.device_id];
    let label = s.attributes.friendly_name || entityId;
    const dn = deviceName(device);
    if (dn && label.startsWith(dn + " ")) label = label.slice(dn.length + 1);
    const required = s.attributes.required ? ` <span class="req" title="${esc(T.required)}">*</span>` : "";
    const disabled = s.state === "unavailable" ? "disabled" : "";
    const known = !["unknown", "unavailable"].includes(s.state);
    const title = s.attributes.description ? ` title="${esc(s.attributes.description)}"` : "";
    let control = "";
    if (domain === "select") {
      const opts = (s.attributes.options || []).map((o) => `<option value="${esc(o)}" ${o === s.state ? "selected" : ""}>${esc(o)}</option>`).join("");
      control = `<select data-entity="${entityId}" data-domain="select" ${disabled}>${known ? "" : `<option value="" selected disabled>${esc(T.select_placeholder)}</option>`}${opts}</select>`;
    } else if (domain === "number") {
      control = `<input type="number" step="1" data-entity="${entityId}" data-domain="number" value="${known ? esc(s.state) : ""}" ${disabled}>`;
    } else {
      control = `<input type="text" maxlength="255" data-entity="${entityId}" data-domain="text" value="${known ? esc(s.state) : ""}" ${disabled}>`;
    }
    return `<label${title}><span>${esc(label)}${required}</span>${control}</label>`;
  }

  _afterRender() {
    this._tick();
    this._fitPackages();
    this._observeSize();
    // <ha-card> draws its slot in a microtask: only after that the chips have a width to measure
    queueMicrotask(() => {
      this._fitPackages();
      this._restoreFocus();
    });
  }

  _isOpen(key) {
    return !!this._pkgsOpen && this._pkgsOpen.has(key);
  }

  /** A redraw replaces the buttons: put the keyboard focus back on "+n more" / "less". */
  _restoreFocus() {
    if (typeof this._focusPkgs !== "string") return;
    const key = this._focusPkgs;
    this._focusPkgs = false;
    const button = [...this.shadowRoot.querySelectorAll('[data-action="pkgs"]')].find((b) => (b.dataset.key || "") === key);
    if (button && !button.hidden) button.focus();
  }

  /** Re-fit the package line when the card gets wider/narrower (and once the fonts are there). */
  _observeSize() {
    if (!this._ro && typeof ResizeObserver !== "undefined") {
      this._ro = new ResizeObserver(() => {
        cancelAnimationFrame(this._fitFrame);
        this._fitFrame = requestAnimationFrame(() => this._fitPackages());
      });
      this._ro.observe(this);
    }
    if (!this._fontsHooked && document.fonts && document.fonts.ready) {
      this._fontsHooked = true;
      document.fonts.ready.then(() => this._fitPackages());
    }
  }

  /**
   * Folded: as many package chips as fit into ONE line, the rest is summed up as "+n more" (a button).
   * Open: all chips (wrapped) and a "less" button - unless everything fits into one line anyway.
   */
  _fitPackages() {
    if (!this._hass) return;
    const T = tx(this._hass);
    // never toggle a visible button off and on again while measuring: that would take the keyboard focus away
    const setHidden = (el, hidden) => {
      if (el.hidden !== hidden) el.hidden = hidden;
    };
    const setText = (el, text) => {
      if (el.textContent !== text) el.textContent = text;
    };
    for (const box of this.shadowRoot.querySelectorAll(".pkgs")) {
      const more = box.querySelector(".pkg.more");
      const chips = [...box.querySelectorAll(".pkg:not(.more)")];
      const width = box.clientWidth;
      if (!more || !width) continue; // not laid out yet (hidden tab): the size observer calls us again
      const gap = parseFloat(getComputedStyle(box).columnGap) || 4;
      box.classList.remove("one"); // measure the natural widths: nothing may shrink meanwhile
      chips.forEach((c) => setHidden(c, false));
      const natural = chips.reduce((sum, c) => sum + c.offsetWidth, 0) + gap * (chips.length - 1);
      const fits = natural <= width + 0.5;
      if (this._isOpen(box.dataset.key || "")) {
        setText(more, T.less);
        setHidden(more, fits); // everything fits into one line anyway: nothing to fold, so nothing to unfold
        continue;
      }
      if (fits) {
        setHidden(more, true);
        continue;
      }
      setHidden(more, false);
      let shown = chips.length - 1;
      for (; shown > 1; shown--) {
        setText(more, T.more_n.replace("{n}", String(chips.length - shown)));
        const used = chips.slice(0, shown).reduce((sum, c) => sum + c.offsetWidth, 0) + gap * shown;
        if (used + more.offsetWidth <= width + 0.5) break;
      }
      shown = Math.max(1, shown);
      chips.forEach((c, i) => setHidden(c, i >= shown));
      box.classList.toggle("one", shown === 1);
      setText(more, T.more_n.replace("{n}", String(chips.length - shown)));
    }
  }
  _tick() {
    const el = this.shadowRoot.querySelector(".elapsed");
    if (!el) return;
    const since = new Date(el.dataset.since).getTime();
    if (!isNaN(since)) el.textContent = fmtDuration((Date.now() - since) / 1000, this._hass);
  }

  async _onClick(ev) {
    const target = ev.target.closest("[data-action]");
    if (!target) return;
    const action = target.dataset.action;
    const entity = target.dataset.entity;
    if (action === "more-info") return this._moreInfo(entity);
    if (action === "schedule") return this._toggleSchedule(entity);
    if (action === "pkgs") {
      const key = target.dataset.key || "";
      this._pkgsOpen = this._pkgsOpen || new Set();
      if (!this._pkgsOpen.delete(key)) this._pkgsOpen.add(key);
      this._focusPkgs = key; // the click redraws the card: keep the keyboard focus on the button
      return this._redraw();
    }
    if (action === "start") {
      if (this._config.confirm_start) {
        this._confirmUntil = Date.now() + 5000;
        clearTimeout(this._confirmTimer);
        this._confirmTimer = setTimeout(() => {
          this._confirmUntil = 0;
          this._sig = "";
          this._update();
        }, 5200);
        this._sig = "";
        return this._update();
      }
      return this._press(entity);
    }
    if (action === "confirm-yes") {
      this._confirmUntil = 0;
      this._sig = "";
      this._update();
      return this._press(entity);
    }
    if (action === "confirm-no") {
      this._confirmUntil = 0;
      this._sig = "";
      return this._update();
    }
    if (action === "press") return this._press(entity);
  }

  async _press(entity) {
    return this._busyRun(entity, true, async () => {
      await this._inflight; // a value typed just before the click must be stored first
      return this._call("button", "press", { entity_id: entity });
    });
  }

  _onChange(ev) {
    const el = ev.target;
    const entity = el.dataset?.entity;
    if (!entity) return;
    const domain = el.dataset.domain;
    if (domain === "select") this._inflight = this._call("select", "select_option", { entity_id: entity, option: el.value });
    else if (domain === "number") {
      if (el.value === "" || isNaN(Number(el.value))) return;
      this._inflight = this._call("number", "set_value", { entity_id: entity, value: Math.trunc(Number(el.value)) });
    } else this._inflight = this._call("text", "set_value", { entity_id: entity, value: el.value });
  }
}
SemaphoreTemplateCard.prototype.getGridOptions = function () {
  return { columns: 12, min_columns: 6 };
};

/* ========================================================== project card */
class SemaphoreProjectCard extends SemaphoreBaseCard {
  static get defaults() {
    return { sort: "status", show_never_run: true, show_start: true, confirm_start: false, only_needed: false, show_version: true, show_integration_version: false, show_schedules: true };
  }
  static getConfigElement() {
    return document.createElement("semaphore-ui-card-editor");
  }
  static getStubConfig(hass) {
    const device = projectDevices(hass)[0];
    return { type: "custom:semaphore-ui-project-card", device_id: device ? device.id : "" };
  }
  getCardSize() {
    return 6;
  }

  _templates() {
    const hass = this._hass;
    const out = [];
    for (const dev of templateDevicesOf(hass, this._config.device_id)) {
      const { byKey } = entitiesOfDevice(hass, dev.id);
      if (!byKey["sensor:status"]) continue;
      const status = this._val(byKey["sensor:status"]) || "never_run";
      const sum = this._state(byKey["sensor:summary"]);
      out.push({
        device: dev,
        name: deviceName(dev),
        byKey,
        status,
        started: this._val(byKey["sensor:last_started"]),
        duration: this._val(byKey["sensor:last_duration"]),
        rep: (sum && sum.attributes) || {},
        needs: this._val(byKey["binary_sensor:needs_action"]),
        needText: ((this._state(byKey["binary_sensor:needs_action"]) || {}).attributes || {}).explanation || "",
      });
    }
    const cfg = this._config;
    let list = out.filter((t) => cfg.show_never_run || t.status !== "never_run");
    if (cfg.only_needed) list = list.filter((t) => t.needs === "on" || t.status === "error" || ACTIVE.has(t.status));
    if (Array.isArray(cfg.templates) && cfg.templates.length) list = list.filter((t) => cfg.templates.includes(t.device.id));
    // tapped tile: only the running / failed / "needs action" templates
    if (this._filter === "running") list = list.filter((t) => ACTIVE.has(t.status));
    else if (this._filter === "failed") list = list.filter((t) => t.status === "error");
    else if (this._filter === "action") list = list.filter((t) => t.needs === "on");
    const ts = (t) => (t.started && !isNaN(Date.parse(t.started)) ? Date.parse(t.started) : 0);
    if (cfg.sort === "last_run") list.sort((a, b) => ts(b) - ts(a) || a.name.localeCompare(b.name));
    else if (cfg.sort === "name") list.sort((a, b) => a.name.localeCompare(b.name));
    else {
      // running first, then failed and "needs action", the rest by name
      const rank = (t) => Math.min(SORT_RANK[t.status] ?? 3, t.needs === "on" ? 2.5 : 9);
      list.sort((a, b) => rank(a) - rank(b) || a.name.localeCompare(b.name));
    }
    return list;
  }

  _signature() {
    const c = this._config;
    if (!c.device_id) return "nodevice";
    const hass = this._hass;
    const ids = []; // [entity id, attribute that is part of the signature]
    const add = (id, attr) => id && ids.push([id, attr]);
    const { byKey } = entitiesOfDevice(hass, c.device_id);
    for (const id of Object.values(byKey)) add(id);
    add(byKey["sensor:project_next_run"], "schedules");
    for (const dev of templateDevicesOf(hass, c.device_id)) {
      const k = entitiesOfDevice(hass, dev.id).byKey;
      for (const key of ["sensor:status", "sensor:last_started", "sensor:last_duration", "button:start", "button:stop"]) add(k[key]);
      add(k["sensor:summary"], "short");
      add(k["binary_sensor:needs_action"], "explanation");
    }
    const parts = ids.map(([id, attr]) => {
      const s = hass.states[id];
      const value = attr ? s?.attributes[attr] : "";
      return s ? `${id}=${s.state}|${value && typeof value === "object" ? JSON.stringify(value) : value}` : `${id}=?`;
    });
    const hacs = c.hacs_update_entity ? hass.states[c.hacs_update_entity] : null;
    const hacsPart = hacs ? `${hacs.state}|${hacs.attributes.installed_version}|${hacs.attributes.latest_version}` : "";
    // the minute counter: relative times need a refresh once a minute
    return [JSON.stringify(c), this._message, this._confirmFor || "", this._filter || "", hacsPart, langOf(hass), Math.floor(Date.now() / 60000), ...parts].join("\n");
  }

  _html() {
    const hass = this._hass;
    const T = tx(hass);
    const c = this._config;
    if (!c.device_id) return `<ha-card><div class="notice">${esc(T.choose_device_p)}</div></ha-card>`;
    const device = hass.devices?.[c.device_id];
    if (!device) return `<ha-card><div class="notice">${esc(T.device_missing)}</div></ha-card>`;
    const { byKey } = entitiesOfDevice(hass, c.device_id);
    if (!byKey["sensor:template_count"]) return `<ha-card><div class="notice">${esc(T.wrong_device)}</div></ha-card>`;

    const title = c.name || deviceName(device).replace(/^Semaphore\s*[–-]\s*/, "");
    const online = this._val(byKey["binary_sensor:connectivity"]) !== "off";
    const updateState = this._state(byKey["update:semaphore_update"]);
    const updateOn = updateState && updateState.state === "on";
    const num = (key) => {
      const v = this._val(byKey[key]);
      return v === undefined || isNaN(Number(v)) ? "–" : Number(v);
    };
    const running = num("sensor:running_tasks");
    const failed = num("sensor:failed_templates");
    const actionId = byKey["sensor:action_templates"];
    const action = actionId ? num("sensor:action_templates") : null;

    const lastStatus = this._val(byKey["sensor:last_task_status"]) || "never_run";
    const lastKnown = STATUS_STYLE[lastStatus] ? lastStatus : "never_run";
    const lastSt = STATUS_STYLE[lastKnown];
    const lastTpl = this._val(byKey["sensor:last_task_template"]);
    const lastStarted = this._val(byKey["sensor:last_task_started"]);
    const lastAttrs = (this._state(byKey["sensor:last_task_template"]) || {}).attributes || {};

    let lastHtml = "";
    if (lastTpl && lastTpl !== "unknown" && lastTpl !== "unavailable") {
      const bits = [esc(T.status[lastKnown] || lastKnown)];
      if (lastStarted && lastStarted !== "unknown") bits.push(esc(fmtRelative(lastStarted, hass)));
      if (lastAttrs.duration) bits.push(esc(lastAttrs.duration));
      lastHtml = `<div class="last" data-action="more-info" data-entity="${byKey["sensor:last_task_template"]}">
        <ha-icon class="${lastSt.pulse ? "pulse" : ""}" icon="${lastSt.icon}" style="color:${lastSt.color}"></ha-icon>
        <div class="t"><div class="sub">${esc(T.last_task)}</div><div>${esc(lastTpl)}</div><div class="sub">${bits.join(" · ")}</div></div></div>`;
    }

    const items = this._templates();
    const emptyText = { running: T.none_running, failed: T.none_failed, action: T.none_action }[this._filter] || (c.only_needed ? T.nothing_needed : T.no_templates);
    const itemsHtml = items.length ? items.map((t) => this._item(t, T, hass)).join("") : `<div class="notice">${esc(emptyText)}</div>`;

    // Version line: Semaphore and (optional) the integration; the HACS update entity adds "update available".
    const versionBits = [];
    if (c.show_version !== false) {
      versionBits.push(`Semaphore UI${updateState && updateState.attributes.installed_version ? " " + esc(updateState.attributes.installed_version) : ""}`);
    }
    const hacsState = c.hacs_update_entity ? this._state(c.hacs_update_entity) : null;
    const hacsOn = !!hacsState && hacsState.state === "on";
    if (c.show_integration_version) {
      const installed = (hacsState && hacsState.attributes.installed_version) || SEMAPHORE_CARD_VERSION;
      versionBits.push(`${esc(T.integration)} ${esc(installed)}`);
    }
    const versionLine = versionBits.length ? `<div class="sub">${versionBits.join(" · ")}</div>` : "";
    const hacsChip = hacsOn
      ? `<span class="chip" style="--chip-color:var(--warning-color,#ffa600)" data-action="more-info" data-entity="${esc(c.hacs_update_entity)}"><ha-icon icon="mdi:arrow-up-bold-circle-outline"></ha-icon>${esc(T.integration_update)}${hacsState.attributes.latest_version ? " " + esc(hacsState.attributes.latest_version) : ""}</span>`
      : "";
    const tile = (filter, cls, count, label) =>
      `<div class="stat ${cls}${this._filter === filter ? " sel" : ""}" data-action="filter" data-filter="${filter}" aria-pressed="${this._filter === filter}" title="${esc(T.filter_hint)}"><div class="n">${count}</div><div class="l">${esc(label)}</div></div>`;

    // Schedules of the whole project (soonest first, switched-off ones last)
    const nextAttrs = (this._state(byKey["sensor:project_next_run"]) || {}).attributes || {};
    let schedHtml = "";
    if (c.show_schedules !== false && Array.isArray(nextAttrs.schedules) && nextAttrs.schedules.length) {
      const soon = (x) => (x.active && x.next_run ? Date.parse(x.next_run) : Infinity);
      const ordered = [...nextAttrs.schedules].sort((a, b) => (b.active ? 1 : 0) - (a.active ? 1 : 0) || soon(a) - soon(b) || a.name.localeCompare(b.name));
      const zone = nextAttrs.timezone ? ` title="${esc(T.schedule_tz)}: ${esc(nextAttrs.timezone)}"` : "";
      schedHtml = `<div class="sched"><div class="sched-title"${zone}>${esc(T.schedules)}</div>${ordered.map((item) => this._scheduleRow(item, T, hass, true)).join("")}</div>`;
    }

    return `<ha-card>
      <div class="head" data-action="more-info" data-entity="${byKey["sensor:template_count"]}">
        <ha-icon class="ic" icon="mdi:script-text-play-outline" style="color:var(--primary-color)"></ha-icon>
        <div class="titles"><div class="title">${esc(title)}</div>${versionLine}</div>
        ${hacsChip || updateOn ? `<div class="chips">${hacsChip}${updateOn ? `<span class="chip" style="--chip-color:var(--warning-color,#ffa600)" data-action="more-info" data-entity="${byKey["update:semaphore_update"]}"><ha-icon icon="mdi:arrow-up-bold-circle-outline"></ha-icon>${esc(T.update)}</span>` : ""}</div>` : ""}
      </div>
      ${online ? "" : `<div class="banner off" role="alert"><ha-icon icon="mdi:lan-disconnect"></ha-icon>${esc(T.offline)}</div>`}
      <div class="stats ${action !== null ? "four" : ""}">
        ${tile("running", running > 0 ? "busy" : "", running, T.running_n)}
        ${tile("failed", failed > 0 ? "bad" : "", failed, T.failed_n)}
        ${action !== null ? tile("action", action > 0 ? "warn" : "", action, T.action_n) : ""}
        ${tile("all", "", num("sensor:template_count"), T.templates_n)}
      </div>
      ${lastHtml}
      <div class="list">${itemsHtml}</div>
      ${schedHtml}
      ${this._message ? `<div class="msg" role="alert">${esc(this._message)}</div>` : ""}
    </ha-card>`;
  }

  _item(t, T, hass) {
    const known = STATUS_STYLE[t.status] ? t.status : "never_run";
    const st = STATUS_STYLE[known];
    const active = ACTIVE.has(t.status);
    const bits = [];
    if (t.status === "never_run") bits.push(T.never);
    else {
      bits.push(T.status[known] || known);
      if (t.rep && t.rep.dry_run) bits.push(T.dry_run);
      if (t.started && t.started !== "unknown") bits.push(fmtRelative(t.started, hass));
      if (!active && t.duration && !isNaN(Number(t.duration))) bits.push(fmtDuration(Number(t.duration), hass));
    }
    if (t.status === "error" && t.rep.error && t.rep.error.reason) bits.push(t.rep.error.reason);
    else if (t.needs === "on" && t.needText) bits.push(t.needText);
    const dryItem = !!(t.rep && t.rep.dry_run) && !active && t.status !== "never_run"; // a dry run: lighter, dashed icon
    const needIcon = t.needs === "on" ? `<ha-icon class="need" icon="mdi:package-up" title="${esc(t.needText)}"></ha-icon>` : "";
    const startId = t.byKey["button:start"];
    const stopId = t.byKey["button:stop"];
    const unavailable = this._val(t.byKey["sensor:status"]) === "unavailable";
    let action = "";
    if (active && stopId) {
      action = `<button class="icon${this._busy.has(stopId) ? " busy" : ""}" data-action="press" data-entity="${stopId}"${this._busyAttrs(stopId)} aria-label="${esc(T.stop)} ${esc(t.name)}" title="${esc(T.stop)}">${this._ico(stopId, "mdi:stop", "color:var(--error-color,#db4437)")}</button>`;
    } else if (this._config.show_start && startId) {
      const confirming = this._confirmFor === startId;
      action = confirming
        ? `<button class="icon${this._busy.has(startId) ? " busy" : ""}" data-action="confirm-yes" data-entity="${startId}"${this._busyAttrs(startId)} aria-label="${esc(T.yes)}" title="${esc(T.confirm)}">${this._ico(startId, "mdi:check", "color:var(--success-color,#43a047)")}</button>
           <button class="icon" data-action="confirm-no" aria-label="${esc(T.no)}"><ha-icon icon="mdi:close"></ha-icon></button>`
        : `<button class="icon${this._busy.has(startId) ? " busy" : ""}" data-action="start" data-entity="${startId}"${this._busyAttrs(startId)} ${unavailable ? "disabled" : ""} aria-label="${esc(T.start)} ${esc(t.name)}" title="${esc(T.start)}">${this._ico(startId, "mdi:play")}</button>`;
    }
    return `<div class="item">
      <ha-icon class="ic ${st.pulse ? "pulse" : ""}${dryItem ? " dry" : ""}" icon="${st.icon}" style="color:${st.color}"${dryItem ? ` title="${esc(T.dry_run_hint)}"` : ""}></ha-icon>
      <div class="main" data-action="more-info" data-entity="${t.byKey["sensor:status"]}">
        <div class="name">${esc(t.name)}${needIcon}</div><div class="sub" title="${esc(bits.join(" · "))}">${esc(bits.join(" · "))}</div>
      </div>${action}</div>`;
  }

  async _onClick(ev) {
    const target = ev.target.closest("[data-action]");
    if (!target) return;
    const action = target.dataset.action;
    const entity = target.dataset.entity;
    if (action === "more-info") return this._moreInfo(entity);
    if (action === "schedule") return this._toggleSchedule(entity);
    if (action === "filter") {
      const wanted = target.dataset.filter;
      this._filter = wanted === "all" || this._filter === wanted ? "" : wanted;
      this._sig = "";
      return this._update();
    }
    if (action === "start" && this._config.confirm_start) {
      this._confirmFor = entity;
      clearTimeout(this._confirmTimer);
      this._confirmTimer = setTimeout(() => {
        this._confirmFor = "";
        this._sig = "";
        this._update();
      }, 5000);
      this._sig = "";
      return this._update();
    }
    if (action === "confirm-no") {
      this._confirmFor = "";
      this._sig = "";
      return this._update();
    }
    if (action === "start" || action === "confirm-yes" || action === "press") {
      this._confirmFor = "";
      this._sig = "";
      this._update();
      return this._call("button", "press", { entity_id: entity });
    }
  }
}

/* ================================================================ editor */
class SemaphoreCardEditor extends HTMLElement {
  setConfig(config) {
    this._config = config;
    this._render();
  }
  set hass(hass) {
    this._hass = hass;
    if (this._form) this._form.hass = hass;
    this._render();
  }
  _schema() {
    const T = tx(this._hass).ed;
    const project = (this._config?.type || "").includes("project");
    // A plain list ("Homelab › Host-Update") instead of the generic device picker: it is clear which
    // entry to take, also with several projects whose templates have the same name.
    const options = deviceOptions(this._hass, project ? "Project" : "Template");
    const current = this._config?.device_id;
    if (current && !options.some((o) => o.value === current)) {
      options.push({ value: current, label: `${T.unknown_device} ${current}` });
    }
    const base = [
      {
        name: "device_id",
        required: true,
        selector: { select: { mode: "dropdown", options } },
      },
      { name: "name", selector: { text: {} } },
    ];
    if (project) {
      base.push(
        {
          name: "sort",
          selector: {
            select: {
              mode: "dropdown",
              options: [
                { value: "status", label: T.sort_status },
                { value: "name", label: T.sort_name },
                { value: "last_run", label: T.sort_last_run },
              ],
            },
          },
        },
        { name: "show_never_run", selector: { boolean: {} } },
        { name: "only_needed", selector: { boolean: {} } },
        { name: "show_start", selector: { boolean: {} } },
        { name: "confirm_start", selector: { boolean: {} } },
        { name: "show_version", selector: { boolean: {} } },
        { name: "show_integration_version", selector: { boolean: {} } },
        { name: "hacs_update_entity", selector: { entity: { domain: "update" } } },
        { name: "show_schedules", selector: { boolean: {} } }
      );
    } else {
      base.push({ name: "show_survey", selector: { boolean: {} } }, { name: "show_details", selector: { boolean: {} } }, { name: "confirm_start", selector: { boolean: {} } }, { name: "show_schedules", selector: { boolean: {} } });
    }
    return base;
  }
  _render() {
    if (!this._hass || !this._config) return;
    if (!this._form) {
      this._form = document.createElement("ha-form");
      this._form.addEventListener("value-changed", (ev) => {
        ev.stopPropagation();
        this._config = { ...this._config, ...ev.detail.value };
        this.dispatchEvent(new CustomEvent("config-changed", { detail: { config: this._config }, bubbles: true, composed: true }));
      });
      this.appendChild(this._form);
    }
    const T = tx(this._hass).ed;
    const project = (this._config.type || "").includes("project");
    const defaults = project ? SemaphoreProjectCard.defaults : SemaphoreTemplateCard.defaults;
    this._form.hass = this._hass;
    this._form.schema = this._schema();
    this._form.data = { ...defaults, ...this._config };
    this._form.computeLabel = (s) => (s.name === "device_id" ? (project ? T.device_id_p : T.device_id_t) : T[s.name] || s.name);
    this._form.computeHelper = (s) => (s.name === "device_id" ? (project ? T.help_device_p : T.help_device_t) : undefined);
    if (!this._notice) {
      this._notice = document.createElement("p");
      this._notice.style.cssText = "color:var(--error-color,#db4437);margin:0 0 12px";
      this.insertBefore(this._notice, this._form);
    }
    this._notice.textContent = deviceOptions(this._hass, project ? "Project" : "Template").length ? "" : T.no_devices;
  }
}

/**
 * Register the elements once the Home Assistant frontend is up. Modules that Home Assistant loads
 * on its own (extra_module_url) can run before the frontend has installed its own element registry;
 * elements defined that early are not found by the dashboard ("Custom element doesn't exist").
 */
function defineElements() {
  const defs = [
    ["semaphore-ui-template-card", SemaphoreTemplateCard],
    ["semaphore-ui-project-card", SemaphoreProjectCard],
    ["semaphore-ui-card-editor", SemaphoreCardEditor],
  ];
  for (const [name, cls] of defs) if (!customElements.get(name)) customElements.define(name, cls);
}
(function whenFrontendReady() {
  if (customElements.get("ha-card")) return defineElements();
  const started = Date.now();
  const timer = setInterval(() => {
    if (customElements.get("ha-card") || Date.now() - started > 60000) {
      clearInterval(timer);
      defineElements();
    }
  }, 25);
})();

window.customCards = window.customCards || [];
for (const card of [
  {
    type: "semaphore-ui-template-card",
    name: "Semaphore UI – Template",
    description: "Ein Semaphore-Template (Gerät „Projekt › Template“): Status, Start / Testlauf / Stopp, letzter Lauf, Fehlergrund, Eingabefelder.",
  },
  {
    type: "semaphore-ui-project-card",
    name: "Semaphore UI – Projekt",
    description: "Übersicht eines Semaphore-Projekts (Gerät „Semaphore – Projektname“): Verfügbarkeit, Update, letzter Task und alle Templates mit Schnellstart.",
  },
]) {
  if (!window.customCards.some((c) => c.type === card.type)) {
    // preview: the picker shows the card with the first matching device (see getStubConfig)
    window.customCards.push({ ...card, preview: true, documentationURL: "https://semaphoreui.com/docs" });
  }
}
console.info(`%c SEMAPHORE-UI-CARD %c ${SEMAPHORE_CARD_VERSION} `, "color:#fff;background:#039be5;font-weight:700", "color:#039be5;background:#fff;font-weight:700");
