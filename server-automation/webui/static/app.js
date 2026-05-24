// ── State ────────────────────────────────────────────────────────────────────
let SERVERS = [];
let GROUPS  = [];

// ── Helpers ──────────────────────────────────────────────────────────────────
const $  = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

function toast(msg, type = "info") {
  const t = document.createElement("div");
  t.className = `toast ${type}`;
  t.textContent = msg;
  $("#toast-container").appendChild(t);
  setTimeout(() => t.remove(), 4000);
}

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

// ── Network status pill ─────────────────────────────────────────────────────
async function refreshNetworkStatus() {
  const pill = $("#network-status");
  try {
    const { in_office, detail, local_ips } = await api("/api/network");
    if (in_office) {
      pill.className = "network-pill online";
      pill.textContent = `🟢 Office network (${local_ips.join(", ")})`;
    } else {
      pill.className = "network-pill offline";
      pill.textContent = `🔴 Off-network — actions disabled`;
    }
  } catch (e) {
    pill.className = "network-pill offline";
    pill.textContent = `🔴 ${e.message}`;
  }
}

// ── Server table ────────────────────────────────────────────────────────────
async function refreshServers() {
  const tbody = $("#server-rows");
  tbody.innerHTML = `<tr><td colspan="7" class="loading">Loading servers…</td></tr>`;
  try {
    const { servers, groups } = await api("/api/servers");
    SERVERS = servers;
    GROUPS  = groups;
    renderGroupFilter();
    renderRows();
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="7" class="loading">⚠️ ${e.message}</td></tr>`;
  }
}

function renderGroupFilter() {
  const sel = $("#group-filter");
  const current = sel.value;
  sel.innerHTML = `<option value="">— all servers —</option>` +
    GROUPS.map(g => `<option value="${g}">${g}</option>`).join("");
  sel.value = current;
}

function renderRows() {
  const tbody = $("#server-rows");
  const filter = $("#group-filter").value;
  const visible = filter
    ? SERVERS.filter(s => s.groups.includes(filter))
    : SERVERS;

  if (!visible.length) {
    tbody.innerHTML = `<tr><td colspan="7" class="loading">No servers match this filter.</td></tr>`;
    return;
  }

  tbody.innerHTML = visible.map(s => `
    <tr data-name="${s.name}">
      <td><input type="checkbox" class="row-check" value="${s.name}"></td>
      <td><span class="status-dot status-${s.status}">${s.status.toUpperCase()}</span></td>
      <td><strong>${s.name}</strong></td>
      <td>${s.ip}</td>
      <td><code>${s.mac}</code></td>
      <td>${s.groups.map(g => `<span class="group-tag">${g}</span>`).join("")}</td>
      <td class="row-actions">
        <button class="btn-wake"     data-act="wake"     data-name="${s.name}">Wake</button>
        <button class="btn-shutdown" data-act="shutdown" data-name="${s.name}">Shutdown</button>
      </td>
    </tr>
  `).join("");

  // Per-row buttons
  tbody.querySelectorAll("button[data-act]").forEach(btn => {
    btn.addEventListener("click", () => {
      const name = btn.dataset.name;
      if (btn.dataset.act === "wake") {
        doWake({ names: [name] });
      } else {
        confirmShutdown([name]);
      }
    });
  });
}

// ── Actions ─────────────────────────────────────────────────────────────────
function getSelectedNames() {
  return [...$$(".row-check:checked")].map(c => c.value);
}

async function doWake(payload) {
  try {
    const { results } = await api("/api/wake", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    results.forEach(r => {
      toast(`${r.name}: ${r.msg}`, r.ok ? "ok" : "error");
    });
    refreshActivity();
    setTimeout(refreshServers, 2000);
  } catch (e) {
    toast(`Wake failed: ${e.message}`, "error");
  }
}

async function doShutdown(payload) {
  try {
    const { results } = await api("/api/shutdown", {
      method: "POST",
      body: JSON.stringify({ ...payload, confirm: "yes" }),
    });
    results.forEach(r => {
      toast(`${r.name}: ${r.msg}`, r.ok ? "ok" : "error");
    });
    refreshActivity();
    setTimeout(refreshServers, 5000);
  } catch (e) {
    toast(`Shutdown failed: ${e.message}`, "error");
  }
}

// ── Confirmation modal ──────────────────────────────────────────────────────
let pendingShutdownNames = [];

function confirmShutdown(names) {
  if (!names.length) {
    toast("Select at least one server first.", "warn");
    return;
  }
  pendingShutdownNames = names;
  $("#modal-server-list").innerHTML =
    names.map(n => `<li><strong>${n}</strong></li>`).join("");
  $("#modal-confirm-input").value = "";
  $("#modal-backdrop").classList.remove("hidden");
  $("#modal-confirm-input").focus();
}

$("#modal-cancel").addEventListener("click", () => {
  $("#modal-backdrop").classList.add("hidden");
});

$("#modal-confirm").addEventListener("click", () => {
  if ($("#modal-confirm-input").value !== "yes") {
    toast("Type 'yes' to confirm.", "warn");
    return;
  }
  $("#modal-backdrop").classList.add("hidden");
  doShutdown({ names: pendingShutdownNames });
});

// ── Activity log polling ────────────────────────────────────────────────────
async function refreshActivity() {
  try {
    const { entries } = await api("/api/activity");
    const pane = $("#activity-log");
    if (!entries.length) {
      pane.innerHTML = `<div class="log-empty">No activity yet.</div>`;
      return;
    }
    pane.innerHTML = entries.map(e => `
      <div class="log-entry">
        <span class="log-ts">${e.ts}</span>
        <span class="log-${e.level}">[${e.level.toUpperCase()}]</span>
        ${e.msg}
      </div>
    `).join("");
  } catch (e) { /* ignore */ }
}

// ── Wire up controls ────────────────────────────────────────────────────────
$("#group-filter").addEventListener("change", renderRows);
$("#refresh").addEventListener("click", () => {
  refreshServers();
  refreshNetworkStatus();
});

$("#header-check").addEventListener("change", (e) => {
  $$(".row-check").forEach(c => { c.checked = e.target.checked; });
});
$("#select-all").addEventListener("click", () => {
  $$(".row-check").forEach(c => { c.checked = true; });
  $("#header-check").checked = true;
});
$("#select-none").addEventListener("click", () => {
  $$(".row-check").forEach(c => { c.checked = false; });
  $("#header-check").checked = false;
});

$("#wake-btn").addEventListener("click", () => {
  const names = getSelectedNames();
  if (!names.length) {
    toast("Select at least one server first.", "warn");
    return;
  }
  doWake({ names });
});

$("#shutdown-btn").addEventListener("click", () => {
  confirmShutdown(getSelectedNames());
});

// ── Initial load + periodic refresh ─────────────────────────────────────────
refreshNetworkStatus();
refreshServers();
refreshActivity();

setInterval(refreshNetworkStatus, 15000);  // every 15s
setInterval(refreshServers,       30000);  // every 30s (ping is slow)
setInterval(refreshActivity,       3000);  // every 3s
