const api = (path, options = {}) =>
  fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  }).then(async (res) => {
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || res.statusText);
    return data;
  });

function screenshotUrl(path) {
  if (!path) return "";
  const normalized = String(path).replace(/\\/g, "/");
  const marker = "/data/";
  const idx = normalized.toLowerCase().indexOf(marker);
  if (idx >= 0) return normalized.slice(idx);
  if (normalized.startsWith("data/")) return `/${normalized}`;
  return normalized;
}

function showView(name) {
  document.querySelectorAll(".view").forEach((el) => el.classList.remove("active"));
  document.querySelectorAll(".nav").forEach((el) => el.classList.remove("active"));
  document.getElementById(`view-${name}`)?.classList.add("active");
  document.querySelector(`.nav[data-view="${name}"]`)?.classList.add("active");
}

document.querySelectorAll(".nav").forEach((btn) => {
  btn.addEventListener("click", () => showView(btn.dataset.view));
});

async function refreshDashboard() {
  const jobs = await api("/api/jobs");
  const counts = jobs.reduce(
    (acc, j) => {
      acc.all += 1;
      if (["PENDING", "CLAIMED", "RETRY"].includes(j.status)) acc.pending += 1;
      if (["EXECUTING", "VERIFYING"].includes(j.status)) acc.running += 1;
      if (j.status === "SUCCESS") acc.success += 1;
      if (["FAILED", "DEAD"].includes(j.status)) acc.failed += 1;
      return acc;
    },
    { all: 0, pending: 0, running: 0, success: 0, failed: 0 }
  );

  document.getElementById("dashboard-stats").innerHTML = `
    <div class="stat"><strong>${counts.pending}</strong><span>Queued</span></div>
    <div class="stat"><strong>${counts.running}</strong><span>Running</span></div>
    <div class="stat"><strong>${counts.success}</strong><span>Success</span></div>
    <div class="stat"><strong>${counts.failed}</strong><span>Failed</span></div>
  `;

  document.getElementById("dashboard-jobs").innerHTML = jobs
    .slice(0, 8)
    .map(
      (j) => `
      <div class="row">
        <div>#${j.id}</div>
        <div>${j.platform}</div>
        <div class="status-${j.status.toLowerCase()}">${j.status}</div>
        <div>${j.error_message || "-"}</div>
      </div>`
    )
    .join("");
}

async function refreshAccounts() {
  const accounts = await api("/api/accounts");
  document.getElementById("accounts-list").innerHTML = accounts
    .map(
      (a) => `
      <div class="row">
        <div>#${a.id} ${a.account_name}</div>
        <div>${a.platform}</div>
        <div>${a.status}</div>
        <div class="actions">
          <button data-open="${a.id}">Open profile</button>
          <button data-active="${a.id}">Mark active</button>
        </div>
      </div>`
    )
    .join("");

  document.querySelectorAll("[data-open]").forEach((btn) => {
    btn.onclick = () => api(`/api/accounts/${btn.dataset.open}/open-profile`, { method: "POST" })
      .then((r) => alert(r.message || "Profile launch requested"))
      .catch((e) => alert(e.message));
  });
  document.querySelectorAll("[data-active]").forEach((btn) => {
    btn.onclick = () => api(`/api/accounts/${btn.dataset.active}/mark-active`, { method: "POST" })
      .then(() => refreshAccounts())
      .catch((e) => alert(e.message));
  });
}

async function refreshContent() {
  const assets = await api("/api/content/assets");
  const variants = await api("/api/content/variants");
  document.getElementById("content-list").innerHTML = [
    ...assets.map((a) => `<div class="row"><div>Asset #${a.id}</div><div>${a.title}</div><div>${a.status}</div></div>`),
    ...variants.map((v) => `<div class="row"><div>Variant #${v.id}</div><div>${v.platform}</div><div>${v.title || ""}</div></div>`),
  ].join("");
}

async function refreshQueue() {
  const jobs = await api("/api/jobs");
  document.getElementById("queue-list").innerHTML = jobs
    .map(
      (j) => `
      <div class="row">
        <div>#${j.id}</div>
        <div>${j.status}</div>
        <div>${j.scheduled_at || ""}</div>
        <div class="actions">
          <button data-cancel="${j.id}">Cancel</button>
          <button data-retry="${j.id}">Retry</button>
          <button data-logs="${j.id}">Logs</button>
        </div>
      </div>`
    )
    .join("");

  document.querySelectorAll("[data-cancel]").forEach((btn) => {
    btn.onclick = () => api(`/api/jobs/${btn.dataset.cancel}/cancel`, { method: "POST" }).then(refreshQueue);
  });
  document.querySelectorAll("[data-retry]").forEach((btn) => {
    btn.onclick = () => api(`/api/jobs/${btn.dataset.retry}/retry`, { method: "POST" }).then(refreshQueue);
  });
  document.querySelectorAll("[data-logs]").forEach((btn) => {
    btn.onclick = () => {
      document.getElementById("history-job-id").value = btn.dataset.logs;
      showView("history");
      loadHistory();
    };
  });
}

async function loadHistory() {
  const id = document.getElementById("history-job-id").value;
  if (!id) return;
  const logs = await api(`/api/jobs/${id}/logs`);
  document.getElementById("history-list").innerHTML = logs
    .map(
      (l) => `
      <div class="row">
        <div>${l.step}</div>
        <div>${l.message || ""}</div>
        <div>${l.screenshot_path ? `<a href="${screenshotUrl(l.screenshot_path)}" target="_blank">screenshot</a>` : ""}</div>
      </div>`
    )
    .join("");
}

document.getElementById("load-history").onclick = loadHistory;

document.getElementById("settings-form").onsubmit = async (e) => {
  e.preventDefault();
  const fd = new FormData(e.target);
  const payload = Object.fromEntries(fd.entries());
  const result = await api("/api/settings/ai", { method: "PUT", body: JSON.stringify(payload) });
  document.getElementById("settings-result").textContent = JSON.stringify(result, null, 2);
};

document.getElementById("test-ai").onclick = async () => {
  const result = await api("/api/settings/ai/test", { method: "POST" });
  document.getElementById("settings-result").textContent = JSON.stringify(result, null, 2);
};

document.getElementById("account-form").onsubmit = async (e) => {
  e.preventDefault();
  const fd = new FormData(e.target);
  await api("/api/accounts", { method: "POST", body: JSON.stringify(Object.fromEntries(fd.entries())) });
  e.target.reset();
  refreshAccounts();
};

document.getElementById("asset-form").onsubmit = async (e) => {
  e.preventDefault();
  const fd = new FormData(e.target);
  const asset = await api("/api/content/assets", {
    method: "POST",
    body: JSON.stringify({ title: fd.get("title"), media_type: "video" }),
  });
  const upload = new FormData();
  upload.append("file", fd.get("file"));
  const res = await fetch(`/api/content/assets/${asset.id}/upload`, { method: "POST", body: upload });
  if (!res.ok) throw new Error("Upload failed");
  e.target.reset();
  refreshContent();
};

document.getElementById("variant-form").onsubmit = async (e) => {
  e.preventDefault();
  const fd = new FormData(e.target);
  await api("/api/content/variants", {
    method: "POST",
    body: JSON.stringify({
      asset_id: Number(fd.get("asset_id")),
      platform: "tiktok",
      title: fd.get("title"),
      caption: fd.get("caption"),
    }),
  });
  e.target.reset();
  refreshContent();
};

document.getElementById("job-form").onsubmit = async (e) => {
  e.preventDefault();
  const fd = new FormData(e.target);
  await api("/api/jobs", {
    method: "POST",
    body: JSON.stringify({
      content_variant_id: Number(fd.get("variant_id")),
      account_id: Number(fd.get("account_id")),
    }),
  });
  refreshQueue();
  refreshDashboard();
};

async function refreshWorkerBar() {
  const status = await api("/api/worker/status");
  document.getElementById("worker-status").textContent =
    `Worker: ${status.running ? "running" : "stopped"} | adapter=${status.adapter_status}`;
  document.getElementById("current-job").textContent =
    `Current job: ${status.current_job_id ?? "none"}`;
}

document.getElementById("btn-pause").onclick = () => api("/api/worker/pause", { method: "POST" }).then(refreshWorkerBar);
document.getElementById("btn-stop").onclick = () => api("/api/worker/stop", { method: "POST" }).then(refreshWorkerBar);

async function init() {
  const health = await api("/health");
  document.getElementById("app-version").textContent = `v${health.version}`;
  await Promise.all([refreshDashboard(), refreshAccounts(), refreshContent(), refreshQueue(), refreshWorkerBar()]);
  setInterval(() => {
    refreshDashboard();
    refreshQueue();
    refreshWorkerBar();
  }, 4000);
}

init().catch((err) => console.error(err));
