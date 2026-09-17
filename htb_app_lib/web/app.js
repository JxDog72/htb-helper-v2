(() => {
  const TABS = ["notes", "logs", "tools", "info", "evidence", "files", "report", "convert", "status", "ctf", "help", "lab", "settings"];
  const SETTINGS_KEY = "htb-settings";
  const THEMES = [
    { id: "field", name: "Field notebook", blurb: "Copper on dark paper (default)" },
    { id: "phosphor", name: "Phosphor", blurb: "Green terminal on black" },
    { id: "midnight", name: "Midnight", blurb: "Navy and ice blue" },
    { id: "slate", name: "Slate", blurb: "Steel gray, low glare" },
    { id: "ember", name: "Ember", blurb: "Red-amber ICS night" },
    { id: "arctic", name: "Arctic", blurb: "High-contrast cyan" },
    { id: "custom", name: "Custom", blurb: "Pick your own colors" },
  ];
  const DEFAULT_CUSTOM = {
    chassis: "#14110d",
    text: "#efe6d4",
    copper: "#c9843a",
    copperHot: "#e2a45a",
    paper: "#f1e6c8",
    ink: "#231910",
    console: "#0e140f",
  };
  const CUSTOM_CSS_KEYS = [
    "chassis", "panel", "rail", "rule", "paper", "paper-edge", "ink", "muted-ink",
    "copper", "copper-hot", "signal", "warn", "rec", "quiet", "console", "phosphor",
    "blue", "text", "btn-bg", "input-bg", "header-from", "header-to", "rail-active-bg",
    "tape-bg", "tape-line", "paper-pre", "paper-pre-fg", "paper-code", "paper-link",
    "on-accent", "overlay", "tick-rule", "error-text",
  ];
  const DEFAULT_SETTINGS = {
    theme: "field",
    speedUp: false,
    notesView: "split",
    startTab: "help",
    logLive: true,
    includeToolNotes: false,
    includeToolCmd: true,
    includeToolFindings: true,
    defaultCategory: "NONE",
    customColors: DEFAULT_CUSTOM,
  };
  const CATS = ["NONE", "RECON", "ENUMERATION", "FINDING", "DEAD END", "FOOTHOLD", "PRIVESC", "FLAG", "TOOL", "OTHER"];

  const $ = (id) => document.getElementById(id);
  const state = {
    dirty: false,
    category: "NONE",
    logOffset: 0,
    logName: "session.log",
    tools: [],
    currentTool: null,
    follow: true,
    setupSeeded: false,
    labChosen: false,
    labPick: "",
    toolsLoaded: false,
    reportDirty: false,
    cmdDirty: false,
    toolRunning: false,
    applyingPreview: false,
    lastOutFile: "",
    osName: "",
  };

  const THEME_SWATCH = {
    field: ["#14110d", "#c9843a", "#f1e6c8"],
    phosphor: ["#07110b", "#3dff7a", "#d7f0d0"],
    midnight: ["#0b1220", "#5b8def", "#e8eef8"],
    slate: ["#1a1d21", "#a8b3c2", "#eceff3"],
    ember: ["#140b0a", "#e85d3a", "#f6e4d4"],
    arctic: ["#0a1214", "#2ee6d6", "#e8f7f6"],
    custom: ["#2a2a2a", "#c9843a", "#efe6d4"],
  };

  function parseHex(h) {
    let s = String(h || "").replace("#", "").trim();
    if (s.length === 3) s = s[0] + s[0] + s[1] + s[1] + s[2] + s[2];
    if (!/^[0-9a-fA-F]{6}$/.test(s)) return { r: 20, g: 17, b: 13 };
    return { r: parseInt(s.slice(0, 2), 16), g: parseInt(s.slice(2, 4), 16), b: parseInt(s.slice(4, 6), 16) };
  }
  function rgbHex(r, g, b) {
    const c = (n) => Math.max(0, Math.min(255, n | 0)).toString(16).padStart(2, "0");
    return "#" + c(r) + c(g) + c(b);
  }
  function mixHex(a, b, t) {
    const pa = parseHex(a), pb = parseHex(b);
    const m = (x, y) => Math.round(x + (y - x) * t);
    return rgbHex(m(pa.r, pb.r), m(pa.g, pb.g), m(pa.b, pb.b));
  }
  function luma(h) {
    const p = parseHex(h);
    return (p.r * 299 + p.g * 587 + p.b * 114) / 1000;
  }
  function deriveCustomTheme(raw) {
    const c = Object.assign({}, DEFAULT_CUSTOM, raw || {});
    const chassis = c.chassis, text = c.text, copper = c.copper;
    const hot = c.copperHot || c["copper-hot"] || DEFAULT_CUSTOM.copperHot;
    const paper = c.paper, ink = c.ink, consoleBg = c.console;
    const dark = luma(chassis) < 140;
    return {
      chassis,
      panel: mixHex(chassis, text, dark ? 0.08 : 0.1),
      rail: mixHex(chassis, "#000000", 0.28),
      rule: mixHex(copper, chassis, 0.55),
      paper,
      "paper-edge": mixHex(paper, ink, 0.22),
      ink,
      "muted-ink": mixHex(ink, paper, 0.42),
      copper,
      "copper-hot": hot,
      signal: hot,
      warn: "#c45c3e",
      rec: copper,
      quiet: mixHex(text, chassis, 0.42),
      console: consoleBg,
      phosphor: mixHex(hot, "#ffffff", 0.28),
      blue: hot,
      text,
      "btn-bg": mixHex(chassis, text, 0.12),
      "input-bg": mixHex(chassis, "#000000", 0.18),
      "header-from": mixHex(chassis, text, 0.07),
      "header-to": chassis,
      "rail-active-bg": mixHex(chassis, copper, 0.16),
      "tape-bg": mixHex(chassis, "#000000", 0.16),
      "tape-line": mixHex(copper, chassis, 0.55),
      "paper-pre": mixHex(ink, paper, 0.12),
      "paper-pre-fg": paper,
      "paper-code": mixHex(paper, ink, 0.14),
      "paper-link": copper,
      "on-accent": luma(copper) > 160 ? chassis : "#1a120c",
      overlay: "rgba(0,0,0,0.82)",
      "tick-rule": mixHex(copper, chassis, 0.55),
      "error-text": "#f0a090",
    };
  }
  function clearCustomProperties() {
    CUSTOM_CSS_KEYS.forEach((k) => document.documentElement.style.removeProperty("--" + k));
  }
  function applyCustomColors(raw) {
    const derived = deriveCustomTheme(raw);
    const root = document.documentElement;
    root.setAttribute("data-theme", "custom");
    Object.entries(derived).forEach(([k, v]) => root.style.setProperty("--" + k, v));
    document.querySelectorAll("#custom-colors [data-cvar]").forEach((input) => {
      const c = Object.assign({}, DEFAULT_CUSTOM, raw || {});
      if (c[input.dataset.cvar]) input.value = c[input.dataset.cvar];
    });
  }

  function loadSettings() {
    let stored = {};
    try { stored = JSON.parse(localStorage.getItem(SETTINGS_KEY) || "{}") || {}; } catch (err) { stored = {}; }
    if (stored.speedUp == null) {
      try { stored.speedUp = localStorage.getItem("htb-speed-up") === "1"; } catch (err) { /* ignore */ }
    }
    const next = Object.assign({}, DEFAULT_SETTINGS, stored);
    next.customColors = Object.assign({}, DEFAULT_CUSTOM, stored.customColors || {});
    return next;
  }

  function saveSettings(partial) {
    const cur = loadSettings();
    const next = Object.assign({}, cur, partial);
    if (partial && partial.customColors) {
      next.customColors = Object.assign({}, cur.customColors, partial.customColors);
    }
    try { localStorage.setItem(SETTINGS_KEY, JSON.stringify(next)); } catch (err) { /* ignore */ }
    return next;
  }

  function applyTheme(id, colors) {
    const theme = THEMES.some((t) => t.id === id) ? id : "field";
    const panel = $("custom-colors");
    if (theme === "custom") {
      applyCustomColors(colors || loadSettings().customColors);
      if (panel) panel.classList.remove("hidden");
    } else {
      clearCustomProperties();
      document.documentElement.setAttribute("data-theme", theme);
      if (panel) panel.classList.add("hidden");
    }
    document.querySelectorAll(".theme-card").forEach((card) => {
      card.classList.toggle("active", card.dataset.theme === theme);
    });
    return theme;
  }

  function applyNotesView(mode) {
    const wrap = $("notes-split");
    if (!wrap) return;
    const allowed = ["split", "write", "nice"];
    if (!allowed.includes(mode)) mode = "split";
    wrap.classList.remove("mode-split", "mode-write", "mode-nice");
    wrap.classList.add("mode-" + mode);
    document.querySelectorAll("[data-notes-view]").forEach((b) => {
      b.classList.toggle("active", b.getAttribute("data-notes-view") === mode);
    });
  }

  function fillSettingsForm(s) {
    if ($("set-start-tab")) $("set-start-tab").value = s.startTab;
    if ($("set-notes-view")) $("set-notes-view").value = s.notesView;
    if ($("set-category")) $("set-category").value = s.defaultCategory;
    if ($("set-speed-up")) $("set-speed-up").checked = !!s.speedUp;
    if ($("set-log-live")) $("set-log-live").checked = !!s.logLive;
    if ($("set-tool-notes")) $("set-tool-notes").checked = !!s.includeToolNotes;
    if ($("set-tool-cmd")) $("set-tool-cmd").checked = !!s.includeToolCmd;
    if ($("set-tool-findings")) $("set-tool-findings").checked = !!s.includeToolFindings;
    if ($("speed-up")) $("speed-up").checked = !!s.speedUp;
    if ($("log-live")) $("log-live").checked = !!s.logLive;
  }

  function applySettings(s) {
    applyTheme(s.theme, s.customColors);
    applyNotesView(s.notesView);
    fillSettingsForm(s);
    state.category = CATS.includes(s.defaultCategory) ? s.defaultCategory : "NONE";
  }

  function renderThemeGrid() {
    const grid = $("theme-grid");
    if (!grid) return;
    const current = loadSettings().theme;
    grid.innerHTML = THEMES.map((t) => {
      const sw = (THEME_SWATCH[t.id] || []).map((c) => `<i style="background:${c}"></i>`).join("");
      return `<button type="button" class="theme-card${t.id === current ? " active" : ""}" data-theme="${t.id}">
        <span class="theme-swatch">${sw}</span>
        <span class="name">${escapeHtml(t.name)}</span>
        <span class="blurb">${escapeHtml(t.blurb)}</span>
      </button>`;
    }).join("");
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }

  function renderMarkdown(src) {
    const fences = [];
    let text = String(src || "").replace(/```(\w*)\n([\s\S]*?)```/g, (_, lang, code) => {
      const i = fences.length;
      fences.push(
        `<pre><div class="code-lang">${escapeHtml(lang)}</div><code>${escapeHtml(code.replace(/\n$/, ""))}</code></pre>`
      );
      return `\0F${i}\0`;
    });
    const lines = text.split("\n");
    const out = [];
    let list = null;
    const flushList = () => {
      if (list) {
        out.push(`<ul>${list.join("")}</ul>`);
        list = null;
      }
    };
    const mediaSrc = (src) => {
      if (/^(https?:|data:|\/api\/)/i.test(src)) return src;
      return "/api/media?path=" + encodeURIComponent(src);
    };
    const inline = (s) => escapeHtml(s)
      .replace(/!\[([^\]]*)\]\(([^)]+)\)/g, (_, alt, src) =>
        `<img alt="${alt}" src="${mediaSrc(src.replace(/&amp;/g, "&"))}">`)
      .replace(/\[([^\]]+)\]\(([^)]+)\)/g, (_, label, href) =>
        `<a href="${href}" target="_blank" rel="noopener">${label}</a>`)
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/\*([^*]+)\*/g, "<em>$1</em>");
    for (const line of lines) {
      const fence = line.match(/^\0F(\d+)\0$/);
      if (fence) {
        flushList();
        out.push(fences[Number(fence[1])]);
        continue;
      }
      if (/^---+$/.test(line.trim())) {
        flushList();
        out.push("<hr>");
        continue;
      }
      if (line.trim() === "<small>") {
        flushList();
        out.push('<div class="hint-list">');
        continue;
      }
      if (line.trim() === "</small>") {
        flushList();
        out.push("</div>");
        continue;
      }
      const h = line.match(/^\s*(#{1,6})\s*(.*)$/);
      if (h) {
        flushList();
        out.push(`<h${h[1].length}>${inline(h[2])}</h${h[1].length}>`);
        continue;
      }
      const li = line.match(/^\s*[-*]\s+(.*)$/);
      if (li) {
        list = list || [];
        list.push(`<li>${inline(li[1])}</li>`);
        continue;
      }
      if (!line.trim()) {
        flushList();
        continue;
      }
      flushList();
      out.push(`<p>${inline(line)}</p>`);
    }
    flushList();
    return out.join("\n");
  }

  async function api(path, opts) {
    const res = await fetch(path, opts);
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || res.statusText);
    return data;
  }

  function setTab(name) {
    TABS.forEach((tab) => {
      $(`tab-${tab}`).classList.toggle("active", tab === name);
      document.querySelector(`[data-tab="${tab}"]`).classList.toggle("active", tab === name);
    });
    if (name === "logs") refreshLogs(true).catch(() => {});
    if (name === "files") refreshFiles();
    if (name === "evidence") refreshEvidence();
    if (name === "status") refreshStatus();
    if (name === "info") renderInfo();
    if (name === "ctf") renderCtf();
    if (name === "tools" && !state.toolsLoaded) loadTools();
    if (name === "report" && !state.reportDirty) loadReport();
    if (name === "lab") {
      api("/api/state").then((data) => fillLabConfig(data.config || {})).catch(() => {});
    }
  }

  function insertAtCursor(textarea, text, cursorOffset) {
    const start = textarea.selectionStart;
    const end = textarea.selectionEnd;
    const before = textarea.value.slice(0, start);
    const after = textarea.value.slice(end);
    textarea.value = before + text + after;
    const pos = start + (cursorOffset == null ? text.length : cursorOffset);
    textarea.setSelectionRange(pos, pos);
    textarea.focus();
    if (textarea.id === "notes-editor") onNotesInput();
    if (textarea.id === "report-editor") onReportInput();
  }

  function onNotesInput() {
    state.dirty = true;
    $("save-state").textContent = "unsaved";
    $("notes-preview").innerHTML = renderMarkdown($("notes-editor").value);
    drawTape($("notes-editor").value);
  }

  function drawTape(text) {
    const stamps = [...text.matchAll(/^\[(\d{2}:\d{2})\]/gm)].map((m) => m[1]);
    $("tape").innerHTML = stamps.map((s, i) => (
      `<button type="button" data-i="${i}">${escapeHtml(s)}</button>`
    )).join("");
  }

  async function saveNotes() {
    await api("/api/notes", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: $("notes-editor").value }),
    });
    state.dirty = false;
    $("save-state").textContent = "saved";
  }

  function applyNotesText(text) {
    $("notes-editor").value = text || "";
    state.dirty = false;
    $("save-state").textContent = "saved";
    $("notes-preview").innerHTML = renderMarkdown(text || "");
    drawTape(text || "");
  }

  async function loadNotes() {
    const data = await api("/api/notes");
    applyNotesText(data.text || "");
  }

  function fillLabSelect(labs, current) {
    const sel = $("lab-select");
    const block = $("existing-labs-block");
    if (!labs || !labs.length) {
      block.classList.add("hidden");
      sel.innerHTML = "";
      return;
    }
    block.classList.remove("hidden");
    const keep = state.labPick || sel.value;
    sel.innerHTML = labs.map((lab) => {
      const label = lab.machine_name || lab.id;
      return `<option value="${escapeHtml(lab.id)}">${escapeHtml(label)}</option>`;
    }).join("");
    if (keep && labs.some((lab) => lab.id === keep)) sel.value = keep;
    else if (current) sel.value = current;
  }

  async function refreshState() {
    const data = await api("/api/state");
    fillLabSelect(data.labs || [], data.current_lab);
    $("btn-dismiss-setup").classList.toggle("hidden", !data.configured);
    if (state.labChosen) {
      $("setup-overlay").classList.add("hidden");
    } else {
      $("setup-overlay").classList.remove("hidden");
    }
    if (!state.setupSeeded) {
      const c = data.config || {};
      const form = $("setup-form");
      if (c.student_id && c.student_id !== "YOUR_STUDENT_ID") form.student_id.value = c.student_id;
      if (c.machine_name && c.machine_name !== "MachineName") form.machine_name.value = c.machine_name;
      if (c.target_ip && c.target_ip !== "10.10.10.10") form.target_ip.value = c.target_ip;
      if (c.target_port) form.target_port.value = c.target_port;
      if (c.research_project) form.research_project.value = c.research_project;
      state.setupSeeded = true;
    }
    if (data.os_name) state.osName = data.os_name;
    $("meta-machine").textContent = (data.config && data.config.machine_name) || "—";
    $("meta-target").textContent = (data.config && data.config.target_ip) || "—";
    $("meta-port").textContent = (data.config && data.config.target_port) || "—";

    let sessionLabel = "idle";
    if (data.session_active && data.session_paused) sessionLabel = "PAUSED";
    else if (data.session_active) sessionLabel = "LIVE";
    else if (data.session_log) sessionLabel = "ended";
    $("meta-session").textContent = sessionLabel;
    $("btn-session-menu").textContent = "Session " + sessionLabel + " ▾";
    $("session-menu-hint").textContent = data.session_active
      ? (data.session_paused ? "Logging is paused. Terminal still works." : "Logging every command in this terminal.")
      : "No live session. Start with ./htb (not --gui-only).";
    $("rec-dot").classList.toggle("live", !!data.session_active && !data.session_paused);
    if (data.configured && state.labChosen && !$("notes-editor").value && !state.dirty) await loadNotes();
    return data;
  }

  async function chooseLabDone() {
    state.labChosen = true;
    state.toolsLoaded = false;
    state.currentTool = null;
    $("setup-overlay").classList.add("hidden");
    await refreshState();
    await loadNotes();
    await loadReport();
    const start = loadSettings().startTab;
    setTab(TABS.includes(start) ? start : "help");
  }

  function speedUpOn() {
    return !!($("speed-up") && $("speed-up").checked);
  }

  async function refreshLogs(reset) {
    const sel = $("log-select");
    const tail = !reset && speedUpOn();
    const data = await api(
      `/api/logs?name=${encodeURIComponent(state.logName)}&offset=${reset ? 0 : state.logOffset}&tail=${tail ? "1" : "0"}`
    );
    if (data.files) {
      const current = state.logName;
      sel.innerHTML = data.files.map((n) => `<option ${n === current ? "selected" : ""}>${escapeHtml(n)}</option>`).join("");
      if (!data.files.includes(current) && data.files[0]) {
        state.logName = data.files[0];
        sel.value = data.files[0];
      }
    }
    const view = $("log-view");
    if (reset || data.replace) {
      view.textContent = data.text || "";
      state.logOffset = data.offset || 0;
    } else if (data.text) {
      view.textContent += data.text;
      state.logOffset = data.offset;
    }
    view.scrollTop = view.scrollHeight;
  }

  async function refreshFiles() {
    const data = await api("/api/files");
    const list = $("file-names");
    list.innerHTML = (data.files || []).map((f) => `<option value="${escapeHtml(f.path)}"></option>`).join("");
    $("file-list").innerHTML = (data.files || []).map((f) => (
      `<div class="rowline"><span>${escapeHtml(f.path)}</span><span>${f.size.toLocaleString()} B</span></div>`
    )).join("") || "<p class='quiet'>No files yet.</p>";
  }

  async function refreshEvidence() {
    const data = await api("/api/evidence");
    $("evidence-view").innerHTML = renderMarkdown(data.text || "_No evidence yet._");
    refreshFiles();
  }

  async function refreshStatus() {
    const pre = await api("/api/preflight");
    $("preflight-list").innerHTML = (pre.checks || []).map((c) => (
      `<li>${c.ok ? "PASS" : "FAIL"} — ${escapeHtml(c.name)} <span class="quiet">${escapeHtml(c.detail || "")}</span></li>`
    )).join("");
    const stats = await api("/api/stats").catch(() => ({}));
    $("stats-list").innerHTML = [
      ["Session logs", stats.session_logs],
      ["Tool runs", stats.tool_runs],
      ["Timeline notes", stats.timeline_notes],
      ["Evidence", stats.evidence],
      ["Screenshots", stats.screenshots],
      ["Workspace", stats.workspace],
    ].map(([k, v]) => `<dt>${escapeHtml(k)}</dt><dd>${escapeHtml(v == null ? "—" : String(v))}</dd>`).join("");
  }

  let infoCache = null;
  let infoGroup = 0;
  let ctfGroup = 0;

  function isCtfGroup(g) {
    return /^CTF\b/i.test(String(g.group || ""));
  }

  function ctfNavLabel(name) {
    return String(name || "").replace(/^CTF\s+/i, "");
  }

  function infoBuckets() {
    const groups = (infoCache && infoCache.groups) || [];
    return {
      info: groups.filter((g) => !isCtfGroup(g)),
      ctf: groups.filter(isCtfGroup),
    };
  }

  function renderCheatCards(groups, q, target) {
    return groups.map((g) => {
      const tools = g.tools.filter((t) => {
        const blob = `${t.name} ${t.bin} ${t.blurb} ${t.syntax} ${(t.options || []).join(" ")} ${(t.examples || []).join(" ")}`.toLowerCase();
        return !q || blob.includes(q);
      });
      if (!tools.length) return `<p class="quiet">No tools in this group match the filter.</p>`;
      const cards = tools.map((t) => {
        const opts = (t.options || []).map((o) => `<li>${escapeHtml(o)}</li>`).join("");
        const ex = (t.examples || []).map((e) => `<code>${escapeHtml(e.replaceAll("$TARGET", target))}</code>`).join("");
        return `<article class="info-card">
          <header><h3>${escapeHtml(t.name)}</h3><span class="badge">${escapeHtml(t.bin)}</span></header>
          <p class="blurb">${escapeHtml(t.blurb)}</p>
          <pre class="syntax">${escapeHtml(t.syntax)}</pre>
          <ul>${opts}</ul>
          <div class="examples">${ex}</div>
        </article>`;
      }).join("");
      return `<section class="info-group"><h2>${escapeHtml(g.group)}</h2>${cards}</section>`;
    }).join("");
  }

  async function ensureInfoCache() {
    if (!infoCache) infoCache = await api("/api/info");
    return infoCache;
  }

  function wireGroupNav(nav, stateKey, onChange) {
    if (!nav || nav.dataset.ready) return;
    nav.addEventListener("click", (e) => {
      const btn = e.target.closest("[data-info-g]");
      if (!btn) return;
      if (stateKey === "ctf") ctfGroup = Number(btn.dataset.infoG);
      else infoGroup = Number(btn.dataset.infoG);
      [...nav.children].forEach((b, i) => b.classList.toggle("active", i === Number(btn.dataset.infoG)));
      onChange();
    });
    nav.dataset.ready = "1";
  }

  async function renderInfo() {
    const cache = await ensureInfoCache();
    const groups = infoBuckets().info;
    const q = ($("info-search").value || "").toLowerCase();
    const target = cache.target || "$TARGET";
    const nav = $("info-nav");
    if (nav && !nav.dataset.ready) {
      nav.innerHTML = groups.map((g, i) => (
        `<button type="button" data-info-g="${i}" class="${i === 0 ? "active" : ""}">${escapeHtml(g.group)}</button>`
      )).join("");
      wireGroupNav(nav, "info", renderInfo);
    }
    const idx = Math.min(infoGroup, Math.max(0, groups.length - 1));
    $("info-groups").innerHTML = renderCheatCards(groups.filter((_, i) => i === idx), q, target);
  }

  async function renderCtf() {
    const cache = await ensureInfoCache();
    const groups = infoBuckets().ctf;
    const q = ($("ctf-search").value || "").toLowerCase();
    const target = cache.target || "$TARGET";
    const nav = $("ctf-nav");
    if (nav && !nav.dataset.ready) {
      nav.innerHTML = groups.map((g, i) => (
        `<button type="button" data-info-g="${i}" class="${i === 0 ? "active" : ""}">${escapeHtml(ctfNavLabel(g.group))}</button>`
      )).join("");
      wireGroupNav(nav, "ctf", renderCtf);
    }
    const idx = Math.min(ctfGroup, Math.max(0, groups.length - 1));
    $("ctf-groups").innerHTML = renderCheatCards(groups.filter((_, i) => i === idx), q, target);
  }

  async function loadTools() {
    const data = await api("/api/tools");
    state.tools = data;
    state.toolsLoaded = true;
    const nav = $("tool-nav");
    nav.innerHTML = data.groups.map((g, i) => (
      `<button type="button" data-g="${i}" class="${i === 0 ? "active" : ""}">${escapeHtml(g.name)}</button>`
    )).join("");
    showGroup(0);
  }

  function showGroup(index) {
    const group = state.tools.groups[index];
    [...$("tool-nav").children].forEach((btn, i) => btn.classList.toggle("active", i === index));
    $("tool-group-title").textContent = group.name;
    $("tool-group-blurb").textContent = group.blurb;
    $("tool-form").classList.add("hidden");
    $("tool-list").innerHTML = group.tools.map((t) => (
      `<div class="tool-card">
        <div><div class="name">${escapeHtml(t.name)}</div><div class="quiet">${escapeHtml(t.summary || "")}</div></div>
        <div>
          <span class="badge ${t.installed ? "" : "missing"}">${t.installed ? (t.bin || "ready") : "not installed"}</span>
          <button type="button" class="btn ghost" data-tool="${escapeHtml(t.id)}">Use</button>
        </div>
      </div>`
    )).join("");
  }

  function openTool(id) {
    let found = null;
    for (const g of state.tools.groups) {
      found = g.tools.find((t) => t.id === id);
      if (found) break;
    }
    if (!found) return;
    state.currentTool = found;
    $("tool-form").classList.remove("hidden");
    $("tool-name").textContent = found.name;
    $("tool-summary").textContent = found.summary || "";
    $("tool-purpose").value = found.purpose || "";
    $("tool-target").value = state.tools.target || "";
    $("tool-port").value = found.kind === "nmap-port" ? (state.tools.port || "") : "";
    $("tool-missing").classList.toggle("hidden", found.installed);
    const fields = $("tool-fields");
    const lists = state.tools.wordlists || [];
    fields.innerHTML = (found.fields || []).map((f) => {
      let def = f.default || "";
      if (def.includes("{target}") && state.tools.target) def = def.replaceAll("{target}", state.tools.target);
      if (f.name === "wordlist") {
        if (def && lists.indexOf(def) === -1 && !lists.some((w) => w.replace(/\\/g, "/") === def.replace(/\\/g, "/"))) {
          const match = lists.find((w) => w.endsWith(def.replace(/\\/g, "/").split("/").pop()));
          def = match || lists[0] || "";
        } else if (!def && lists[0]) {
          def = lists[0];
        }
        return `<label>${escapeHtml(f.label)}${wordlistSelectHtml(lists, def)}</label>`;
      }
      return `<label>${escapeHtml(f.label)}<input data-field="${escapeHtml(f.name)}" value="${escapeHtml(def)}"></label>`;
    }).join("");
    bindWordlistSelect();
    $("tool-out").textContent = "";
    $("tool-cmd-preview").textContent = "";
    $("tool-copy").value = "";
    $("tool-extra").value = "";
    const prefs = loadSettings();
    if ($("tool-notes")) $("tool-notes").checked = !!prefs.includeToolNotes;
    if ($("tool-notes-cmd")) $("tool-notes-cmd").checked = prefs.includeToolCmd !== false;
    if ($("tool-notes-findings")) $("tool-notes-findings").checked = prefs.includeToolFindings !== false;
    syncNotesOptions();
    if (found.kind === "custom") {
      $("tool-cmd").value = "";
      $("tool-copy").value = "";
      $("tool-cmd-preview").textContent = "Type the full command in the Command box.";
      state.cmdDirty = true;
      return;
    }
    state.cmdDirty = false;
    previewCommand(true);
  }

  function wordlistLabel(path) {
    const parts = String(path).replace(/\\/g, "/").split("/");
    if (parts.length >= 2) return parts.slice(-2).join("/");
    return path;
  }

  function wordlistSelectHtml(lists, selected) {
    if (!lists.length) {
      return `<select data-field="wordlist" id="tool-wordlist">
        <option value="__custom__" selected>Custom path…</option>
      </select>
      <input data-field="wordlist_custom" id="tool-wordlist-custom" placeholder="/path/to/wordlist.txt">`;
    }
    const groups = new Map();
    for (const w of lists) {
      const norm = String(w).replace(/\\/g, "/");
      const slash = norm.lastIndexOf("/");
      const group = slash > 0 ? norm.slice(0, slash) : "Other";
      if (!groups.has(group)) groups.set(group, []);
      groups.get(group).push(w);
    }
    let html = `<select data-field="wordlist" id="tool-wordlist">`;
    for (const [group, items] of groups) {
      const gLabel = group.replace(/\\/g, "/").split("/").slice(-3).join("/");
      html += `<optgroup label="${escapeHtml(gLabel)}">`;
      for (const w of items) {
        const sel = w === selected ? " selected" : "";
        html += `<option value="${escapeHtml(w)}"${sel}>${escapeHtml(wordlistLabel(w))}</option>`;
      }
      html += `</optgroup>`;
    }
    html += `<option value="__custom__">Custom path…</option></select>
      <input data-field="wordlist_custom" id="tool-wordlist-custom" class="hidden" placeholder="/path/to/wordlist.txt">`;
    return html;
  }

  function bindWordlistSelect() {
    const sel = $("tool-wordlist");
    const custom = $("tool-wordlist-custom");
    if (!sel || !custom) return;
    const toggle = () => {
      const isCustom = sel.value === "__custom__";
      custom.classList.toggle("hidden", !isCustom);
      if (isCustom) custom.focus();
    };
    sel.addEventListener("change", toggle);
    toggle();
  }

  function toolFields() {
    const fields = {};
    $("tool-fields").querySelectorAll("[data-field]").forEach((el) => {
      fields[el.getAttribute("data-field")] = el.value;
    });
    if (fields.wordlist === "__custom__") {
      fields.wordlist = (fields.wordlist_custom || "").trim();
    }
    delete fields.wordlist_custom;
    fields.target = $("tool-target").value.trim();
    fields.port = $("tool-port").value.trim();
    return fields;
  }

  function notesIncludePayload() {
    const include = !!($("tool-notes") && $("tool-notes").checked);
    return {
      include_notes: include,
      include_command: !!(include && $("tool-notes-cmd") && $("tool-notes-cmd").checked),
      include_findings: !!(include && $("tool-notes-findings") && $("tool-notes-findings").checked),
      include_txt: !!($("tool-capture-txt") && $("tool-capture-txt").checked),
    };
  }

  function syncNotesOptions() {
    const extra = $("tool-notes-extra");
    if (!extra || !$("tool-notes")) return;
    extra.classList.toggle("hidden", !$("tool-notes").checked);
  }

  function setToolRunning(running) {
    state.toolRunning = running;
    $("btn-tool-run").disabled = running;
    $("btn-tool-stop").disabled = !running;
  }

  let previewTimer = null;
  function schedulePreview() {
    clearTimeout(previewTimer);
    previewTimer = setTimeout(() => previewCommand(true).catch(() => {}), 80);
  }

  function teeCopy(cmd, outFile) {
    const dest = outFile || "logs/tool.txt";
    if (!cmd) return "";
    if (cmd.includes("| tee ") || cmd.endsWith("| tee")) return cmd;
    const wantTxt = !!($("tool-capture-txt") && $("tool-capture-txt").checked);
    if (!wantTxt || state.osName === "nt") return cmd;
    return `${cmd} | tee "${dest}"`;
  }

  async function previewCommand(force) {
    if (!state.currentTool) return;
    if (state.cmdDirty && !force) return;
    try {
      const data = await api("/api/tools/preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          id: state.currentTool.id,
          extra: $("tool-extra").value,
          fields: toolFields(),
          include_txt: !!($("tool-capture-txt") && $("tool-capture-txt").checked),
        }),
      });
      state.applyingPreview = true;
      $("tool-cmd").value = data.command || "";
      $("tool-copy").value = data.copy_command || teeCopy(data.command, data.output_file);
      $("tool-cmd-preview").textContent = data.output_file ? "saves " + data.output_file : "";
      if (data.os_name) state.osName = data.os_name;
      state.lastOutFile = data.output_file || state.lastOutFile;
      state.applyingPreview = false;
      if (force) state.cmdDirty = false;
    } catch (err) {
      state.applyingPreview = false;
      $("tool-cmd-preview").textContent = err.message;
    }
  }

  async function runTool(ev) {
    ev.preventDefault();
    if (!state.currentTool || state.toolRunning) return;
    const payload = {
      id: state.currentTool.id,
      purpose: $("tool-purpose").value,
      extra: $("tool-extra").value,
      fields: toolFields(),
      command: $("tool-cmd").value,
      command_edited: state.cmdDirty,
      ...notesIncludePayload(),
    };
    $("tool-out").textContent = "";
    setToolRunning(true);
    try {
      const res = await fetch("/api/tools/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ error: res.statusText }));
        $("tool-out").textContent = err.error || "failed";
        return;
      }
      const reader = res.body.getReader();
      const dec = new TextDecoder();
      let buf = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        const parts = buf.split("\n\n");
        buf = parts.pop();
        for (const part of parts) {
          const line = part.replace(/^data: /, "");
          if (!line) continue;
          let msg;
          try { msg = JSON.parse(line); } catch { continue; }
          if (msg.type === "command") {
            $("tool-cmd-preview").textContent = msg.command || "";
            if (msg.copy_command) $("tool-copy").value = msg.copy_command;
            if (msg.output_file) $("tool-cmd-preview").textContent = (msg.command || "") + "  →  " + msg.output_file;
          }
          if (msg.type === "line") $("tool-out").textContent += msg.text;
          if (msg.type === "done") {
            $("tool-out").textContent += `\n[exit ${msg.exit_code}] ${msg.output_file || ""}\n`;
            setToolRunning(false);
            if (msg.notes != null) applyNotesText(msg.notes);
          }
          if (msg.type === "error") {
            $("tool-out").textContent += `\n[-] ${msg.error}`;
            setToolRunning(false);
          }
          $("tool-out").scrollTop = $("tool-out").scrollHeight;
        }
      }
      loadNotes();
    } finally {
      setToolRunning(false);
    }
  }

  async function stopTool() {
    if (!state.toolRunning) return;
    try {
      await api("/api/tools/stop", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      });
      $("tool-out").textContent += "\n[stop requested]\n";
    } catch (err) {
      $("tool-out").textContent += `\n[-] ${err.message}\n`;
    }
  }

  function onReportInput() {
    state.reportDirty = true;
    $("report-save-state").textContent = "unsaved";
    $("report-view").innerHTML = renderMarkdown($("report-editor").value);
  }

  async function saveReport() {
    await api("/api/report", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: $("report-editor").value }),
    });
    state.reportDirty = false;
    $("report-save-state").textContent = "saved";
  }

  async function loadReport() {
    const data = await api("/api/report");
    $("report-editor").value = data.text || "";
    state.reportDirty = false;
    $("report-save-state").textContent = "saved";
    $("report-view").innerHTML = renderMarkdown(data.text || "_Insert the template, then write here._");
  }

  function bindImagePaste(textarea) {
    textarea.addEventListener("paste", async (e) => {
      const items = e.clipboardData && e.clipboardData.items;
      if (!items) return;
      for (const item of items) {
        if (!item.type || !item.type.startsWith("image/")) continue;
        e.preventDefault();
        const file = item.getAsFile();
        if (!file) continue;
        const reader = new FileReader();
        reader.onload = async () => {
          try {
            const data = await api("/api/image", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                mime: file.type,
                data: reader.result,
                dest: textarea.id === "notes-editor" ? "notes" : "report",
              }),
            });
            insertAtCursor(textarea, `\n![pasted image](${data.path})\n`);
            if (textarea.id === "report-editor") onReportInput();
            if (textarea.id === "notes-editor") onNotesInput();
          } catch (err) {
            alert(err.message);
          }
        };
        reader.readAsDataURL(file);
        return;
      }
    });
  }

  function fillLabConfig(c) {
    if (!$("lab-target-ip")) return;
    $("lab-machine").value = c.machine_name || "";
    $("lab-student").value = c.student_id || "";
    $("lab-target-ip").value = c.target_ip || "";
    $("lab-target-port").value = c.target_port || "";
  }

  function applySavedTarget(config) {
    if (state.tools) {
      state.tools.target = config.target_ip || "";
      state.tools.port = config.target_port || "";
    }
    if ($("tool-target") && document.activeElement !== $("tool-target")) {
      $("tool-target").value = config.target_ip || "";
    }
    if ($("tool-port") && document.activeElement !== $("tool-port") && state.currentTool && state.currentTool.kind === "nmap-port") {
      $("tool-port").value = config.target_port || "";
    }
  }

  function wire() {
    document.querySelectorAll(".rail-btn").forEach((btn) => {
      btn.addEventListener("click", () => setTab(btn.dataset.tab));
    });
    $("lab-config-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      const errEl = $("lab-config-error");
      const msgEl = $("lab-config-msg");
      errEl.classList.add("hidden");
      errEl.textContent = "";
      msgEl.textContent = "";
      try {
        const data = await api("/api/lab/target", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            student_id: $("lab-student").value,
            machine_name: $("lab-machine").value,
            target_ip: $("lab-target-ip").value,
            target_port: $("lab-target-port").value,
          }),
        });
        fillLabConfig(data.config || {});
        applySavedTarget(data.config || {});
        await refreshState();
        if (!state.dirty) await loadNotes();
        if (!state.reportDirty) await loadReport();
        const bits = ["Saved. Header and Tools defaults now use the new values."];
        if (data.renamed && data.folder) bits.push("Lab folder is now " + data.folder + ".");
        if (data.archives && data.archives.length) {
          bits.push("Renamed " + data.archives.length + " export archive(s).");
        }
        msgEl.textContent = bits.join(" ");
      } catch (err) {
        errEl.classList.remove("hidden");
        errEl.textContent = err.message;
      }
    });
    $("notes-editor").addEventListener("input", onNotesInput);
    $("notes-editor").addEventListener("keydown", (e) => {
      if (e.key === "Tab") {
        e.preventDefault();
        insertAtCursor($("notes-editor"), "    ");
      }
    });
    $("btn-save").addEventListener("click", () => saveNotes().catch((err) => alert(err.message)));
    $("btn-help").addEventListener("click", () => setTab("help"));
    $("btn-session-menu").addEventListener("click", (e) => {
      e.stopPropagation();
      $("session-pop").classList.toggle("hidden");
    });
    document.addEventListener("click", () => $("session-pop").classList.add("hidden"));
    $("session-pop").addEventListener("click", (e) => e.stopPropagation());
    async function setSession(action) {
      try {
        await api("/api/session", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ action }),
        });
        $("session-pop").classList.add("hidden");
        await refreshState();
      } catch (err) {
        alert(err.message);
      }
    }
    $("btn-session-pause").addEventListener("click", () => setSession("pause"));
    $("btn-session-resume").addEventListener("click", () => setSession("resume"));
    document.querySelectorAll("[data-notes-view]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const mode = btn.getAttribute("data-notes-view");
        applyNotesView(mode);
        saveSettings({ notesView: mode });
        if ($("set-notes-view")) $("set-notes-view").value = mode;
      });
    });
    CATS.forEach((cat) => {
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = "chip" + (cat === state.category ? " active" : "");
      chip.textContent = cat === "NONE" ? "None" : cat;
      chip.addEventListener("click", () => {
        state.category = cat;
        document.querySelectorAll("#note-cats .chip").forEach((c) => c.classList.toggle("active", c === chip));
      });
      $("note-cats").appendChild(chip);
    });
    if ($("set-category")) {
      $("set-category").innerHTML = CATS.map((cat) =>
        `<option value="${cat}">${cat === "NONE" ? "None" : cat}</option>`
      ).join("");
    }
    $("btn-stamp").addEventListener("click", async () => {
      const data = await api("/api/notes/stamp", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ category: state.category }),
      });
      insertAtCursor($("notes-editor"), data.heading);
    });
    $("btn-heading").addEventListener("click", () => insertAtCursor($("notes-editor"), "## "));
    $("btn-code").addEventListener("click", () => {
      const open = "```python\n";
      const close = "\n```";
      insertAtCursor($("notes-editor"), open + close, open.length);
    });
    $("btn-notes-example").addEventListener("click", () => {
      window.open("/examples/view?doc=notes", "_blank", "noopener");
    });
    $("btn-report-example").addEventListener("click", () => {
      window.open("/examples/view?doc=report", "_blank", "noopener");
    });
    $("btn-list").addEventListener("click", () => insertAtCursor($("notes-editor"), "- "));
    $("btn-append").addEventListener("click", async () => {
      const body = $("quick-body").value;
      const data = await api("/api/notes/append", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ category: state.category, body }),
      });
      $("quick-body").value = "";
      $("notes-editor").value = data.text;
      onNotesInput();
      state.dirty = false;
      $("save-state").textContent = "saved";
    });
    $("quick-body").addEventListener("keydown", (e) => {
      if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
        e.preventDefault();
        $("btn-append").click();
      }
    });
    $("setup-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      $("setup-error").hidden = true;
      const fd = new FormData($("setup-form"));
      try {
        await api("/api/config", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            student_id: fd.get("student_id"),
            machine_name: fd.get("machine_name"),
            target_ip: fd.get("target_ip"),
            target_port: fd.get("target_port"),
            research_project: fd.get("research_project"),
          }),
        });
        await chooseLabDone();
      } catch (err) {
        $("setup-error").hidden = false;
        $("setup-error").textContent = err.message;
      }
    });
    $("lab-select").addEventListener("change", () => {
      state.labPick = $("lab-select").value;
    });
    $("btn-open-lab").addEventListener("click", async () => {
      $("setup-error").hidden = true;
      try {
        await api("/api/labs/select", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ id: $("lab-select").value }),
        });
        await chooseLabDone();
      } catch (err) {
        $("setup-error").hidden = false;
        $("setup-error").textContent = err.message;
      }
    });
    $("btn-dismiss-setup").addEventListener("click", async () => {
      try {
        await api("/api/labs/ready", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: "{}",
        });
        await chooseLabDone();
      } catch (err) {
        $("setup-error").hidden = false;
        $("setup-error").textContent = err.message;
      }
    });
    $("btn-switch-lab").addEventListener("click", () => {
      state.labChosen = false;
      $("setup-overlay").classList.remove("hidden");
      refreshState().catch(() => {});
    });
    $("log-select").addEventListener("change", () => {
      state.logName = $("log-select").value;
      state.logOffset = 0;
      refreshLogs(true);
    });
    $("btn-log-refresh").addEventListener("click", () => refreshLogs(true));
    $("btn-new-terminal").addEventListener("click", async () => {
      try {
        const data = await api("/api/terminal/spawn", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: "{}",
        });
        if (data.file) {
          state.logName = data.file;
          state.logOffset = 0;
          await refreshLogs(true);
        }
      } catch (err) {
        alert(err.message);
      }
    });
    $("tool-nav").addEventListener("click", (e) => {
      const btn = e.target.closest("[data-g]");
      if (btn) showGroup(Number(btn.dataset.g));
    });
    $("tool-list").addEventListener("click", (e) => {
      const btn = e.target.closest("[data-tool]");
      if (btn) openTool(btn.dataset.tool);
    });
    $("tool-form").addEventListener("submit", (e) => runTool(e).catch((err) => {
      $("tool-out").textContent = err.message;
      setToolRunning(false);
    }));
    $("btn-tool-stop").addEventListener("click", () => stopTool().catch((err) => {
      $("tool-out").textContent += `\n[-] ${err.message}\n`;
    }));
    $("btn-tool-rebuild").addEventListener("click", () => {
      state.cmdDirty = false;
      previewCommand(true).catch(() => {});
    });
    if ($("tool-notes")) {
      $("tool-notes").addEventListener("change", syncNotesOptions);
    }
    if ($("tool-capture-txt")) {
      $("tool-capture-txt").addEventListener("change", () => schedulePreview());
    }
    $("btn-tool-send").addEventListener("click", async () => {
      const cmd = ($("tool-cmd").value || "").trim();
      if (!cmd) {
        alert("Command is empty.");
        return;
      }
      try {
        const data = await api("/api/tools/inject", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            id: state.currentTool ? state.currentTool.id : "",
            purpose: $("tool-purpose").value,
            extra: $("tool-extra").value,
            fields: toolFields(),
            command: cmd,
            command_edited: state.cmdDirty,
            ...notesIncludePayload(),
          }),
        });
        if (data.copy_command) $("tool-copy").value = data.copy_command;
        if (data.output_file) {
          state.lastOutFile = data.output_file;
          $("tool-cmd-preview").textContent = "saves " + data.output_file;
        }
        if (data.notes != null) applyNotesText(data.notes);
        $("tool-out").textContent += "\n[sent to logged terminal]\n" + (data.send_command || cmd) + "\n";
        if (data.output_file) $("tool-out").textContent += "[capture] " + data.output_file + "\n";
        if (data.pending_id) {
          $("tool-out").textContent += "[notes] waiting for the command to finish so findings can be parsed\n";
          pollPendingNotes(data.pending_id);
        }
        $("tool-out").scrollTop = $("tool-out").scrollHeight;
      } catch (err) {
        alert(err.message);
      }
    });
    async function pollPendingNotes(pendingId) {
      const deadline = Date.now() + 45 * 60 * 1000;
      while (Date.now() < deadline) {
        await new Promise((r) => setTimeout(r, 1000));
        try {
          const data = await api(`/api/tools/pending?id=${encodeURIComponent(pendingId)}`);
          if (!data.done) continue;
          if (data.notes != null && !state.dirty) applyNotesText(data.notes);
          if (data.error) {
            $("tool-out").textContent += `[findings] ${data.error}\n`;
          } else if (data.summary) {
            $("tool-out").textContent += `[findings] ${data.summary}\n`;
          } else {
            $("tool-out").textContent += "[findings] parsed\n";
          }
          $("tool-out").scrollTop = $("tool-out").scrollHeight;
          return;
        } catch (err) {
          $("tool-out").textContent += `[findings] ${err.message}\n`;
          $("tool-out").scrollTop = $("tool-out").scrollHeight;
          return;
        }
      }
    }
    function onToolFieldsChanged(e) {
      if (state.applyingPreview) return;
      const id = e.target && e.target.id;
      const isField = e.target && e.target.hasAttribute && e.target.hasAttribute("data-field");
      if (id === "tool-purpose" || id === "tool-notes" || id === "tool-notes-cmd" || id === "tool-notes-findings") return;
      if (id === "tool-copy") return;
      if (id === "tool-cmd") {
        state.cmdDirty = true;
        $("tool-copy").value = teeCopy($("tool-cmd").value.trim(), state.lastOutFile);
        return;
      }
      if (id === "tool-target" || id === "tool-port" || id === "tool-extra" || isField) {
        state.cmdDirty = false;
        schedulePreview();
      }
    }
    $("tool-form").addEventListener("input", onToolFieldsChanged);
    $("tool-form").addEventListener("change", onToolFieldsChanged);
    $("info-search").addEventListener("input", () => renderInfo());
    $("ctf-search").addEventListener("input", () => renderCtf());
    $("source-na").addEventListener("change", () => {
      $("evidence-source").disabled = $("source-na").checked;
      if ($("source-na").checked) $("evidence-source").value = "";
    });
    function parseNums(text, base) {
      const cleaned = String(text || "")
        .replace(/[\[\](){}<>'"]/g, " ")
        .replace(/0x/gi, " ");
      const tokens = cleaned.split(/[\s,;|]+/).map((t) => t.trim()).filter(Boolean);
      const re = base === 16 ? /^-?[0-9a-f]+$/i : /^-?\d+$/;
      return tokens.map((t) => (re.test(t) ? parseInt(t, base) : NaN));
    }
    $("btn-conv-from-dec").addEventListener("click", () => {
      const nums = parseNums($("conv-decimal").value, 10);
      if (!nums.length || nums.some((n) => Number.isNaN(n))) {
        $("conv-text").value = "Invalid decimal list";
        return;
      }
      $("conv-text").value = nums.map((n) => String.fromCharCode(n)).join("");
    });
    $("btn-conv-from-hex").addEventListener("click", () => {
      const nums = parseNums($("conv-hex").value, 16);
      if (!nums.length || nums.some((n) => Number.isNaN(n))) {
        $("conv-text").value = "Invalid hex";
        return;
      }
      $("conv-text").value = nums.map((n) => String.fromCharCode(n)).join("");
    });
    $("btn-conv-to-dec").addEventListener("click", () => {
      const text = $("conv-text").value;
      $("conv-decimal").value = [...text].map((c) => c.charCodeAt(0)).join(" ");
      $("conv-hex").value = [...text].map((c) => c.charCodeAt(0).toString(16).padStart(2, "0")).join(" ");
    });
    $("evidence-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      const fd = new FormData($("evidence-form"));
      const data = await api("/api/evidence", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          phase: fd.get("phase"),
          description: fd.get("description"),
          source: fd.get("source"),
          source_na: $("source-na").checked,
        }),
      });
      e.target.reset();
      $("source-na").checked = false;
      $("evidence-source").disabled = false;
      refreshEvidence();
      loadNotes();
      if (data.finding) {
        if (state.reportDirty) {
          applyFindingsBlock(data.finding + "\n");
        } else if (data.report != null) {
          $("report-editor").value = data.report;
          onReportInput();
          state.reportDirty = false;
          $("report-save-state").textContent = "saved";
        }
      }
    });
    $("report-editor").addEventListener("input", onReportInput);
    $("report-editor").addEventListener("keydown", (e) => {
      if (e.key === "Tab") {
        e.preventDefault();
        insertAtCursor($("report-editor"), "    ");
      }
    });
    bindImagePaste($("report-editor"));
    bindImagePaste($("notes-editor"));
    $("btn-save-report").addEventListener("click", () => saveReport().catch((err) => alert(err.message)));
    $("report-display").addEventListener("change", () => {
      const mode = $("report-display").value;
      const wrap = $("report-split");
      wrap.classList.remove("mode-write", "mode-view", "mode-both");
      wrap.classList.add("mode-" + mode);
    });
    $("btn-report-reset").addEventListener("click", async () => {
      if ($("report-editor").value.trim() && !confirm("Replace the whole report with a blank template?")) return;
      const data = await api("/api/report", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
      $("report-editor").value = data.text || "";
      onReportInput();
      state.reportDirty = false;
      $("report-save-state").textContent = "saved";
    });
    function applyFindingsBlock(block) {
      const ed = $("report-editor");
      const text = ed.value;
      const already = new Set();
      const idRe = /\bE-\d+\b/gi;
      let m;
      while ((m = idRe.exec(text))) already.add(m[0].toUpperCase());
      const lines = String(block || "").split("\n");
      const fresh = lines.filter((line) => {
        const hit = line.match(/\bE-\d+\b/i);
        if (!hit) return line.trim().length > 0;
        return !already.has(hit[0].toUpperCase());
      });
      const hasNew = fresh.some((line) => /^\s*-\s/.test(line) && /\bE-\d+\b/i.test(line));
      if (!hasNew) return false;
      const chunk = fresh.join("\n").replace(/\n+$/, "") + "\n";
      const marker = "## Findings";
      const i = text.indexOf(marker);
      if (i < 0) {
        ed.value = text + (text.endsWith("\n") || !text ? "" : "\n") + "\n## Findings\n\n" + chunk;
        onReportInput();
        return true;
      }
      const after = text.indexOf("\n", i);
      const start = after >= 0 ? after + 1 : text.length;
      const rest = text.slice(start);
      const next = rest.search(/^## /m);
      const insertAt = next < 0 ? text.length : start + next;
      const head = text.slice(0, insertAt).replace(/\s+$/, "") + "\n\n";
      let tail = text.slice(insertAt);
      if (tail.startsWith("##")) tail = "\n" + tail;
      ed.value = head + chunk + tail;
      onReportInput();
      return true;
    }
    $("btn-report-insert").addEventListener("click", async () => {
      try {
        const data = await api("/api/report/findings", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
        if (data.report && !state.reportDirty) {
          $("report-editor").value = data.report;
          onReportInput();
          state.reportDirty = false;
          $("report-save-state").textContent = "saved";
          return;
        }
        if (!applyFindingsBlock(data.block || "")) {
          alert("No new evidence IDs to insert. Existing E-numbers are already in the report.");
        }
      } catch (err) {
        alert(err.message);
      }
    });
    $("btn-validate").addEventListener("click", async () => {
      const data = await api("/api/validate", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
      $("validate-out").textContent = data.text || "";
    });
    function rebuildScp() {
      const host = ($("pwn-host").value || "htb-xxxxx.htb-cloud.com").trim();
      const user = ($("pwn-user").value || "htb-username").trim();
      const path = ($("pwn-path").value || "/home/USER/.../file.zip").trim().replace(/\\/g, "/");
      const remote = user + "@" + host + ":" + path;
      $("zip-scp").textContent =
        "Windows Command Prompt:\n" +
        "scp " + remote + " %USERPROFILE%\\Downloads\\\n\n" +
        "Windows PowerShell:\n" +
        "scp " + remote + " $env:USERPROFILE\\Downloads\\";
    }
    function showExport(data, dest, wormhole) {
      dest.textContent = "Saved: " + (data.file || "") + (data.copied && data.copied.length ? "  [" + data.copied.join(", ") + "]" : "");
      if (wormhole) {
        dest.textContent += "  Upload that file at https://wormhole.app for one download (not SCP).";
      } else if (data.file) {
        $("pwn-path").value = data.file;
        rebuildScp();
      }
    }
    ["pwn-host", "pwn-user", "pwn-path"].forEach((id) => {
      $(id).addEventListener("input", rebuildScp);
    });
    $("btn-zip").addEventListener("click", async () => {
      try {
        const data = await api("/api/backup", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            hostname: $("pwn-host").value,
            username: $("pwn-user").value,
          }),
        });
        showExport(data, $("zip-out"));
      } catch (err) {
        $("zip-out").textContent = err.message;
      }
    });
    $("btn-7z").addEventListener("click", async () => {
      const password = $("zip-pass").value;
      if (!password) {
        $("zip7-out").textContent = "Set a 7z password first.";
        return;
      }
      try {
        const data = await api("/api/backup", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            encrypt: true,
            password,
            hostname: $("pwn-host").value,
            username: $("pwn-user").value,
          }),
        });
        showExport(data, $("zip7-out"), true);
      } catch (err) {
        $("zip7-out").textContent = err.message;
      }
    });
    if ($("btn-screenshot")) $("btn-screenshot").addEventListener("click", async () => {
      const description = ($("shot-desc").value || "").trim();
      if (!description) {
        $("shot-out").textContent = "Description is required.";
        return;
      }
      const btn = $("btn-screenshot");
      btn.disabled = true;
      try {
        for (let n = 3; n > 0; n -= 1) {
          $("shot-out").textContent = `Capturing in ${n}… switch to the terminal if that is the shot you want.`;
          await new Promise((r) => setTimeout(r, 1000));
        }
        $("shot-out").textContent = "Capturing…";
        const data = await api("/api/screenshot", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            milestone: $("shot-milestone").value,
            description,
          }),
        });
        $("shot-out").textContent = "Saved " + (data.file || "screenshot");
        if (data.notes != null && !state.dirty) applyNotesText(data.notes);
        refreshFiles().catch(() => {});
        refreshStatus().catch(() => {});
      } catch (err) {
        $("shot-out").textContent = err.message;
      } finally {
        btn.disabled = false;
      }
    });
    $("btn-bootstrap").addEventListener("click", async () => {
      const data = await api("/api/bootstrap", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
      alert(data.message || JSON.stringify(data));
      refreshStatus();
    });
    document.addEventListener("keydown", (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") {
        e.preventDefault();
        if ($("tab-report").classList.contains("active")) {
          saveReport().catch((err) => alert(err.message));
        } else {
          saveNotes().catch((err) => alert(err.message));
        }
      }
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "n") {
        e.preventDefault();
        $("btn-stamp").click();
      }
      if ((e.ctrlKey || e.metaKey) && e.key >= "1" && e.key <= "9") {
        e.preventDefault();
        setTab(TABS[Number(e.key) - 1]);
      }
    });
    setInterval(() => {
      if (state.dirty) saveNotes().catch(() => {});
      if (state.reportDirty) saveReport().catch(() => {});
    }, 8000);
    $("log-live").addEventListener("change", () => {
      if ($("log-live").checked && $("tab-logs").classList.contains("active")) {
        refreshLogs(true).catch(() => {});
      }
    });
    $("speed-up").addEventListener("change", () => {
      const on = !!$("speed-up").checked;
      saveSettings({ speedUp: on });
      if ($("set-speed-up")) $("set-speed-up").checked = on;
      try { localStorage.setItem("htb-speed-up", on ? "1" : "0"); } catch (err) { /* ignore */ }
      if (!on) refreshState().catch(() => {});
    });
    renderThemeGrid();
    $("theme-grid").addEventListener("click", (e) => {
      const card = e.target.closest("[data-theme]");
      if (!card) return;
      const s = saveSettings({ theme: card.dataset.theme });
      applyTheme(s.theme, s.customColors);
    });
    $("custom-colors").addEventListener("input", (e) => {
      const input = e.target.closest("[data-cvar]");
      if (!input) return;
      const s = saveSettings({ theme: "custom", customColors: { [input.dataset.cvar]: input.value } });
      applyTheme("custom", s.customColors);
    });
    $("btn-custom-reset").addEventListener("click", () => {
      const s = saveSettings({ theme: "custom", customColors: DEFAULT_CUSTOM });
      applyTheme("custom", s.customColors);
    });
    [
      ["set-start-tab", "startTab", false],
      ["set-notes-view", "notesView", false],
      ["set-category", "defaultCategory", false],
      ["set-speed-up", "speedUp", true],
      ["set-log-live", "logLive", true],
      ["set-tool-notes", "includeToolNotes", true],
      ["set-tool-cmd", "includeToolCmd", true],
      ["set-tool-findings", "includeToolFindings", true],
    ].forEach(([id, key, isCheck]) => {
      const el = $(id);
      if (!el) return;
      el.addEventListener("change", () => {
        const value = isCheck ? !!el.checked : el.value;
        saveSettings({ [key]: value });
        if (key === "notesView") applyNotesView(value);
        if (key === "speedUp") {
          if ($("speed-up")) $("speed-up").checked = value;
          try { localStorage.setItem("htb-speed-up", value ? "1" : "0"); } catch (err) { /* ignore */ }
        }
        if (key === "logLive" && $("log-live")) $("log-live").checked = value;
        if (key === "defaultCategory" && CATS.includes(value)) {
          state.category = value;
          document.querySelectorAll("#note-cats .chip").forEach((c, i) => {
            c.classList.toggle("active", CATS[i] === value);
          });
        }
        if (key === "theme") applyTheme(value);
      });
    });
    applySettings(loadSettings());
    setInterval(() => {
      if (!speedUpOn()) refreshState().catch(() => {});
      if ($("tab-logs").classList.contains("active") && $("log-live").checked) {
        refreshLogs(false).catch(() => {});
      }
    }, 2500);
  }

  wire();
  refreshState().catch((err) => {
    $("setup-overlay").classList.remove("hidden");
    $("setup-error").hidden = false;
    $("setup-error").textContent = err.message;
  });
})();
