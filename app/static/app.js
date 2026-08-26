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
  const filterEl = document.getElementById("dashboard-package-filter");
  const filter = filterEl?.value || "DRAFT";

  const [jobs, packagesResp] = await Promise.all([
    api("/api/jobs"),
    api("/api/content/variants?generated_by=skill&page=1&page_size=50&sort=id&order=desc").catch(
      () => ({ items: [], total: 0 })
    ),
  ]);
  const packages = unwrapVariantList(packagesResp);
  const jobsByVariant = latestJobByVariant(jobs);
  const enriched = packages.map((v) => ({
    ...v,
    lifecycle: packageLifecycle(v, jobsByVariant.get(v.id)),
  }));
  const filtered =
    filter === "ALL" ? enriched : enriched.filter((v) => v.lifecycle === filter);

  const lifecycleCounts = enriched.reduce(
    (acc, v) => {
      acc[v.lifecycle] = (acc[v.lifecycle] || 0) + 1;
      return acc;
    },
    { DRAFT: 0, QUEUED: 0, RUNNING: 0, SUCCESS: 0, FAILED: 0 }
  );

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
    <div class="stat"><strong>${lifecycleCounts.DRAFT || 0}</strong><span>Draft packages</span></div>
    <div class="stat"><strong>${lifecycleCounts.QUEUED || counts.pending}</strong><span>Queued</span></div>
    <div class="stat"><strong>${lifecycleCounts.RUNNING || counts.running}</strong><span>Running</span></div>
    <div class="stat"><strong>${lifecycleCounts.SUCCESS || counts.success}</strong><span>Success</span></div>
    <div class="stat"><strong>${lifecycleCounts.FAILED || counts.failed}</strong><span>Failed</span></div>
  `;

  const draftsEl = document.getElementById("dashboard-drafts");
  if (draftsEl) {
    draftsEl.innerHTML = filtered.length
      ? filtered
          .slice(0, 12)
          .map((v) => {
            const job = jobsByVariant.get(v.id);
            const jobHint = job ? ` · job #${job.id}` : "";
            return `
        <div class="row">
          <div>包 #${v.id}</div>
          <div>${escapeHtml(platformLabel(v.platform))}</div>
          <div class="status-${String(v.lifecycle).toLowerCase()}">${escapeHtml(v.lifecycle)}${jobHint}</div>
          <div>${escapeHtml((v.title || v.caption || "").slice(0, 36))}</div>
          <div class="actions">
            <button type="button" data-dash-open-package="${v.id}">Open</button>
            ${job ? `<button type="button" data-dash-history="${job.id}">Logs</button>` : ""}
          </div>
        </div>`;
          })
          .join("")
      : `<div class="hint">当前筛选（${escapeHtml(filter)}）下暂无内容包。</div>`;
    draftsEl.querySelectorAll("[data-dash-open-package]").forEach((btn) => {
      btn.onclick = () => openPackageVariant(Number(btn.dataset.dashOpenPackage)).catch((e) => alert(e.message));
    });
    draftsEl.querySelectorAll("[data-dash-history]").forEach((btn) => {
      btn.onclick = () => openJobDetail(btn.dataset.dashHistory);
    });
  }

  document.getElementById("dashboard-jobs").innerHTML = jobs.length
    ? jobs
        .slice(0, 8)
        .map(
          (j) => `
      <div class="row">
        <div>Job #${j.id}</div>
        <div>包 #${j.content_variant_id}</div>
        <div>${j.platform}</div>
        <div class="status-${j.status.toLowerCase()}">${j.status}</div>
        <div class="actions">
          <button type="button" data-dash-open-package="${j.content_variant_id}">Open package</button>
          <button type="button" data-dash-history="${j.id}">Logs</button>
        </div>
      </div>`
        )
        .join("")
    : `<div class="hint">暂无发布任务。</div>`;

  document.querySelectorAll("#dashboard-jobs [data-dash-open-package]").forEach((btn) => {
    btn.onclick = () => openPackageVariant(Number(btn.dataset.dashOpenPackage)).catch((e) => alert(e.message));
  });
  document.querySelectorAll("#dashboard-jobs [data-dash-history]").forEach((btn) => {
    btn.onclick = () => openJobDetail(btn.dataset.dashHistory);
  });
}

function latestJobByVariant(jobs) {
  const map = new Map();
  for (const job of jobs || []) {
    const vid = job.content_variant_id;
    if (vid == null) continue;
    const prev = map.get(vid);
    if (!prev || job.id > prev.id) map.set(vid, job);
  }
  return map;
}

function packageLifecycle(variant, job) {
  if (job) {
    if (["PENDING", "CLAIMED", "RETRY"].includes(job.status)) return "QUEUED";
    if (["EXECUTING", "VERIFYING"].includes(job.status)) return "RUNNING";
    if (job.status === "SUCCESS") return "SUCCESS";
    if (["FAILED", "DEAD"].includes(job.status)) return "FAILED";
    if (job.status === "CANCELLED") return variant?.status === "DRAFT" ? "DRAFT" : "READY";
  }
  if (variant?.status === "DRAFT") return "DRAFT";
  if (variant?.status === "READY") return "QUEUED";
  return String(variant?.status || "DRAFT").toUpperCase();
}

let platformCatalog = [];
let cachedAccounts = [];
let wizardStep = 1;
let wizardAssetId = Number(sessionStorage.getItem("wizardAssetId") || 0) || null;
let reviewVariants = [];
let packagesPage = 1;
let packagesPageSize = 20;

function setWizardAssetId(id) {
  wizardAssetId = id;
  if (id) sessionStorage.setItem("wizardAssetId", String(id));
  else sessionStorage.removeItem("wizardAssetId");
}

function isSkillDraft(variant) {
  return Boolean(variant && variant.generated_by === "skill" && variant.account_id);
}

/** Accept paginated {items} or legacy array responses. */
function unwrapVariantList(resp) {
  if (Array.isArray(resp)) return resp;
  if (resp && Array.isArray(resp.items)) return resp.items;
  return [];
}

function applyReviewVariants(variants) {
  const byAccount = new Map();
  for (const variant of variants || []) {
    if (!isSkillDraft(variant)) continue;
    const prev = byAccount.get(variant.account_id);
    if (!prev || variant.id > prev.id) {
      byAccount.set(variant.account_id, variant);
    }
  }
  reviewVariants = Array.from(byAccount.values()).sort((a, b) => b.id - a.id);
  return reviewVariants;
}

async function loadDraftPackages(assetId) {
  if (!assetId) {
    reviewVariants = [];
    return [];
  }
  const resp = await api(
    `/api/content/variants?asset_id=${assetId}&generated_by=skill&page_size=100&sort=id&order=desc`
  );
  return applyReviewVariants(unwrapVariantList(resp));
}

async function fillMotherFormFromAsset(assetId) {
  if (!assetId) return null;
  try {
    const asset = await api(`/api/content/assets/${assetId}`);
    const form = document.getElementById("publish-mother-form");
    if (!form) return asset;
    form.title.value = asset.title || "";
    form.base_caption.value = asset.base_caption || "";
    form.tags.value = (asset.tags || []).join(", ");
    return asset;
  } catch {
    setWizardAssetId(null);
    return null;
  }
}

function setWizardStep(step) {
  wizardStep = step;
  document.querySelectorAll(".wizard-step").forEach((el) => {
    el.classList.toggle("active", Number(el.dataset.wizardStep) === step);
  });
  for (let i = 1; i <= 3; i += 1) {
    const panel = document.getElementById(`wizard-step-${i}`);
    if (panel) {
      panel.classList.toggle("active", i === step);
      panel.hidden = i !== step;
    }
  }
  if (step === 2) renderWizardAccountPicks();
  if (step === 3) renderReviewPackages();
}

async function goWizardStep(step) {
  if (step === 2 && !wizardAssetId) {
    alert("请先完成第 1 步：填写标题和描述并点 Next。");
    return false;
  }
  if (step === 3) {
    if (wizardAssetId) {
      await loadDraftPackages(wizardAssetId);
    }
    if (!reviewVariants.length) {
      alert("请先在第 2 步勾选账号并生成内容包。");
      return false;
    }
  }
  setWizardStep(step);
  return true;
}

async function resumeWizardAsset(assetId) {
  setWizardAssetId(assetId);
  await fillMotherFormFromAsset(assetId);
  const drafts = await loadDraftPackages(assetId);
  renderWizardAccountPicks();
  if (drafts.length) {
    setWizardStep(3);
  } else {
    setWizardStep(2);
  }
  showView("content");
}

function platformMeta(platformId) {
  return platformCatalog.find((p) => p.id === platformId) || { id: platformId, display_name: platformId };
}

function sectionChoices(platformId) {
  const meta = platformMeta(platformId);
  const section = meta.publish_options?.section;
  return section?.choices || [];
}

function sectionLabel(platformId) {
  const meta = platformMeta(platformId);
  return meta.publish_options?.section?.label || "Section";
}

function isPublishable(platformId) {
  const match = platformCatalog.find((p) => p.id === platformId);
  return Boolean(match && match.publishable);
}

function hasDedicatedChannel(platformId) {
  const match = platformCatalog.find((p) => p.id === platformId);
  return Boolean(match && match.has_dedicated_channel);
}

function platformLabel(platformId) {
  const match = platformCatalog.find((p) => p.id === platformId);
  if (!match) return platformId;
  if (!match.publishable) return `${match.display_name} (disabled)`;
  if (!match.has_dedicated_channel) return `${match.display_name} (generic agent)`;
  return match.display_name;
}

function renderPlatformOptions(selectId, { publishableOnly = false, includeBlank = false, blankLabel = "All" } = {}) {
  const select = document.getElementById(selectId);
  if (!select) return;
  const items = platformCatalog.filter((p) => !publishableOnly || p.publishable);
  const blank = includeBlank ? `<option value="">${escapeHtml(blankLabel)}</option>` : "";
  select.innerHTML =
    blank +
    items
      .map(
        (p) =>
          `<option value="${p.id}">${p.display_name}${p.publishable ? (p.has_dedicated_channel ? "" : " (generic agent)") : " (disabled)"}</option>`
      )
      .join("");
}

async function loadPlatforms() {
  platformCatalog = await api("/api/platforms");
  if (!Array.isArray(platformCatalog) || platformCatalog.length === 0) {
    throw new Error("Platform catalog is empty");
  }
  renderPlatformOptions("account-platform");
}

function showBootError(message) {
  const el = document.getElementById("boot-error");
  if (!el) return;
  el.hidden = false;
  el.textContent = message;
}

async function refreshAccounts() {
  cachedAccounts = await api("/api/accounts");
  document.getElementById("accounts-list").innerHTML = cachedAccounts
    .map(
      (a) => `
      <div class="row">
        <div>#${a.id} ${a.account_name}</div>
        <div>${platformLabel(a.platform)}</div>
        <div>${a.status}</div>
        <div class="actions">
          <button type="button" data-skill="${a.id}">Edit skill</button>
          <button type="button" data-open="${a.id}">Open profile</button>
          <button type="button" data-active="${a.id}">Mark active</button>
          <button type="button" class="danger" data-delete="${a.id}">Delete</button>
        </div>
      </div>`
    )
    .join("") || `<div class="hint">No accounts yet.</div>`;

  if (wizardStep === 2) {
    renderWizardAccountPicks();
  }

  document.querySelectorAll("[data-skill]").forEach((btn) => {
    btn.onclick = () => openSkillEditor(Number(btn.dataset.skill));
  });
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
  document.querySelectorAll("[data-delete]").forEach((btn) => {
    btn.onclick = () => {
      if (!confirm("Delete this account record? Profile folder stays on disk.")) return;
      fetch(`/api/accounts/${btn.dataset.delete}`, { method: "DELETE" })
        .then(async (res) => {
          const data = await res.json().catch(() => ({}));
          if (!res.ok) throw new Error(data.detail || res.statusText);
          refreshAccounts();
        })
        .catch((e) => alert(e.message));
    };
  });
}

function renderWizardAccountPicks() {
  const container = document.getElementById("wizard-account-picks");
  if (!container) return;
  const previouslyChecked = new Set(
    Array.from(document.querySelectorAll('input[name="wizard_account"]:checked')).map((el) => el.value)
  );
  const active = cachedAccounts.filter((a) => a.status === "ACTIVE");
  if (active.length === 0) {
    container.innerHTML = `<div class="hint">No ACTIVE accounts. Mark accounts active first.</div>`;
    return;
  }
  const grouped = active.reduce((acc, account) => {
    if (!acc[account.platform]) acc[account.platform] = [];
    acc[account.platform].push(account);
    return acc;
  }, {});
  const hasPrev = previouslyChecked.size > 0;
  container.innerHTML = Object.entries(grouped)
    .map(([platformId, accounts]) => {
      const meta = platformMeta(platformId);
      const rows = accounts
        .map((a) => {
          const checked = hasPrev ? previouslyChecked.has(String(a.id)) : true;
          return `
          <label class="check-row">
            <input type="checkbox" name="wizard_account" value="${a.id}" ${checked ? "checked" : ""} />
            <span>#${a.id} ${escapeHtml(a.account_name)}</span>
          </label>`;
        })
        .join("");
      return `
        <div class="account-group">
          <h4>${escapeHtml(meta.display_name)}${meta.publishable ? (meta.has_dedicated_channel ? "" : " (generic agent)") : " (disabled)"}</h4>
          <div class="account-picks">${rows}</div>
        </div>`;
    })
    .join("");
}

function renderReviewPackages() {
  const container = document.getElementById("review-packages");
  if (!container) return;
  if (!reviewVariants.length) {
    container.innerHTML = `<div class="hint">No generated packages yet. Go back and generate first.</div>`;
    return;
  }
  const publishableCount = reviewVariants.filter((v) => isPublishable(v.platform)).length;
  const banner =
    publishableCount === 0
      ? `<div class="hint warn">当前内容包所属平台均已禁用，无法入队。</div>`
      : `<div class="hint">可入队 ${publishableCount} / ${reviewVariants.length} 个内容包。无专用 Channel 的平台将走通用工具 Agent 执行。</div>`;
  container.innerHTML =
    banner +
    reviewVariants
      .map((v) => {
        const publishable = isPublishable(v.platform);
        const dedicated = hasDedicatedChannel(v.platform);
        const meta = platformMeta(v.platform);
        const choices = sectionChoices(v.platform);
        const sectionField = choices.length
          ? `<label>${escapeHtml(sectionLabel(v.platform))}
            <select data-field="section" data-variant-id="${v.id}">
              <option value="">—</option>
              ${choices
                .map(
                  (c) =>
                    `<option value="${escapeHtml(c)}" ${v.section === c ? "selected" : ""}>${escapeHtml(c)}</option>`
                )
                .join("")}
            </select>
          </label>`
          : "";
        const accountTitle = escapeHtml(v.account_name || `Account #${v.account_id}`);
        const platformName = escapeHtml(meta.display_name || v.platform);
        const statusBadge = escapeHtml(v.status || "DRAFT");
        return `
        <article class="package-card ${publishable ? "" : "login-only-card"}" data-variant-id="${v.id}">
          <div class="package-card-header">
            <label class="check-row">
              <input type="checkbox" name="enqueue_variant" value="${v.id}" data-account-id="${v.account_id}" data-platform="${escapeHtml(v.platform)}" ${publishable ? "checked" : ""} ${publishable ? "" : "disabled"} />
              <span class="card-title">
                <strong class="package-id">内容包 #${v.id}</strong>
                <span class="meta">${accountTitle} · #${v.account_id} · ${platformName}</span>
              </span>
            </label>
            <span class="package-badge status-${statusBadge.toLowerCase()}">${statusBadge}</span>
            <span class="package-badge ${dedicated ? "publishable" : "login-only"}">${dedicated ? "dedicated channel" : "generic agent"}</span>
          </div>
          <label>Title
            <input type="text" data-field="title" data-variant-id="${v.id}" value="${escapeHtml(v.title || "")}" />
          </label>
          <label>Caption
            <textarea data-field="caption" data-variant-id="${v.id}" rows="5">${escapeHtml(v.caption || "")}</textarea>
          </label>
          <label>Hashtags (comma-separated)
            <input type="text" data-field="hashtags" data-variant-id="${v.id}" value="${escapeHtml((v.hashtags || []).join(", "))}" />
          </label>
          ${sectionField}
        </article>`;
      })
      .join("");

  // Persist field edits into reviewVariants as user types/selects
  container.querySelectorAll("[data-field]").forEach((el) => {
    const sync = () => {
      const variantId = Number(el.dataset.variantId);
      const field = el.dataset.field;
      const target = reviewVariants.find((v) => v.id === variantId);
      if (!target) return;
      if (field === "hashtags") {
        target.hashtags = el.value
          ? el.value.split(",").map((s) => s.trim()).filter(Boolean)
          : [];
      } else {
        target[field] = el.value;
      }
    };
    el.addEventListener("change", sync);
    el.addEventListener("input", sync);
  });
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function collectReviewEdits() {
  const byId = {};
  reviewVariants.forEach((v) => {
    byId[v.id] = { ...v };
  });
  document.querySelectorAll("[data-field]").forEach((el) => {
    const variantId = Number(el.dataset.variantId);
    const field = el.dataset.field;
    if (!byId[variantId]) return;
    if (field === "hashtags") {
      byId[variantId].hashtags = el.value
        ? el.value.split(",").map((s) => s.trim()).filter(Boolean)
        : [];
    } else {
      byId[variantId][field] = el.value;
    }
  });
  return Object.values(byId);
}

function openSkillEditor(accountId) {
  const account = cachedAccounts.find((a) => a.id === accountId);
  if (!account) return;
  const skill = account.skill || {};
  document.getElementById("skill-editor").hidden = false;
  document.getElementById("skill-account-id").value = account.id;
  document.getElementById("skill-persona").value = account.persona || "";
  document.getElementById("skill-tone").value = skill.tone || "";
  document.getElementById("skill-audience").value = skill.audience || "";
  document.getElementById("skill-language").value = skill.language || account.language || "";
  document.getElementById("skill-cta").value = skill.cta || "";
  document.getElementById("skill-taboos").value = (skill.taboos || []).join(", ");
  document.getElementById("skill-extra").value = skill.extra_prompt || "";
}

document.getElementById("skill-form").onsubmit = async (e) => {
  e.preventDefault();
  const accountId = Number(document.getElementById("skill-account-id").value);
  const taboosRaw = document.getElementById("skill-taboos").value;
  const payload = {
    persona: document.getElementById("skill-persona").value || null,
    language: document.getElementById("skill-language").value || null,
    skill: {
      tone: document.getElementById("skill-tone").value || null,
      audience: document.getElementById("skill-audience").value || null,
      language: document.getElementById("skill-language").value || null,
      cta: document.getElementById("skill-cta").value || null,
      taboos: taboosRaw ? taboosRaw.split(",").map((s) => s.trim()).filter(Boolean) : [],
      extra_prompt: document.getElementById("skill-extra").value || null,
    },
  };
  try {
    await api(`/api/accounts/${accountId}`, { method: "PATCH", body: JSON.stringify(payload) });
    await refreshAccounts();
    alert("Skill saved.");
  } catch (err) {
    alert(err.message);
  }
};

function renderEnqueueList() {
  // legacy no-op; wizard step 3 handles enqueue UI
}

function packagesFilterParams(page = packagesPage) {
  const form = document.getElementById("packages-filter-form");
  if (!form) return { page, page_size: packagesPageSize };
  const fd = new FormData(form);
  const params = new URLSearchParams();
  for (const [key, value] of fd.entries()) {
    if (value !== "" && value != null) params.set(key, String(value));
  }
  params.set("page", String(page));
  params.set("page_size", String(packagesPageSize));
  return Object.fromEntries(params.entries());
}

function buildPackagesQuery(page = packagesPage) {
  const params = packagesFilterParams(page);
  const qs = new URLSearchParams(params);
  return `/api/content/variants?${qs.toString()}`;
}

async function openPackageVariant(variantId) {
  const variant = await api(`/api/content/variants/${variantId}`);
  setWizardAssetId(variant.asset_id);
  await fillMotherFormFromAsset(variant.asset_id);
  await loadDraftPackages(variant.asset_id);
  setWizardStep(3);
  showView("content");
}

async function deletePackageVariant(variantId) {
  if (!confirm(`Delete draft package #${variantId}?`)) return;
  await api(`/api/content/variants/${variantId}`, { method: "DELETE" });
  await loadPackagesTable(packagesPage);
}

function renderPackagesTable(resp) {
  const container = document.getElementById("packages-table");
  const pager = document.getElementById("packages-pagination");
  if (!container) return;

  const items = unwrapVariantList(resp);
  if (!items.length) {
    container.innerHTML = `<div class="hint">No packages found.</div>`;
  } else {
    const header = `
      <div class="row packages-head">
        <div>ID</div>
        <div>Asset</div>
        <div>Account</div>
        <div>Platform</div>
        <div>Title</div>
        <div>Status</div>
        <div>Section</div>
        <div>Actions</div>
      </div>`;
    const rows = items
      .map((v) => {
        const title = escapeHtml((v.title || v.caption || "").slice(0, 48));
        const account = escapeHtml(v.account_name || (v.account_id ? `#${v.account_id}` : "-"));
        const section = escapeHtml(v.section || "-");
        const canDelete = v.status === "DRAFT";
        return `
        <div class="row packages-row">
          <div>#${v.id}</div>
          <div>#${v.asset_id}</div>
          <div>${account}</div>
          <div>${escapeHtml(platformLabel(v.platform))}</div>
          <div>${title}</div>
          <div class="status-${String(v.status || "").toLowerCase()}">${escapeHtml(v.status)}</div>
          <div>${section}</div>
          <div class="actions">
            <button type="button" data-open-package="${v.id}">Open</button>
            <button type="button" data-resume-asset="${v.asset_id}">Resume asset</button>
            ${canDelete ? `<button type="button" data-delete-package="${v.id}" class="danger">Delete</button>` : ""}
          </div>
        </div>`;
      })
      .join("");
    container.innerHTML = header + rows;
  }

  if (pager) {
    const page = Number(resp.page || packagesPage || 1);
    const pageSize = Number(resp.page_size || packagesPageSize);
    const total = Array.isArray(resp) ? items.length : Number(resp.total || items.length);
    const totalPages = Math.max(1, Math.ceil(total / pageSize));
    pager.innerHTML = `
      <button type="button" id="packages-prev" ${page <= 1 ? "disabled" : ""}>Previous</button>
      <span>Page ${page} / ${totalPages} · ${total} total</span>
      <button type="button" id="packages-next" ${page >= totalPages ? "disabled" : ""}>Next</button>`;
    document.getElementById("packages-prev")?.addEventListener("click", () => {
      if (page > 1) loadPackagesTable(page - 1).catch((e) => alert(e.message));
    });
    document.getElementById("packages-next")?.addEventListener("click", () => {
      if (page < totalPages) loadPackagesTable(page + 1).catch((e) => alert(e.message));
    });
  }

  container.querySelectorAll("[data-open-package]").forEach((btn) => {
    btn.onclick = () => openPackageVariant(Number(btn.dataset.openPackage)).catch((e) => alert(e.message));
  });
  container.querySelectorAll("[data-resume-asset]").forEach((btn) => {
    btn.onclick = () => resumeWizardAsset(Number(btn.dataset.resumeAsset)).catch((e) => alert(e.message));
  });
  container.querySelectorAll("[data-delete-package]").forEach((btn) => {
    btn.onclick = () => deletePackageVariant(Number(btn.dataset.deletePackage)).catch((e) => alert(e.message));
  });
}

async function loadPackagesTable(page = 1) {
  packagesPage = page;
  const resp = await api(buildPackagesQuery(page));
  renderPackagesTable(resp);
  return resp;
}

async function refreshContent() {
  renderPlatformOptions("packages-platform", { includeBlank: true, blankLabel: "All platforms" });
  await loadPackagesTable(packagesPage);
}

document.getElementById("publish-mother-form").onsubmit = async (e) => {
  e.preventDefault();
  const fd = new FormData(e.target);
  const tagsRaw = String(fd.get("tags") || "");
  const tags = tagsRaw ? tagsRaw.split(",").map((s) => s.trim()).filter(Boolean) : [];
  try {
    const asset = await api("/api/content/assets", {
      method: "POST",
      body: JSON.stringify({
        title: fd.get("title"),
        base_caption: fd.get("base_caption"),
        media_type: "text",
        tags,
      }),
    });
    setWizardAssetId(asset.id);
    const video = fd.get("video");
    if (video && video.size > 0) {
      const upload = new FormData();
      upload.append("file", video);
      const res = await fetch(`/api/content/assets/${asset.id}/upload`, { method: "POST", body: upload });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || "Video upload failed");
      }
    }
    const images = fd.getAll("images").filter((f) => f && f.size > 0);
    if (images.length > 0) {
      const upload = new FormData();
      images.forEach((file) => upload.append("files", file));
      const res = await fetch(`/api/content/assets/${asset.id}/upload-images`, { method: "POST", body: upload });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || "Image upload failed");
      }
    }
    renderWizardAccountPicks();
    setWizardStep(2);
    await refreshContent();
  } catch (err) {
    alert(err.message);
  }
};

document.getElementById("btn-wizard-back-2").onclick = () => setWizardStep(1);
document.getElementById("btn-wizard-back-3").onclick = () => setWizardStep(2);

document.getElementById("packages-filter-form")?.addEventListener("submit", (e) => {
  e.preventDefault();
  loadPackagesTable(1).catch((err) => alert(err.message));
});

document.getElementById("btn-select-all-accounts").onclick = () => {
  document.querySelectorAll('input[name="wizard_account"]').forEach((el) => {
    el.checked = true;
  });
};
document.getElementById("btn-select-none-accounts").onclick = () => {
  document.querySelectorAll('input[name="wizard_account"]').forEach((el) => {
    el.checked = false;
  });
};

document.getElementById("btn-generate-packages").onclick = async () => {
  const accountIds = Array.from(document.querySelectorAll('input[name="wizard_account"]:checked')).map(
    (el) => Number(el.value)
  );
  if (!wizardAssetId || accountIds.length === 0) {
    alert("Create mother content first and select at least one ACTIVE account.");
    return;
  }
  const btn = document.getElementById("btn-generate-packages");
  const statusEl = document.getElementById("generate-status");
  const resultEl = document.getElementById("generate-result");

  try {
    const models = await api("/api/llm/models").catch(() => []);
    const enabled = (models || [])
      .filter((m) => m.enabled)
      .sort((a, b) => (a.priority ?? 0) - (b.priority ?? 0));
    const primary = enabled[0];
    const llmInfo = primary
      ? `主模型：${primary.alias} | ${primary.provider} | ${primary.model || "(default)"}` +
        (primary.base_url ? `\nbase_url: ${primary.base_url}` : "") +
        (enabled.length > 1
          ? `\n备用：${enabled
              .slice(1)
              .map((m) => `${m.alias}/${m.provider}/${m.model || "?"}`)
              .join("; ")}`
          : "")
      : "警告：没有启用的 LLM 配置，生成会失败。";
    const ok = confirm(
      `即将为 ${accountIds.length} 个账号调用 LLM 生成内容包（二次确认）：\n\n${llmInfo}\n\n确认继续？`
    );
    if (!ok) return;
  } catch (err) {
    alert(err.message);
    return;
  }

  if (btn) btn.disabled = true;
  if (statusEl) {
    statusEl.hidden = false;
    statusEl.textContent = `Generating packages for ${accountIds.length} account(s)…`;
  }
  try {
    const result = await api(`/api/content/assets/${wizardAssetId}/generate-variants`, {
      method: "POST",
      body: JSON.stringify({ account_ids: accountIds }),
    });
    const created = result.variants || [];
    const errors = result.errors || [];
    if (resultEl) {
      resultEl.hidden = false;
      resultEl.textContent = JSON.stringify(result, null, 2);
    }
    if (created.length) {
      applyReviewVariants(created);
      // Merge with any surviving drafts from failed accounts
      await loadDraftPackages(wizardAssetId);
      renderReviewPackages();
      setWizardStep(3);
    }
    const summary = `生成完成：成功 ${created.length}，失败 ${errors.length}`;
    if (statusEl) statusEl.textContent = summary;
    if (errors.length) {
      const detail = errors.map((e) => `#${e.account_id}: ${e.detail}`).join("\n");
      alert(`${summary}\n\n${detail}`);
    } else if (!created.length) {
      alert("未生成任何内容包。请检查 LLM 配置与账号状态。");
    }
    await refreshContent();
    await refreshDashboard();
  } catch (err) {
    if (statusEl) statusEl.textContent = `生成失败：${err.message}`;
    alert(err.message);
  } finally {
    if (btn) btn.disabled = false;
  }
};

document.getElementById("btn-select-all-enqueue").onclick = () => {
  document.querySelectorAll('input[name="enqueue_variant"]').forEach((el) => {
    const variant = reviewVariants.find((v) => v.id === Number(el.value));
    if (variant && isPublishable(variant.platform)) el.checked = true;
  });
};

document.getElementById("btn-save-packages").onclick = async () => {
  const edits = collectReviewEdits();
  try {
    for (const variant of edits) {
      await api(`/api/content/variants/${variant.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          title: variant.title || null,
          caption: variant.caption || null,
          hashtags: variant.hashtags || [],
          section: variant.section || "",
        }),
      });
    }
    reviewVariants = await loadDraftPackages(wizardAssetId);
    renderReviewPackages();
    alert("Saved.");
  } catch (err) {
    alert(err.message);
  }
};

document.getElementById("btn-enqueue-selected").onclick = async () => {
  const edits = collectReviewEdits();
  const editMap = Object.fromEntries(edits.map((v) => [v.id, v]));
  const items = Array.from(document.querySelectorAll('input[name="enqueue_variant"]:checked:not(:disabled)'))
    .map((el) => {
      const variantId = Number(el.value);
      const variant = editMap[variantId];
      return {
        content_variant_id: variantId,
        account_id: Number(el.dataset.accountId),
        platform: el.dataset.platform || variant?.platform,
        _variant: variant,
      };
    })
    .filter((item) => isPublishable(item.platform));
  if (items.length === 0) {
    alert("没有可入队的内容包。请确认平台已启用且账号为 ACTIVE。");
    return;
  }

  try {
    const preview = await buildEnqueueLlmPreview(items);
    if (preview.usesLlm) {
      const ok = confirm(
        `即将创建 ${items.length} 个发布任务。\n\n` +
          `Worker 执行时会调用 LLM（二次确认）：\n` +
          `${preview.summary}\n\n` +
          `确认入队并允许后续任务使用上述 LLM？`
      );
      if (!ok) return;
    } else {
      const ok = confirm(`即将创建 ${items.length} 个发布任务（当前执行层为 mock，不调用 LLM）。确认？`);
      if (!ok) return;
    }

    for (const item of items) {
      if (item._variant) {
        await api(`/api/content/variants/${item.content_variant_id}`, {
          method: "PATCH",
          body: JSON.stringify({
            title: item._variant.title || null,
            caption: item._variant.caption || null,
            hashtags: item._variant.hashtags || [],
            section: item._variant.section || "",
            status: "READY",
          }),
        });
      }
    }
    const result = await api("/api/jobs/bulk", {
      method: "POST",
      body: JSON.stringify({
        items: items.map(({ content_variant_id, account_id }) => ({ content_variant_id, account_id })),
      }),
    });
    const failed = result.failed || [];
    const created = result.created || [];
    let msg = `Created ${created.length} job(s). Failed: ${failed.length}`;
    if (failed.length) {
      msg +=
        "\n\n" +
        failed.map((f) => `包 #${f.content_variant_id} / 账号 #${f.account_id}: ${f.detail}`).join("\n");
    }
    alert(msg);
    refreshQueue();
    refreshDashboard();
    refreshContent();
  } catch (err) {
    alert(err.message);
  }
};

function adapterUsesLlm(adapterName) {
  const name = String(adapterName || "mock").toLowerCase().replace(/-/g, "_");
  return name !== "mock";
}

function resolvePlatformAdapterName(platformId) {
  const meta = platformMeta(platformId);
  if (meta.preferred_adapter) return String(meta.preferred_adapter).toLowerCase().replace(/-/g, "_");
  return null;
}

async function buildEnqueueLlmPreview(items) {
  const [models, workerStatus] = await Promise.all([
    api("/api/llm/models").catch(() => []),
    api("/api/worker/status").catch(() => ({})),
  ]);
  const globalAdapter = String(workerStatus.adapter_name || "browser_use").toLowerCase().replace(/-/g, "_");
  const enabled = (models || [])
    .filter((m) => m.enabled)
    .sort((a, b) => (a.priority ?? 0) - (b.priority ?? 0));
  const primary = enabled[0] || null;
  const backups = enabled.slice(1);

  const byAdapter = new Map();
  for (const item of items) {
    const adapter = resolvePlatformAdapterName(item.platform) || globalAdapter;
    if (!byAdapter.has(adapter)) byAdapter.set(adapter, new Set());
    byAdapter.get(adapter).add(item.platform);
  }

  const adapterLines = Array.from(byAdapter.entries()).map(
    ([adapter, platforms]) => `· 执行层 ${adapter} ← ${Array.from(platforms).join(", ")}`
  );
  const usesLlm = Array.from(byAdapter.keys()).some(adapterUsesLlm);

  let llmLines = [];
  if (usesLlm) {
    if (primary) {
      llmLines.push(
        `· 主模型：${primary.alias} | ${primary.provider} | ${primary.model || "(default)"}` +
          (primary.base_url ? `\n  base_url: ${primary.base_url}` : "")
      );
      if (backups.length) {
        llmLines.push(
          `· 备用（失败自动切换）：${backups
            .map((m) => `${m.alias}/${m.provider}/${m.model || "?"}`)
            .join("; ")}`
        );
      }
    } else {
      llmLines.push("· 警告：当前没有启用的 LLM 配置，任务执行时可能失败。请先到 Settings 配置。");
    }
    if (byAdapter.has("openclaw")) {
      llmLines.push("· OpenClaw 使用其自身模型/网关（非本机 LLM 连接池）。");
    }
  }

  return {
    usesLlm,
    summary: [...adapterLines, ...llmLines].join("\n"),
    primary,
  };
}

const RUNNING_JOB_STATUSES = new Set(["PENDING", "CLAIMED", "EXECUTING", "VERIFYING"]);
const RETRY_JOB_STATUSES = new Set(["FAILED", "DEAD", "CANCELLED", "RETRY"]);
const REPUBLISH_JOB_STATUSES = new Set([
  "SUCCESS",
  "FAILED",
  "DEAD",
  "CANCELLED",
  "WAITING_HUMAN",
  "RETRY",
]);

function formatRepublishPreviewLines(preview) {
  const lines = [];
  if (preview.will_call_content_llm) {
    lines.push("【内容 LLM】将重写标题/文案/话题");
    const items = preview.llm || [];
    if (items.length) {
      const primary = items[0];
      lines.push(
        `· 主模型：${primary.alias} | ${primary.provider} | ${primary.model || "(default)"}`
      );
      if (items.length > 1) {
        lines.push(
          `· 备用：${items
            .slice(1)
            .map((m) => `${m.alias}/${m.provider}/${m.model || "?"}`)
            .join("; ")}`
        );
      }
    } else {
      lines.push("· 警告：无启用的 LLM 配置");
    }
  } else {
    lines.push("【内容】使用原内容包，不调用 LLM 重写");
  }
  if (preview.will_call_execution_llm) {
    lines.push(`【执行 LLM】Worker 将通过 ${preview.adapter} 调用 LLM`);
    if ((preview.llm || []).length) {
      const primary = preview.llm[0];
      lines.push(`· 执行层模型池：${primary.alias} | ${primary.provider} | ${primary.model || "(default)"}`);
    }
  } else {
    lines.push(`【执行】adapter=${preview.adapter}，执行时不调用 LLM`);
  }
  return lines.join("\n");
}

function confirmLlmAction(title, preview) {
  const parts = [title];
  if (preview.warnings?.length) {
    parts.push("", preview.warnings.map((w) => `⚠ ${w}`).join("\n"));
  }
  parts.push("", formatRepublishPreviewLines(preview), "", "确认继续？");
  return confirm(parts.join("\n"));
}

function jobActionButtons(job, { includeOpenPackage = true } = {}) {
  const status = String(job.status || "");
  let html = "";
  if (includeOpenPackage) {
    html += `<button type="button" data-open-job-package="${job.content_variant_id}">Open package</button>`;
  }
  if (RUNNING_JOB_STATUSES.has(status)) {
    html += `<button type="button" data-cancel="${job.id}">Cancel</button>`;
  }
  if (RETRY_JOB_STATUSES.has(status)) {
    html += `<button type="button" data-retry-job="${job.id}">原内容重试</button>`;
  }
  if (REPUBLISH_JOB_STATUSES.has(status)) {
    if (status === "SUCCESS" || status === "WAITING_HUMAN") {
      html += `<button type="button" data-republish="${job.id}" data-rewrite="0">再发</button>`;
    } else if (!RETRY_JOB_STATUSES.has(status)) {
      html += `<button type="button" data-republish="${job.id}" data-rewrite="0">再发</button>`;
    }
    html += `<button type="button" data-republish="${job.id}" data-rewrite="1">重写后再发</button>`;
  }
  html += `<button type="button" data-logs="${job.id}">Logs</button>`;
  return html;
}

async function confirmRetryJob(jobId) {
  const preview = await api(`/api/jobs/${jobId}/republish/preview`, {
    method: "POST",
    body: JSON.stringify({ rewrite: false }),
  });
  preview.will_call_content_llm = false;
  if (!confirmLlmAction(`即将原内容重试 Job #${jobId}`, preview)) return;
  await api(`/api/jobs/${jobId}/retry`, { method: "POST" });
  alert("任务已重新入队");
  refreshQueue();
  refreshDashboard();
  if (document.getElementById("history-job-id")?.value === String(jobId)) {
    loadJobDetail().catch((e) => alert(e.message));
  }
}

async function confirmRepublishJob(jobId, rewrite) {
  const isRewrite = Boolean(Number(rewrite));
  const preview = await api(`/api/jobs/${jobId}/republish/preview`, {
    method: "POST",
    body: JSON.stringify({ rewrite: isRewrite }),
  });
  const title = isRewrite
    ? `即将为 Job #${jobId} 重写内容并再发`
    : `即将为 Job #${jobId} 再发（原内容）`;
  if (!confirmLlmAction(title, preview)) return;
  const result = await api(`/api/jobs/${jobId}/republish`, {
    method: "POST",
    body: JSON.stringify({ rewrite: isRewrite }),
  });
  alert(`已创建新任务 Job #${result.new_job.id}`);
  refreshQueue();
  refreshDashboard();
  openJobDetail(result.new_job.id);
}

function wireJobActions(root = document) {
  root.querySelectorAll("[data-open-job-package]").forEach((btn) => {
    btn.onclick = () => openPackageVariant(Number(btn.dataset.openJobPackage)).catch((e) => alert(e.message));
  });
  root.querySelectorAll("[data-cancel]").forEach((btn) => {
    btn.onclick = () =>
      api(`/api/jobs/${btn.dataset.cancel}/cancel`, { method: "POST" })
        .then(() => {
          refreshQueue();
          refreshDashboard();
        })
        .catch((e) => alert(e.message));
  });
  root.querySelectorAll("[data-retry-job]").forEach((btn) => {
    btn.onclick = () => confirmRetryJob(Number(btn.dataset.retryJob)).catch((e) => alert(e.message));
  });
  root.querySelectorAll("[data-republish]").forEach((btn) => {
    btn.onclick = () =>
      confirmRepublishJob(Number(btn.dataset.republish), btn.dataset.rewrite).catch((e) => alert(e.message));
  });
  root.querySelectorAll("[data-logs]").forEach((btn) => {
    btn.onclick = () => openJobDetail(btn.dataset.logs);
  });
}

async function refreshQueue() {
  const jobs = await api("/api/jobs");
  document.getElementById("queue-list").innerHTML = jobs
    .map(
      (j) => `
      <div class="row">
        <div>Job #${j.id}</div>
        <div>包 #${j.content_variant_id}</div>
        <div>${j.platform || "-"}</div>
        <div class="status-${String(j.status || "").toLowerCase()}">${j.status}</div>
        <div>${j.scheduled_at || ""}</div>
        <div class="actions">
          ${jobActionButtons(j)}
        </div>
      </div>`
    )
    .join("") || `<div class="hint">Queue is empty.</div>`;

  wireJobActions(document.getElementById("queue-list"));
}

function formatTokens(value) {
  return value == null ? "—" : String(value);
}

function formatDuration(ms) {
  if (ms == null) return "—";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function parseStepPayload(step) {
  if (!step.payload_json) return {};
  try {
    return JSON.parse(step.payload_json);
  } catch {
    return {};
  }
}

function openJobDetail(jobId) {
  showView("history");
  const input = document.getElementById("history-job-id");
  if (input) input.value = String(jobId);
  loadJobDetail().catch((e) => alert(e.message));
}

function renderHumanCard(detail) {
  const { job, steps, account_id } = detail;
  if (job.status !== "WAITING_HUMAN") return "";
  const waitStep = [...steps].reverse().find((s) => s.status === "WAITING_HUMAN" || s.step === "waiting_human");
  const payload = waitStep ? parseStepPayload(waitStep) : {};
  const guidance =
    payload.guidance ||
    "请在浏览器中完成登录或验证码，完成后点击继续执行。";
  return `
    <article class="job-human-card">
      <h3>需要人工介入</h3>
      <p>${escapeHtml(guidance)}</p>
      <div class="job-human-actions">
        <button type="button" data-human-open-profile="${account_id}">打开浏览器 Profile</button>
        <button type="button" data-human-resume="${job.id}">我已完成，继续</button>
      </div>
    </article>`;
}

function renderJobDetail(detail) {
  const container = document.getElementById("job-detail");
  if (!container) return;
  const { job, steps, totals } = detail;
  const statusClass = String(job.status || "").toLowerCase();

  container.innerHTML = `
    <div class="job-detail-header">
      <div class="stat"><strong>#${job.id}</strong><span>Job ID</span></div>
      <div class="stat"><strong class="status-${statusClass}">${escapeHtml(job.status)}</strong><span>状态</span></div>
      <div class="stat"><strong>${escapeHtml(job.platform)}</strong><span>平台</span></div>
      <div class="stat"><strong>包 #${job.content_variant_id}</strong><span>内容包</span></div>
      <div class="stat"><strong>${formatDuration(totals.duration_ms)}</strong><span>总耗时</span></div>
      <div class="stat"><strong>${formatTokens(totals.total_tokens)}</strong><span>总 Token</span></div>
    </div>
    <div class="job-detail-actions actions">
      ${jobActionButtons(job, { includeOpenPackage: false })}
    </div>
    ${renderHumanCard(detail)}
    <ol class="step-line">
      ${steps
        .map((step, index) => {
          const payload = parseStepPayload(step);
          const stepStatus = String(step.status || "running").toLowerCase();
          const title = step.tool_name ? `${step.step} · ${step.tool_name}` : step.step;
          const summary = step.message ? escapeHtml(step.message.slice(0, 120)) : "";
          const payloadText = JSON.stringify(payload, null, 2);
          return `
        <li class="step-line-item status-${stepStatus}">
          <span class="step-dot" aria-hidden="true"></span>
          <div class="step-head">
            <span class="step-title">${escapeHtml(title)}</span>
            <span class="step-meta">${formatDuration(step.duration_ms)} · Token ${formatTokens(step.total_tokens)}</span>
            <button type="button" class="step-toggle" data-step-toggle="${index}">展开</button>
          </div>
          ${summary ? `<div class="step-meta">${summary}</div>` : ""}
          <div class="step-body" hidden data-step-body="${index}">
            <div>状态：${escapeHtml(step.status || "—")}</div>
            <div>Prompt tokens：${formatTokens(step.prompt_tokens)} · Completion：${formatTokens(step.completion_tokens)}</div>
            ${step.message ? `<div>消息：${escapeHtml(step.message)}</div>` : ""}
            ${Object.keys(payload).length ? `<pre>${escapeHtml(payloadText)}</pre>` : ""}
            ${
              step.screenshot_path
                ? `<div class="step-screenshot"><a href="${screenshotUrl(step.screenshot_path)}" target="_blank">查看截图</a></div>`
                : ""
            }
          </div>
        </li>`;
        })
        .join("")}
    </ol>`;

  container.querySelectorAll("[data-step-toggle]").forEach((btn) => {
    btn.onclick = () => {
      const body = container.querySelector(`[data-step-body="${btn.dataset.stepToggle}"]`);
      if (!body) return;
      const open = body.hidden;
      body.hidden = !open;
      btn.textContent = open ? "收起" : "展开";
    };
  });

  container.querySelectorAll("[data-human-open-profile]").forEach((btn) => {
    btn.onclick = () =>
      api(`/api/accounts/${btn.dataset.humanOpenProfile}/open-profile`, { method: "POST" })
        .then(() => alert("已尝试打开浏览器 Profile"))
        .catch((e) => alert(e.message));
  });

  container.querySelectorAll("[data-human-resume]").forEach((btn) => {
    btn.onclick = () =>
      api(`/api/jobs/${btn.dataset.humanResume}/resume`, { method: "POST" })
        .then(() => loadJobDetail())
        .catch((e) => alert(e.message));
  });

  wireJobActions(container);
}

async function loadJobDetail() {
  const id = document.getElementById("history-job-id")?.value;
  const container = document.getElementById("job-detail");
  if (!id) {
    if (container) container.innerHTML = `<div class="job-detail-empty">输入 Job ID 查看推送详情。</div>`;
    return;
  }
  const detail = await api(`/api/jobs/${id}/detail`);
  renderJobDetail(detail);
}

document.getElementById("load-history").onclick = () => loadJobDetail().catch((e) => alert(e.message));

let cachedLlmModels = [];

function resetLlmEditor() {
  const form = document.getElementById("llm-model-form");
  form.reset();
  document.getElementById("llm-edit-id").value = "";
  document.getElementById("llm-enabled").checked = true;
  document.getElementById("llm-priority").value = "0";
  document.getElementById("llm-concurrency").value = "4";
  document.getElementById("llm-timeout").value = "60";
  document.getElementById("llm-editor-title").textContent = "添加配置";
  document.getElementById("llm-save-btn").textContent = "保存";
  document.getElementById("llm-api-key").placeholder = "新建必填；编辑留空则不改";
}

function openLlmEditor(model = null) {
  const editor = document.getElementById("llm-editor");
  resetLlmEditor();
  if (model) {
    document.getElementById("llm-editor-title").textContent = `编辑配置 #${model.id}`;
    document.getElementById("llm-edit-id").value = String(model.id);
    document.getElementById("llm-alias").value = model.alias || "";
    document.getElementById("llm-provider").value = model.provider || "openai";
    document.getElementById("llm-model").value = model.model || "";
    document.getElementById("llm-base-url").value = model.base_url || "";
    document.getElementById("llm-priority").value = String(model.priority ?? 0);
    document.getElementById("llm-concurrency").value = String(model.max_concurrency ?? 4);
    document.getElementById("llm-timeout").value = String(model.timeout_sec ?? 60);
    document.getElementById("llm-enabled").checked = Boolean(model.enabled);
    document.getElementById("llm-api-key").value = "";
    document.getElementById("llm-save-btn").textContent = "更新";
  }
  editor.hidden = false;
  editor.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function closeLlmEditor() {
  document.getElementById("llm-editor").hidden = true;
  resetLlmEditor();
}

async function refreshLlmModels() {
  cachedLlmModels = await api("/api/llm/models");
  const container = document.getElementById("llm-models-list");
  if (!container) return;
  if (!cachedLlmModels.length) {
    container.innerHTML = `<div class="hint">连接池为空。点击「+ 添加配置」创建第一套模型。</div>`;
    return;
  }
  container.innerHTML = cachedLlmModels
    .map(
      (m) => `
      <article class="pool-card ${m.enabled ? "" : "disabled"}">
        <div>
          <div class="title">${escapeHtml(m.alias)}
            <span class="pool-badge ${m.enabled ? "on" : "off"}">${m.enabled ? "启用" : "停用"}</span>
          </div>
          <div class="meta">#${m.id} · key ${escapeHtml(m.api_key || "未配置")}</div>
        </div>
        <div>
          <div>${escapeHtml(m.provider)} · ${escapeHtml(m.model || "-")}</div>
          <div class="meta">${escapeHtml(m.base_url || "默认 endpoint")}</div>
        </div>
        <div>
          <div>Priority ${m.priority}</div>
          <div class="meta">并发 ${m.max_concurrency} · 超时 ${m.timeout_sec}s</div>
        </div>
        <div class="actions">
          <button type="button" data-llm-edit="${m.id}">编辑</button>
          <button type="button" data-llm-test="${m.id}">测试</button>
          <button type="button" data-llm-toggle="${m.id}" data-enabled="${m.enabled}">${m.enabled ? "停用" : "启用"}</button>
          <button type="button" class="danger" data-llm-delete="${m.id}">删除</button>
        </div>
      </article>`
    )
    .join("");

  document.querySelectorAll("[data-llm-edit]").forEach((btn) => {
    btn.onclick = () => {
      const model = cachedLlmModels.find((m) => m.id === Number(btn.dataset.llmEdit));
      if (model) openLlmEditor(model);
    };
  });
  document.querySelectorAll("[data-llm-test]").forEach((btn) => {
    btn.onclick = async () => {
      const resultEl = document.getElementById("settings-result");
      resultEl.textContent = "Testing…";
      try {
        const result = await api(`/api/llm/models/${btn.dataset.llmTest}/test`, { method: "POST" });
        resultEl.textContent = JSON.stringify(result, null, 2);
      } catch (err) {
        resultEl.textContent = err.message;
      }
    };
  });
  document.querySelectorAll("[data-llm-toggle]").forEach((btn) => {
    btn.onclick = async () => {
      const id = Number(btn.dataset.llmToggle);
      const enabled = btn.dataset.enabled !== "true";
      await api(`/api/llm/models/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ enabled }),
      });
      refreshLlmModels();
    };
  });
  document.querySelectorAll("[data-llm-delete]").forEach((btn) => {
    btn.onclick = async () => {
      if (!confirm("删除该连接池配置？")) return;
      await api(`/api/llm/models/${btn.dataset.llmDelete}`, { method: "DELETE" });
      closeLlmEditor();
      refreshLlmModels();
    };
  });
}

document.getElementById("btn-llm-add").onclick = () => openLlmEditor();
document.getElementById("btn-llm-cancel").onclick = () => closeLlmEditor();

document.getElementById("llm-model-form").onsubmit = async (e) => {
  e.preventDefault();
  const fd = new FormData(e.target);
  const editId = String(fd.get("id") || "").trim();
  const payload = {
    alias: fd.get("alias"),
    provider: fd.get("provider"),
    model: fd.get("model") || null,
    base_url: fd.get("base_url") || null,
    priority: Number(fd.get("priority") || 0),
    max_concurrency: Number(fd.get("max_concurrency") || 4),
    timeout_sec: Number(fd.get("timeout_sec") || 60),
    enabled: fd.get("enabled") === "on",
  };
  const apiKey = String(fd.get("api_key") || "").trim();
  if (apiKey) payload.api_key = apiKey;
  if (!editId && !apiKey) {
    alert("新建配置需要填写 API Key");
    return;
  }
  try {
    if (editId) {
      await api(`/api/llm/models/${editId}`, { method: "PATCH", body: JSON.stringify(payload) });
    } else {
      await api("/api/llm/models", { method: "POST", body: JSON.stringify(payload) });
    }
    closeLlmEditor();
    await refreshLlmModels();
  } catch (err) {
    alert(err.message);
  }
};

document.getElementById("account-form").onsubmit = async (e) => {
  e.preventDefault();
  const fd = new FormData(e.target);
  try {
    await api("/api/accounts", { method: "POST", body: JSON.stringify(Object.fromEntries(fd.entries())) });
    e.target.reset();
    renderPlatformOptions("account-platform");
    refreshAccounts();
  } catch (err) {
    alert(err.message);
  }
};

document.getElementById("job-form").onsubmit = async (e) => {
  e.preventDefault();
  const fd = new FormData(e.target);
  try {
    await api("/api/jobs", {
      method: "POST",
      body: JSON.stringify({
        content_variant_id: Number(fd.get("variant_id")),
        account_id: Number(fd.get("account_id")),
      }),
    });
    refreshQueue();
    refreshDashboard();
  } catch (err) {
    alert(err.message);
  }
};

async function refreshWorkerBar() {
  const status = await api("/api/worker/status");
  document.getElementById("worker-status").textContent =
    `Worker: ${status.running ? "running" : "stopped"} | adapter=${status.adapter_name || "browser_use"} (${status.adapter_status})`;
  document.getElementById("current-job").textContent =
    `Current job: ${status.current_job_id ?? "none"}`;
}

document.getElementById("btn-pause").onclick = () => api("/api/worker/pause", { method: "POST" }).then(refreshWorkerBar);
document.getElementById("btn-stop").onclick = () => api("/api/worker/stop", { method: "POST" }).then(refreshWorkerBar);

document.getElementById("dashboard-package-filter")?.addEventListener("change", () => {
  refreshDashboard().catch((e) => console.error(e));
});

document.querySelectorAll(".wizard-step").forEach((btn) => {
  btn.addEventListener("click", () => {
    goWizardStep(Number(btn.dataset.wizardStep)).catch((e) => alert(e.message));
  });
});

async function restoreWizardSession() {
  if (!wizardAssetId) return;
  const asset = await fillMotherFormFromAsset(wizardAssetId);
  if (!asset) return;
  const drafts = await loadDraftPackages(wizardAssetId);
  if (drafts.length) {
    setWizardStep(3);
  } else {
    setWizardStep(2);
  }
}

async function init() {
  try {
    const health = await api("/health");
    document.getElementById("app-version").textContent = `v${health.version}`;
    await loadPlatforms();
    await Promise.all([
      refreshDashboard(),
      refreshAccounts(),
      refreshContent(),
      refreshQueue(),
      refreshWorkerBar(),
      refreshLlmModels(),
    ]);
    await restoreWizardSession();
    setInterval(() => {
      refreshDashboard();
      refreshQueue();
      refreshWorkerBar();
    }, 4000);
  } catch (err) {
    console.error(err);
    showBootError(`UI failed to load: ${err.message}. Hard-refresh the page (Ctrl+F5).`);
  }
}

init();
