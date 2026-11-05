const state = { status: "all" };

const healthRoot = document.querySelector("#health");
const statsRoot = document.querySelector("#stats");
const logsRoot = document.querySelector("#logs");
const configRoot = document.querySelector("#config");
const runStatus = document.querySelector("#run-status");
const folderResult = document.querySelector("#folder-result");

function cell(text) {
  const td = document.createElement("td");
  td.textContent = text || "—";
  return td;
}

function card(label, value, detail, stateName) {
  const article = document.createElement("article");
  article.className = "card" + (stateName ? " state-" + stateName : "");
  const span = document.createElement("span");
  span.textContent = label;
  const strong = document.createElement("strong");
  strong.textContent = value;
  article.append(span, strong);
  if (detail) {
    const p = document.createElement("p");
    p.textContent = detail;
    article.append(p);
  }
  return article;
}

async function api(path, options) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", "Accept": "application/json" },
    ...options,
  });
  if (response.status === 401) {
    window.location.href = "/login";
    throw new Error("Authentication required");
  }
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.detail || "Request failed");
  }
  return payload;
}

function formatTime(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString();
}

async function loadHealth() {
  const data = await api("/health/integrations");
  healthRoot.replaceChildren(
    card("Application", data.application, data.poll_running ? "Cycle running" : "Idle"),
    card("Gmail", data.gmail.state, data.gmail.detail, data.gmail.state),
    card("Google Drive", data.google_drive.state, data.google_drive.detail, data.google_drive.state),
    card("DeepSeek", data.deepseek.state, data.deepseek.detail, data.deepseek.state),
    card("Database", data.database.state, data.database.detail, data.database.state),
    card("Last poll", formatTime(data.last_success_at), data.last_error || "Last successful cycle")
  );
}

async function loadStats() {
  const data = await api("/api/stats");
  const rows = [
    ["Emails scanned", data.emails_scanned],
    ["Trigger matches", data.trigger_matches],
    ["Attachments", data.attachments_detected],
    ["Uploaded", data.uploads_succeeded],
    ["Failed uploads", data.uploads_failed],
    ["Pending", data.pending],
  ];
  statsRoot.replaceChildren(
    ...rows.map(([label, value]) => card(label, String(value)))
  );
}

async function loadLogs() {
  const data = await api("/api/logs?limit=50&status=" + encodeURIComponent(state.status));
  logsRoot.replaceChildren();
  if (!data.items.length) {
    const row = document.createElement("tr");
    const td = cell("No activity for this filter.");
    td.colSpan = 7;
    row.append(td);
    logsRoot.append(row);
    return;
  }
  data.items.forEach((item) => {
    const row = document.createElement("tr");
    const status = document.createElement("td");
    const pill = document.createElement("span");
    pill.className = "pill " + (item.status || "");
    pill.textContent = item.upload_status || item.status || "—";
    status.append(pill);
    row.append(
      cell(formatTime(item.created_at)),
      cell(item.subject),
      cell(item.sender),
      cell(item.filename),
      cell(item.event_type),
      status,
      cell(item.error_message || item.message)
    );
    logsRoot.append(row);
  });
}

async function loadConfig() {
  const data = await api("/api/config/status");
  configRoot.replaceChildren();
  data.flags.forEach((flag) => {
    const row = document.createElement("div");
    row.className = "flag";
    const name = document.createElement("span");
    name.textContent = flag.name;
    const value = document.createElement("strong");
    value.textContent = flag.configured ? "Configured" : "Missing";
    row.append(name, value);
    configRoot.append(row);
  });
  const meta = document.createElement("p");
  meta.className = "note";
  const model = data.deepseek_model ? data.deepseek_model : "not set";
  meta.textContent =
    "Environment " + data.app_env +
    " · database " + data.database_backend +
    " · keyword " + data.trigger_keywords.join(", ") +
    " · DeepSeek model " + model;
  configRoot.append(meta);
}

async function refresh() {
  await Promise.all([loadHealth(), loadStats(), loadLogs(), loadConfig()]);
}

document.querySelector("#refresh").addEventListener("click", () => {
  refresh().catch((error) => {
    runStatus.textContent = error.message;
  });
});

document.querySelector("#filters").addEventListener("click", (event) => {
  const button = event.target.closest("button");
  if (!button) return;
  state.status = button.dataset.status;
  document.querySelectorAll(".filter").forEach((item) => item.classList.remove("is-active"));
  button.classList.add("is-active");
  loadLogs().catch((error) => {
    runStatus.textContent = error.message;
  });
});

async function run(reprocess) {
  runStatus.textContent = "Running one cycle…";
  try {
    const result = await api("/api/agent/run", {
      method: "POST",
      body: JSON.stringify({ reprocess_failed: reprocess }),
    });
    runStatus.textContent =
      "Cycle " + result.detail +
      " · discovered " + result.discovered +
      " · uploaded " + result.uploaded +
      " · failed " + result.failed;
    await refresh();
  } catch (error) {
    runStatus.textContent = error.message;
  }
}

document.querySelector("#run").addEventListener("click", () => run(false));
document.querySelector("#retry").addEventListener("click", () => run(true));

document.querySelector("#folder-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  folderResult.textContent = "Creating folder…";
  try {
    const created = await api("/api/drive/folder", {
      method: "POST",
      body: JSON.stringify({ name: document.querySelector("#folder-name").value }),
    });
    folderResult.textContent = created.detail + " Folder id: " + created.id;
  } catch (error) {
    folderResult.textContent = error.message;
  }
});

refresh().catch((error) => {
  runStatus.textContent = error.message;
});
setInterval(() => {
  refresh().catch(() => {});
}, 15000);
