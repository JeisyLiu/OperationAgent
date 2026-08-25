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

let platformCatalog = [];
let cachedAccounts = [];
let cachedVariants = [];
let wizardStep = 1;
let wizardAssetId = Number(sessionStorage.getItem("wizardAssetId") || 0) || null;
let reviewVariants = [];

function setWizardAssetId(id) {
  wizardAssetId = id;
  if (id) sessionStorage.setItem("wizardAssetId", String(id));
  else sessionStorage.removeItem("wizardAssetId");
}

function isSkillDraft(variant) {
  return Boolean(variant && variant.generated_by === "skill" && variant.account_id);
}

async function loadDraftPackages(assetId) {
  if (!assetId) {
    reviewVariants = [];
    return [];
  }
  const variants = await api(`/api/content/variants?asset_id=${assetId}`);
  // Keep latest draft per account_id
  const byAccount = new Map();
  for (const variant of variants) {
    if (!isSkillDraft(variant)) continue;
    const prev = byAccount.get(variant.account_id);
    if (!prev || variant.id > prev.id) {
      byAccount.set(variant.account_id, variant);
    }
  }
  reviewVariants = Array.from(byAccount.values()).sort((a, b) => b.id - a.id);
  return reviewVariants;
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

function platformLabel(platformId) {
  const match = platformCatalog.find((p) => p.id === platformId);
  if (!match) return platformId;
  return match.publishable ? match.display_name : `${match.display_name} (login only)`;
}

function renderPlatformOptions(selectId, { publishableOnly = false } = {}) {
  const select = document.getElementById(selectId);
  if (!select) return;
  const items = platformCatalog.filter((p) => !publishableOnly || p.publishable);
  select.innerHTML = items
    .map(
      (p) =>
        `<option value="${p.id}">${p.display_name}${p.publishable ? "" : " (login only)"}</option>`
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
          <h4>${escapeHtml(meta.display_name)}${meta.publishable ? "" : " (login only)"}</h4>
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
  container.innerHTML = reviewVariants
    .map((v) => {
      const publishable = isPublishable(v.platform);
      const choices = sectionChoices(v.platform);
      const sectionField = choices.length
        ? `<label>${sectionLabel(v.platform)}
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
      return `
        <article class="package-card" data-variant-id="${v.id}">
          <div class="package-card-header">
            <label class="check-row">
              <input type="checkbox" name="enqueue_variant" value="${v.id}" data-account-id="${v.account_id}" ${publishable ? "checked" : ""} />
              <strong>${escapeHtml(v.account_name || `Account #${v.account_id}`)}</strong>
              <span>· ${escapeHtml(platformLabel(v.platform))}</span>
            </label>
            <span class="package-badge ${publishable ? "publishable" : "login-only"}">${publishable ? "publishable" : "login only（可勾选审阅，入队会被拒绝）"}</span>
          </div>
          <label>Title
            <input data-field="title" data-variant-id="${v.id}" value="${escapeHtml(v.title || "")}" />
          </label>
          <label>Caption
            <textarea data-field="caption" data-variant-id="${v.id}" rows="4">${escapeHtml(v.caption || "")}</textarea>
          </label>
          <label>Hashtags (comma-separated)
            <input data-field="hashtags" data-variant-id="${v.id}" value="${escapeHtml((v.hashtags || []).join(", "))}" />
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

async function refreshContent() {
  const assets = await api("/api/content/assets");
  cachedVariants = await api("/api/content/variants");
  const draftCountByAsset = cachedVariants.reduce((acc, v) => {
    if (!isSkillDraft(v)) return acc;
    acc[v.asset_id] = (acc[v.asset_id] || 0) + 1;
    return acc;
  }, {});
  document.getElementById("content-list").innerHTML = [
    ...assets.map((a) => {
      const drafts = draftCountByAsset[a.id] || 0;
      const current = wizardAssetId === a.id ? " · current" : "";
      return `<div class="row">
        <div>Asset #${a.id}${current}</div>
        <div>${escapeHtml(a.title)}</div>
        <div>${a.status} · ${drafts} draft(s)</div>
        <div class="actions">
          <button type="button" data-resume-asset="${a.id}">Resume</button>
        </div>
      </div>`;
    }),
    ...cachedVariants
      .filter((v) => isSkillDraft(v))
      .slice(0, 20)
      .map(
        (v) =>
          `<div class="row"><div>Draft #${v.id}</div><div>${platformLabel(v.platform)}</div><div>${escapeHtml(
            (v.title || v.caption || "").slice(0, 60)
          )}</div><div>acct #${v.account_id || "-"} · asset #${v.asset_id}</div></div>`
      ),
  ].join("") || `<div class="hint">No assets yet.</div>`;

  document.querySelectorAll("[data-resume-asset]").forEach((btn) => {
    btn.onclick = () => resumeWizardAsset(Number(btn.dataset.resumeAsset)).catch((e) => alert(e.message));
  });
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
  try {
    const result = await api(`/api/content/assets/${wizardAssetId}/generate-variants`, {
      method: "POST",
      body: JSON.stringify({ account_ids: accountIds }),
    });
    document.getElementById("generate-result").textContent = JSON.stringify(result, null, 2);
    await loadDraftPackages(wizardAssetId);
    renderReviewPackages();
    setWizardStep(3);
    await refreshContent();
  } catch (err) {
    alert(err.message);
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
  const items = Array.from(document.querySelectorAll('input[name="enqueue_variant"]:checked')).map((el) => {
    const variantId = Number(el.value);
    const variant = editMap[variantId];
    return {
      content_variant_id: variantId,
      account_id: Number(el.dataset.accountId),
      _variant: variant,
    };
  });
  if (items.length === 0) {
    alert("Select at least one publishable package.");
    return;
  }
  try {
    for (const item of items) {
      if (item._variant) {
        await api(`/api/content/variants/${item.content_variant_id}`, {
          method: "PATCH",
          body: JSON.stringify({
            title: item._variant.title || null,
            caption: item._variant.caption || null,
            hashtags: item._variant.hashtags || [],
            section: item._variant.section || "",
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
    alert(`Created ${result.created.length} job(s). Failed: ${result.failed.length}`);
    if (result.failed.length) console.log(result.failed);
    refreshQueue();
    refreshDashboard();
  } catch (err) {
    alert(err.message);
  }
};

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
    `Worker: ${status.running ? "running" : "stopped"} | adapter=${status.adapter_status}`;
  document.getElementById("current-job").textContent =
    `Current job: ${status.current_job_id ?? "none"}`;
}

document.getElementById("btn-pause").onclick = () => api("/api/worker/pause", { method: "POST" }).then(refreshWorkerBar);
document.getElementById("btn-stop").onclick = () => api("/api/worker/stop", { method: "POST" }).then(refreshWorkerBar);

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
