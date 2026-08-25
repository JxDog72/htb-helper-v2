(() => {
  const TABS = ["notes", "logs", "tools", "info", "evidence", "files", "report", "convert", "status", "help"];
  const CATS = ["RECON", "ENUMERATION", "FINDING", "DEAD END", "FOOTHOLD", "PRIVESC", "FLAG", "OTHER"];

  const $ = (id) => document.getElementById(id);
  const state = {
    dirty: false,
    category: "RECON",
    logOffset: 0,
    logName: "session.log",
    tools: [],
    currentTool: null,
    follow: true,
    setupSeeded: false,
    labChosen: false,
    reportDirty: false,
  };

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
      const h = line.match(/^(#{1,4})\s+(.*)$/);
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
    if (name === "logs") refreshLogs(true);
    if (name === "files") refreshFiles();
    if (name === "evidence") refreshEvidence();
    if (name === "status") refreshStatus();
    if (name === "info") renderInfo();
    if (name === "tools") loadTools();
    if (name === "report") loadReport();
  }

  function insertAtCursor(textarea, text) {
    const start = textarea.selectionStart;
    const end = textarea.selectionEnd;
    const before = textarea.value.slice(0, start);
    const after = textarea.value.slice(end);
    textarea.value = before + text + after;
    const pos = start + text.length;
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
    const stamps = [...text.matchAll(/^### \[([^\]]+)\]/gm)].map((m) => m[1]);
    $("tape").innerHTML = stamps.map((s, i) => {
      const short = s.slice(11, 19) || s;
      return `<button type="button" data-i="${i}">${escapeHtml(short)}</button>`;
    }).join("");
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

  async function loadNotes() {
    const data = await api("/api/notes");
    $("notes-editor").value = data.text || "";
    state.dirty = false;
    $("save-state").textContent = "saved";
    $("notes-preview").innerHTML = renderMarkdown(data.text || "");
    drawTape(data.text || "");
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
    sel.innerHTML = labs.map((lab) => {
      const label = `${lab.machine_name || lab.id}  ${lab.target_ip || ""}`.trim();
      const selected = lab.id === current || lab.current ? " selected" : "";
      return `<option value="${escapeHtml(lab.id)}"${selected}>${escapeHtml(label)}</option>`;
    }).join("");
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
    $("meta-machine").textContent = (data.config && data.config.machine_name) || "—";
    $("meta-target").textContent = (data.config && data.config.target_ip) || "—";
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
    $("setup-overlay").classList.add("hidden");
    await refreshState();
    await loadNotes();
  }

  async function refreshLogs(reset) {
    const sel = $("log-select");
    const data = await api(`/api/logs?name=${encodeURIComponent(state.logName)}&offset=${reset ? 0 : state.logOffset}`);
    if (data.files) {
      const current = state.logName;
      sel.innerHTML = data.files.map((n) => `<option ${n === current ? "selected" : ""}>${escapeHtml(n)}</option>`).join("");
      if (!data.files.includes(current) && data.files[0]) {
        state.logName = data.files[0];
        sel.value = data.files[0];
      }
    }
    const view = $("log-view");
    const follow = $("log-follow").checked;
    const prevTop = view.scrollTop;
    if (reset || data.replace) {
      view.textContent = data.text || "";
      state.logOffset = data.offset || 0;
    } else if (data.text) {
      view.textContent += data.text;
      state.logOffset = data.offset;
    }
    if (follow) view.scrollTop = view.scrollHeight;
    else view.scrollTop = prevTop;
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
  async function renderInfo(filter) {
    if (!infoCache) infoCache = await api("/api/info");
    const q = (filter || $("info-search").value || "").toLowerCase();
    const target = infoCache.target || "$TARGET";
    $("info-groups").innerHTML = infoCache.groups.map((g) => {
      const tools = g.tools.filter((t) => {
        const blob = `${t.name} ${t.bin} ${t.blurb} ${t.syntax}`.toLowerCase();
        return !q || blob.includes(q);
      });
      if (!tools.length) return "";
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

  async function loadTools() {
    const data = await api("/api/tools");
    state.tools = data;
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
    $("tool-port").value = state.tools.port || "";
    $("tool-missing").classList.toggle("hidden", found.installed);
    const fields = $("tool-fields");
    const lists = state.tools.wordlists || [];
    fields.innerHTML = (found.fields || []).map((f) => {
      let def = f.default || "";
      if (f.name === "wordlist" && !def && lists[0]) def = lists[0];
      if (def.includes("{target}") && state.tools.target) def = def.replaceAll("{target}", state.tools.target);
      const list = f.name === "wordlist"
        ? ` list="wl" /><datalist id="wl">${lists.map((w) => `<option value="${escapeHtml(w)}">`).join("")}</datalist`
        : "";
      return `<label>${escapeHtml(f.label)}<input data-field="${escapeHtml(f.name)}" value="${escapeHtml(def)}"${list}></label>`;
    }).join("");
    $("tool-out").textContent = "";
  }

  async function runTool(ev) {
    ev.preventDefault();
    if (!state.currentTool) return;
    const fields = {};
    $("tool-fields").querySelectorAll("[data-field]").forEach((el) => {
      fields[el.getAttribute("data-field")] = el.value;
    });
    fields.target = $("tool-target").value.trim();
    fields.port = $("tool-port").value.trim();
    const payload = {
      id: state.currentTool.id,
      purpose: $("tool-purpose").value,
      extra: $("tool-extra").value,
      fields,
    };
    $("tool-out").textContent = "";
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
        if (msg.type === "command") $("tool-cmd-preview").textContent = msg.command;
        if (msg.type === "line") $("tool-out").textContent += msg.text;
        if (msg.type === "done") $("tool-out").textContent += `\n[exit ${msg.exit_code}] ${msg.output_file}\n${msg.summary || ""}`;
        if (msg.type === "error") $("tool-out").textContent += `\n[-] ${msg.error}`;
        $("tool-out").scrollTop = $("tool-out").scrollHeight;
      }
    }
    loadNotes();
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
              body: JSON.stringify({ mime: file.type, data: reader.result }),
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

  function wire() {
    document.querySelectorAll(".rail-btn").forEach((btn) => {
      btn.addEventListener("click", () => setTab(btn.dataset.tab));
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
        $("notes-split").classList.remove("mode-split", "mode-write", "mode-nice");
        $("notes-split").classList.add("mode-" + mode);
        document.querySelectorAll("[data-notes-view]").forEach((b) => {
          b.classList.toggle("active", b === btn);
        });
      });
    });
    CATS.forEach((cat) => {
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = "chip" + (cat === state.category ? " active" : "");
      chip.textContent = cat;
      chip.addEventListener("click", () => {
        state.category = cat;
        document.querySelectorAll(".chip").forEach((c) => c.classList.toggle("active", c.textContent === cat));
      });
      $("note-cats").appendChild(chip);
    });
    $("btn-stamp").addEventListener("click", async () => {
      const data = await api("/api/notes/stamp", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ category: state.category }),
      });
      insertAtCursor($("notes-editor"), data.heading);
    });
    $("btn-heading").addEventListener("click", () => insertAtCursor($("notes-editor"), "## "));
    $("btn-code").addEventListener("click", () => insertAtCursor($("notes-editor"), "```python\n\n```\n"));
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
    $("log-view").addEventListener("scroll", () => {
      const el = $("log-view");
      const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 48;
      $("log-follow").checked = atBottom;
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
    }));
    $("info-search").addEventListener("input", () => renderInfo());
    $("source-na").addEventListener("change", () => {
      $("evidence-source").disabled = $("source-na").checked;
      if ($("source-na").checked) $("evidence-source").value = "";
    });
    function parseNums(text, base) {
      return text.split(/[\s,;]+/).map((t) => t.trim()).filter(Boolean).map((t) => parseInt(t, base));
    }
    $("btn-conv-from-dec").addEventListener("click", () => {
      const nums = parseNums($("conv-decimal").value, 10);
      if (nums.some((n) => Number.isNaN(n))) {
        $("conv-text").value = "Invalid decimal list";
        return;
      }
      $("conv-text").value = nums.map((n) => String.fromCharCode(n)).join("");
    });
    $("btn-conv-from-hex").addEventListener("click", () => {
      const raw = $("conv-hex").value.replace(/0x/gi, " ").trim();
      const nums = parseNums(raw, 16);
      if (nums.some((n) => Number.isNaN(n))) {
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
      await api("/api/evidence", {
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
    $("btn-report").addEventListener("click", async () => {
      const data = await api("/api/report", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
      $("report-editor").value = data.text || "";
      onReportInput();
      state.reportDirty = false;
      $("report-save-state").textContent = "saved";
    });
    $("btn-validate").addEventListener("click", async () => {
      const data = await api("/api/validate", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
      $("validate-out").textContent = data.text || "";
    });
    $("btn-zip").addEventListener("click", async () => {
      const data = await api("/api/backup", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
      $("zip-out").textContent = data.file || "";
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
    setInterval(() => {
      refreshState().catch(() => {});
      if ($("tab-logs").classList.contains("active") && $("log-follow").checked) {
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
