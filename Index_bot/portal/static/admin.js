/** Admin sidebar — dashboard, libraries, pending, watch catalog, tracking */
let adminPendingPage = 1;
let adminBatchPage = 1;
let adminSection = "dashboard";
let watchLibPage = 1;
let watchLibFilter = "all";
let watchLibQuery = "";
let watchLibSort = "published_at";
let watchLibOrder = "desc";
let adminBrowseQuery = "";
let publishAllPollTimer = null;
let trackingFilter = "all";
let trackingCompletion = "all";
let trackingPage = 1;
let requestsPage = 1;
let metadataGapsFilter = "all";
let metadataGapsPage = 1;
const ADMIN_LIST_PAGE_SIZE = 12;
const POSTER_GRID_PAGE_SIZE = 28;
const METADATA_GAPS_PAGE_SIZE = 40;
const tmdbCache = {};
const TITLE_REMAP_COLLAPSED_KEY = "portal_title_remap_collapsed";

const PENDING_LANE_OPTIONS = [
  { id: "media", label: "Media library", icon: "🎬" },
  { id: "adult", label: "Adult vault", icon: "🔒" },
  { id: "course", label: "Course", icon: "🎓" },
  { id: "archive", label: "Archive", icon: "📦" },
  { id: "shortform", label: "Shortform", icon: "📱" },
];

function laneAllowsTmdb(lane) {
  const l = (lane || "").toLowerCase();
  return l === "media" || l === "adult";
}

async function playPendingFile(uploadId, canStream, fileName, browserPlay) {
  if (browserPlay && typeof window.playInBrowser === "function") {
    window.playInBrowser(uploadId, fileName);
    return;
  }
  if (canStream && typeof window.playInBrowser === "function") {
    window.playInBrowser(uploadId, fileName);
    return;
  }
  if (typeof window.sendToTelegram === "function") {
    await window.sendToTelegram(uploadId);
    return;
  }
  try {
    const r = await api(`/api/play/${uploadId}`, { method: "POST" });
    toast(r.message || (r.ok ? "Sent to Telegram" : r.error || "Failed"));
  } catch (e) {
    toast(e.message || "Could not play");
  }
}

async function pollMp4Convert(uploadId, btn) {
  const maxTries = 360;
  for (let i = 0; i < maxTries; i++) {
    await new Promise((r) => setTimeout(r, 2000));
    const st = await adminApi(`/api/admin/uploads/${uploadId}/convert-mp4`);
    if (st.phase === "complete") {
      toast("MP4 ready — use Browser play (subtitles preserved when possible)");
      btn.textContent = "✓ MP4 ready";
      btn.disabled = false;
      return;
    }
    if (st.phase === "failed") {
      toast(st.error || "Conversion failed");
      btn.textContent = "🎞 Convert MP4";
      btn.disabled = false;
      return;
    }
    const label =
      st.phase === "downloading"
        ? "⬇ Converting…"
        : st.phase === "converting"
          ? "🎞 Converting…"
          : "🎞 Converting…";
    btn.textContent = label;
  }
  toast("Conversion still running — check again later");
  btn.textContent = "🎞 Convert MP4";
  btn.disabled = false;
}

function mountPendingPlayButtons(
  actionsEl,
  uploadId,
  canStream,
  fileName,
  browserFriendly,
  opts = {}
) {
  const wrap = document.createElement("div");
  wrap.className = "pending-play-btns";
  const play = document.createElement("button");
  play.type = "button";
  play.className = "btn secondary btn-sm";
  play.textContent = "▶ Browser";
  play.title = window.portalFfmpegTranscode
    ? "Play in browser (MKV/AVI converted to MP4 via ffmpeg)"
    : "Play in browser";
  play.onclick = () => playPendingFile(uploadId, canStream, fileName, true);
  wrap.append(play);
  const tg = document.createElement("button");
  tg.type = "button";
  tg.className = "btn secondary btn-sm";
  tg.textContent = "📱 Telegram";
  tg.title = "Send file to your Telegram chat (best for MKV)";
  tg.onclick = () => {
    if (typeof window.sendToTelegram === "function") {
      window.sendToTelegram(uploadId);
    }
  };
  wrap.append(tg);
  if (opts.canConvert && window.portalFfmpegTranscode) {
    const conv = document.createElement("button");
    conv.type = "button";
    conv.className = "btn ghost btn-sm";
    conv.textContent = opts.mp4Cached ? "✓ MP4 ready" : "🎞 Convert MP4";
    conv.title =
      "Pre-convert to MP4 on server (keeps embedded + matching .srt sidecar subtitles)";
    if (!opts.mp4Cached) {
      conv.onclick = async () => {
        conv.disabled = true;
        conv.textContent = "🎞 Starting…";
        try {
          const r = await adminApi(`/api/admin/uploads/${uploadId}/convert-mp4`, {
            method: "POST",
          });
          if (!r.ok) {
            toast(r.error || "Could not start conversion");
            conv.textContent = "🎞 Convert MP4";
            conv.disabled = false;
            return;
          }
          if (r.phase === "complete") {
            toast(r.message || "MP4 already ready");
            conv.textContent = "✓ MP4 ready";
            conv.disabled = false;
            return;
          }
          await pollMp4Convert(uploadId, conv);
        } catch (e) {
          toast(e.message || "Conversion failed");
          conv.textContent = "🎞 Convert MP4";
          conv.disabled = false;
        }
      };
    } else {
      conv.disabled = true;
    }
    wrap.append(conv);
  }
  actionsEl.insertBefore(wrap, actionsEl.firstChild);
}

function mountPendingLaneSelect(actionsEl, currentLane, target) {
  const mixed = currentLane === "mixed";
  const cur = mixed ? "" : (currentLane || "media").toLowerCase();
  const label = document.createElement("label");
  label.className = "pending-lane-select-wrap";
  label.textContent = "Lane";
  const sel = document.createElement("select");
  sel.className = "input input-sm portal-select pending-lane-select";
  if (mixed) {
    const opt = document.createElement("option");
    opt.value = "";
    opt.textContent = "— mixed (pick one) —";
    opt.selected = true;
    sel.append(opt);
  }
  PENDING_LANE_OPTIONS.forEach((l) => {
    const opt = document.createElement("option");
    opt.value = l.id;
    opt.textContent = `${l.icon} ${l.label}`;
    if (!mixed && l.id === cur) opt.selected = true;
    sel.append(opt);
  });
  sel.onchange = () => {
    const lane = sel.value;
    if (!lane) return;
    if (target.batchKey != null) {
      setPendingBatchLane(target.batchKey, lane, target.fileIds || []);
    } else {
      setPendingUploadLane(target.uploadId, lane);
    }
  };
  label.append(sel);
  actionsEl.insertBefore(label, actionsEl.firstChild);
}

async function setPendingUploadLane(uploadId, lane) {
  try {
    const r = await adminApi(`/api/admin/pending/${uploadId}/lane`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ lane }),
    });
    toast(r.message || (r.ok ? "Lane updated" : r.error || "Failed"));
    if (r.ok || r.removed_from_pending) {
      await loadAdminPending(adminPendingPage, adminBatchPage);
    }
  } catch (e) {
    toast(e.message || "Failed");
  }
}

async function setPendingBatchLane(matchKey, lane, fileIds = []) {
  try {
    const r = await adminApi(
      `/api/admin/pending/batches/${encodeURIComponent(matchKey)}/lane`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ lane, file_ids: fileIds }),
      }
    );
    toast(r.message || (r.ok ? "Lane updated" : r.error || "Failed"));
    if (r.ok || (r.removed_from_pending ?? 0) > 0) {
      await loadAdminPending(adminPendingPage, adminBatchPage);
    }
  } catch (e) {
    toast(e.message || "Failed");
  }
}

const ADMIN_SECTION_KEY = "portal_admin_section";
const WATCH_FILTER_KEY = "portal_watch_filter";

/** Browse API scope for the active admin library section (overrides stale browseScope). */
function getAdminBrowseScope() {
  const map = {
    media: "media",
    courses: "course",
    archive: "archive",
    shortform: "shortform",
    adult: "adult",
    noncatalog: "non_catalog",
  };
  return map[adminSection] || null;
}
window.getAdminBrowseScope = getAdminBrowseScope;

const SECTION_TITLES = {
  dashboard: "Home",
  media: "Media library",
  courses: "Course library",
  archive: "Archive library",
  shortform: "Shortform library",
  adult: "Adult library",
  noncatalog: "Non-catalog (skip catalog)",
  tracking: "Tracking list",
  pending: "Pending list",
  watch: "Watch library",
  metadata: "Metadata gaps",
  "filename-rules": "Filename rules",
  pipeline: "Upload pipeline",
  channels: "Channel monitoring",
  requests: "User requests",
  watchlist: "Watch later",
  favorites: "Favorites",
};

function adminApi(path, opts = {}) {
  return api(path, opts);
}

function showAdminListSkeleton(container, count = ADMIN_LIST_PAGE_SIZE, variant = "info") {
  if (!container) return;
  container.innerHTML = "";
  container.classList.add("is-loading");
  for (let i = 0; i < count; i++) {
    const sk = document.createElement("div");
    sk.className = variant === "grid" ? "skeleton-card" : "skeleton-info-card";
    container.appendChild(sk);
  }
}

function renderAdminPagination(navEl, page, pages, onPage) {
  if (!navEl) return;
  navEl.innerHTML = "";
  navEl.classList.toggle("hidden", pages <= 1);
  if (pages <= 1) return;

  const addBtn = (label, targetPage, disabled = false, active = false) => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "page-btn" + (active ? " active" : "");
    b.textContent = label;
    b.disabled = disabled;
    if (!disabled && !active) {
      b.onclick = () => {
        onPage(targetPage);
        globalThis.scrollTo({ top: 0, behavior: "smooth" });
      };
    }
    navEl.appendChild(b);
  };

  addBtn("«", Math.max(1, page - 1), page <= 1);
  const maxBtns = 9;
  let start = Math.max(1, page - 4);
  let end = Math.min(pages, start + maxBtns - 1);
  start = Math.max(1, end - maxBtns + 1);
  if (start > 1) {
    addBtn("1", 1);
    if (start > 2) {
      const ell = document.createElement("span");
      ell.className = "pagination-ellipsis sub";
      ell.textContent = "…";
      navEl.appendChild(ell);
    }
  }
  for (let p = start; p <= end; p++) addBtn(String(p), p, false, p === page);
  if (end < pages) {
    if (end < pages - 1) {
      const ell = document.createElement("span");
      ell.className = "pagination-ellipsis sub";
      ell.textContent = "…";
      navEl.appendChild(ell);
    }
    addBtn(String(pages), pages);
  }
  addBtn("»", Math.min(pages, page + 1), page >= pages);

  const jump = document.createElement("label");
  jump.className = "pagination-jump sub";
  const inp = document.createElement("input");
  inp.type = "number";
  inp.min = "1";
  inp.max = String(pages);
  inp.value = String(page);
  inp.className = "page-jump-input";
  inp.setAttribute("aria-label", "Go to page");
  jump.append("Go ", inp, ` / ${pages}`);
  inp.addEventListener("keydown", (e) => {
    if (e.key !== "Enter") return;
    const n = parseInt(inp.value, 10);
    if (n >= 1 && n <= pages && n !== page) onPage(n);
  });
  navEl.appendChild(jump);
}

window.renderPortalPagination = renderAdminPagination;

function libraryPosterCard(options = {}) {
  const {
    title,
    posterUrl,
    subText = "",
    badgeText = "",
    badgeClass = "",
    onClick,
    overlayButton,
    actionsHtml,
  } = options;
  const div = document.createElement("div");
  div.className = "card library-poster-card";
  if (overlayButton) div.append(overlayButton);
  const img = document.createElement("img");
  img.src = posterUrl || "/static/placeholder.svg";
  img.alt = title || "";
  img.loading = "lazy";
  img.onerror = () => {
    img.src = "/static/placeholder.svg";
  };
  const meta = document.createElement("div");
  meta.className = "meta";
  const t = document.createElement("div");
  t.className = "title";
  t.textContent = title || "?";
  meta.append(t);
  if (subText) {
    const sub = document.createElement("div");
    sub.className = "sub";
    sub.textContent = subText;
    meta.append(sub);
  }
  if (badgeText) {
    const badge = document.createElement("span");
    badge.className = `badge ${badgeClass}`.trim();
    badge.textContent = badgeText;
    meta.append(badge);
  }
  if (actionsHtml) {
    const actions = document.createElement("div");
    actions.className = "card-actions";
    actions.innerHTML = actionsHtml;
    meta.append(actions);
  }
  div.append(img, meta);
  if (onClick) div.onclick = onClick;
  return div;
}

function tmdbCtxKey(kind, id) {
  return `${kind}:${id}`;
}

function hideAllAdminSections() {
  document.querySelectorAll(".admin-section-view").forEach((v) => v.classList.add("hidden"));
  document.getElementById("browseView")?.classList.add("hidden");
  document.getElementById("searchView")?.classList.add("hidden");
  document.getElementById("detailView")?.classList.add("hidden");
}

function setSidebarActive(section) {
  document.querySelectorAll(".sidebar-link").forEach((b) => {
    b.classList.toggle("active", b.dataset.adminSection === section);
  });
}

const SIDEBAR_COLLAPSE_KEY = "portal_sidebar_collapsed";

function isCompactSidebar() {
  return window.matchMedia("(max-width: 1024px)").matches;
}

function syncSidebarBackdrop() {
  const app = document.getElementById("app");
  const backdrop = document.getElementById("sidebarBackdrop");
  if (!app || !backdrop) return;
  const open = app.classList.contains("sidebar-open");
  const collapsed = app.classList.contains("sidebar-collapsed");
  if (isCompactSidebar() && open && !collapsed) {
    backdrop.classList.remove("hidden");
  } else {
    backdrop.classList.add("hidden");
  }
}

function syncAdminLayout() {
  const app = document.getElementById("app");
  if (!app?.classList.contains("is-admin")) return;
  if (!isCompactSidebar()) {
    app.classList.remove("sidebar-open");
  }
  syncSidebarBackdrop();
}

function applySidebarCollapsed(collapsed, openIfCompact = false) {
  const app = document.getElementById("app");
  const btn = document.getElementById("sidebarCollapseBtn");
  if (!app) return;
  app.classList.toggle("sidebar-collapsed", collapsed);
  if (isCompactSidebar() && collapsed && openIfCompact) {
    app.classList.add("sidebar-open");
  }
  syncSidebarBackdrop();
  if (btn) {
    btn.setAttribute("aria-expanded", collapsed ? "false" : "true");
    btn.title = collapsed ? "Expand menu" : "Collapse menu";
    btn.setAttribute("aria-label", collapsed ? "Expand menu" : "Collapse menu");
  }
}

function initSidebarCollapse() {
  const collapsed = localStorage.getItem(SIDEBAR_COLLAPSE_KEY) === "1";
  applySidebarCollapsed(collapsed);
  document.getElementById("sidebarCollapseBtn")?.addEventListener("click", (e) => {
    e.stopPropagation();
    const app = document.getElementById("app");
    const next = !app?.classList.contains("sidebar-collapsed");
    const wasOpen = app?.classList.contains("sidebar-open");
    applySidebarCollapsed(next, next && (wasOpen || isCompactSidebar()));
    localStorage.setItem(SIDEBAR_COLLAPSE_KEY, next ? "1" : "0");
  });
}

function closeMobileSidebar() {
  document.getElementById("app")?.classList.remove("sidebar-open");
  syncSidebarBackdrop();
}

function openMobileSidebar() {
  document.getElementById("app")?.classList.add("sidebar-open");
  syncSidebarBackdrop();
}

async function initAdminShell() {
  const sidebar = document.getElementById("adminSidebar");
  sidebar?.classList.remove("hidden");

  const toggle = document.getElementById("sidebarToggle");
  toggle?.classList.remove("hidden");
  toggle?.addEventListener("click", () => {
    const app = document.getElementById("app");
    if (!app || !isCompactSidebar()) return;
    if (app.classList.contains("sidebar-open")) closeMobileSidebar();
    else openMobileSidebar();
  });
  document.getElementById("sidebarBackdrop")?.addEventListener("click", closeMobileSidebar);
  initSidebarCollapse();
  syncAdminLayout();
  window.addEventListener("resize", syncAdminLayout);

  document.querySelectorAll(".sidebar-link").forEach((btn) => {
    btn.addEventListener("click", () => {
      loadAdminSection(btn.dataset.adminSection);
      const app = document.getElementById("app");
      const keepMiniRail =
        isCompactSidebar() && app?.classList.contains("sidebar-collapsed");
      if (!keepMiniRail) closeMobileSidebar();
    });
  });

  document.querySelectorAll("[data-goto]").forEach((btn) => {
    btn.addEventListener("click", () => loadAdminSection(btn.dataset.goto));
  });

  const trackingKindSelect = document.getElementById("trackingKindSelect");
  const trackingStatusSelect = document.getElementById("trackingStatusSelect");
  if (trackingKindSelect) {
    trackingKindSelect.value = trackingFilter;
    trackingKindSelect.addEventListener("change", () => {
      trackingFilter = trackingKindSelect.value || "all";
      trackingPage = 1;
      loadAdminTracking(1);
    });
  }
  if (trackingStatusSelect) {
    trackingStatusSelect.value = trackingCompletion;
    trackingStatusSelect.addEventListener("change", () => {
      trackingCompletion = trackingStatusSelect.value || "all";
      trackingPage = 1;
      loadAdminTracking(1);
    });
  }

  document.querySelectorAll("[data-watch-filter]").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll("[data-watch-filter]").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      watchLibFilter = btn.dataset.watchFilter || "all";
      localStorage.setItem(WATCH_FILTER_KEY, watchLibFilter);
      watchLibPage = 1;
      loadWatchLibrary(1);
    });
  });

  const watchSort = document.getElementById("watchLibSort");
  const watchOrder = document.getElementById("watchLibOrder");
  if (watchSort) {
    watchSort.value = watchLibSort;
    watchSort.addEventListener("change", () => {
      watchLibSort = watchSort.value || "published_at";
      watchLibPage = 1;
      loadWatchLibrary(1);
    });
  }
  if (watchOrder) {
    watchOrder.value = watchLibOrder;
    watchOrder.addEventListener("change", () => {
      watchLibOrder = watchOrder.value || "desc";
      watchLibPage = 1;
      loadWatchLibrary(1);
    });
  }

  document.querySelectorAll("[data-metadata-filter]").forEach((btn) => {
    btn.addEventListener("click", () => {
      document
        .querySelectorAll("[data-metadata-filter]")
        .forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      metadataGapsFilter = btn.dataset.metadataFilter || "all";
      metadataGapsPage = 1;
      loadMetadataGaps(1);
    });
  });

  const savedFilter = localStorage.getItem(WATCH_FILTER_KEY);
  if (savedFilter && ["all", "published", "unpublished"].includes(savedFilter)) {
    watchLibFilter = savedFilter;
    document.querySelectorAll("[data-watch-filter]").forEach((b) => {
      b.classList.toggle("active", b.dataset.watchFilter === watchLibFilter);
    });
  }

  bindFilenameRuleForms();

  await loadAdminSection(getSavedAdminSection(), { persist: false });
}

function getSavedAdminSection() {
  const s = localStorage.getItem(ADMIN_SECTION_KEY);
  return s && SECTION_TITLES[s] ? s : "dashboard";
}

async function loadAdminSection(section, { persist = true } = {}) {
  adminSection = section || "dashboard";
  if (persist) {
    localStorage.setItem(ADMIN_SECTION_KEY, adminSection);
  }
  setSidebarActive(adminSection);
  hideAllAdminSections();
  window.setPortalPageTitle?.(SECTION_TITLES[adminSection] || "Admin");
  updateAdminSearchPlaceholder();

  const browseSections = [
    "media",
    "courses",
    "archive",
    "shortform",
    "adult",
    "noncatalog",
    "watchlist",
    "favorites",
  ];
  if (browseSections.includes(adminSection)) {
    const scope = getAdminBrowseScope() || "media";
    window.setPortalBrowseScope?.(scope);
    document.getElementById("browseView")?.classList.remove("hidden");
    const showChrome =
      adminSection === "media" ||
      adminSection === "courses" ||
      adminSection === "archive" ||
      adminSection === "shortform" ||
      adminSection === "adult" ||
      adminSection === "noncatalog";
    if (typeof setBrowseChromeVisible === "function") {
      setBrowseChromeVisible(showChrome);
    }
    if (adminSection === "watchlist" && typeof loadWatchlist === "function") {
      await loadWatchlist();
    } else if (adminSection === "favorites" && typeof loadFavorites === "function") {
      await loadFavorites();
    } else if (typeof loadPortalBrowse === "function") {
      await loadPortalBrowse();
    }
    return;
  }

  if (typeof setBrowseChromeVisible === "function") {
    setBrowseChromeVisible(false);
  }

  if (adminSection === "dashboard") {
    document.getElementById("dashboardView")?.classList.remove("hidden");
    await loadAdminDashboard();
  } else if (adminSection === "pending") {
    document.getElementById("pendingView")?.classList.remove("hidden");
    await loadAdminPending(1, 1);
  } else if (adminSection === "requests") {
    document.getElementById("requestsView")?.classList.remove("hidden");
    await loadAdminRequests();
  } else if (adminSection === "tracking") {
    document.getElementById("trackingView")?.classList.remove("hidden");
    const kindSel = document.getElementById("trackingKindSelect");
    const statusSel = document.getElementById("trackingStatusSelect");
    if (kindSel) kindSel.value = trackingFilter;
    if (statusSel) statusSel.value = trackingCompletion;
    await loadAdminTracking(trackingPage);
  } else if (adminSection === "watch") {
    document.getElementById("watchLibraryView")?.classList.remove("hidden");
    await loadWatchLibrary(1);
  } else if (adminSection === "metadata") {
    document.getElementById("metadataGapsView")?.classList.remove("hidden");
    await loadMetadataGaps(1);
  } else if (adminSection === "filename-rules") {
    document.getElementById("filenameRulesView")?.classList.remove("hidden");
    await loadFilenameRules();
  } else if (adminSection === "pipeline") {
    document.getElementById("pipelineView")?.classList.remove("hidden");
    await loadPipelineAdmin();
  } else if (adminSection === "channels") {
    document.getElementById("channelsMonitorView")?.classList.remove("hidden");
    await loadChannelsMonitor();
  }
}

function formatMonitorWhen(iso) {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return "—";
    return d.toLocaleString();
  } catch {
    return "—";
  }
}

function renderChannelMonitorTable(rows, emptyText) {
  if (!rows?.length) {
    return `<p class="sub">${escapeHtml(emptyText)}</p>`;
  }
  const head = `<thead><tr>
    <th>Channel</th>
    <th>Lane</th>
    <th>Indexed</th>
    <th>Last indexed</th>
    <th>Last pull</th>
    <th>Last pull +</th>
    <th>Seen msg</th>
  </tr></thead>`;
  const body = rows
    .map((r) => {
      const name = r.username
        ? `@${escapeHtml(r.username)}`
        : escapeHtml(r.title || r.channel_id);
      const inactive = r.is_active ? "" : ' <span class="badge missing">inactive</span>';
      return `<tr>
        <td><strong>${name}</strong>${inactive}<br><span class="sub mono">${escapeHtml(r.channel_id)}</span></td>
        <td><code>${escapeHtml(r.content_lane || "")}</code></td>
        <td>${r.indexed_count ?? 0}${r.backfill_count ? ` <span class="sub">(+${r.backfill_count} backfill)</span>` : ""}</td>
        <td>${formatMonitorWhen(r.last_indexed_at)}</td>
        <td>${formatMonitorWhen(r.last_pull_at)}</td>
        <td>${r.last_pull_indexed != null ? r.last_pull_indexed : "—"}</td>
        <td>${r.last_seen_message_id != null ? r.last_seen_message_id : "—"}</td>
      </tr>`;
    })
    .join("");
  return `<table class="channel-monitor-table">${head}<tbody>${body}</tbody></table>`;
}

async function loadChannelsMonitor() {
  const summaryEl = document.getElementById("channelsMonitorSummary");
  const botEl = document.getElementById("channelsBotIndexTable");
  const watchEl = document.getElementById("channelsMemberWatchTable");
  const ingestEl = document.getElementById("channelsIngestTable");
  const ingestSec = document.getElementById("channelsIngestSection");
  if (!summaryEl) return;

  summaryEl.innerHTML = '<p class="sub">Loading…</p>';
  if (botEl) botEl.innerHTML = "";
  if (watchEl) watchEl.innerHTML = "";

  let data;
  try {
    data = await adminApi("/api/admin/channels/monitoring");
  } catch (e) {
    summaryEl.innerHTML = `<p class="sub">Failed to load — ${escapeHtml(e.message || "error")}</p>`;
    return;
  }

  const watchOn = data.member_watch_enabled ? "on" : "off";
  const interval = Math.round((data.member_watch_interval_s || 300) / 60);
  summaryEl.innerHTML = `
    <div class="stat-card"><span class="stat-n">${data.bot_indexed_count ?? 0}</span><span class="stat-l">Bot live index</span></div>
    <div class="stat-card"><span class="stat-n">${data.member_watch_count ?? 0}</span><span class="stat-l">Member watch</span></div>
    <div class="stat-card"><span class="stat-n">${watchOn}</span><span class="stat-l">Member watch (${interval}m tick)</span></div>
  `;

  if (botEl) {
    botEl.innerHTML = renderChannelMonitorTable(
      data.bot_indexed,
      "No bot-indexed channels yet — add the bot as admin to a channel or post a file."
    );
  }
  if (watchEl) {
    watchEl.innerHTML = renderChannelMonitorTable(
      data.member_watch,
      watchOn === "on"
        ? "No member-watch channels — only channels where the bot is not admin."
        : "Member watch is disabled in .env (TELETHON_MEMBER_WATCH_ENABLED)."
    );
  }
  const ingest = data.ingest_sinks || [];
  if (ingestSec && ingestEl) {
    if (ingest.length) {
      ingestSec.classList.remove("hidden");
      ingestEl.innerHTML = renderChannelMonitorTable(ingest, "No ingest sink.");
    } else {
      ingestSec.classList.add("hidden");
    }
  }
}

async function loadPipelineAdmin() {
  const statusEl = document.getElementById("pipelineStatusPanel");
  const defaultsEl = document.getElementById("pipelineDefaultsList");
  const jobsEl = document.getElementById("pipelineJobsList");
  const dupesEl = document.getElementById("pipelineDupesList");
  if (!statusEl) return;

  const [status, defaults, jobs, dupes] = await Promise.all([
    adminApi("/api/admin/pipeline/status"),
    adminApi("/api/admin/pipeline/defaults"),
    adminApi("/api/admin/upload-jobs"),
    adminApi("/api/admin/duplicate-holds"),
  ]);

  const cfg = status.config || {};
  const checks = (status.checks || [])
    .map((c) => {
      const mark = c.ok === true ? "✅" : c.ok === false ? "❌" : "➖";
      return `<li>${mark} ${escapeHtml(c.label)}${c.hint && !c.ok ? ` — <span class="sub">${escapeHtml(c.hint)}</span>` : ""}</li>`;
    })
    .join("");
  statusEl.innerHTML = `
    <div class="admin-stats">
      <div class="stat-card"><span class="stat-n">${status.duplicate_holds ?? 0}</span><span class="stat-l">Duplicate holds</span></div>
      <div class="stat-card"><span class="stat-n">${status.route_pending ?? 0}</span><span class="stat-l">Route queue</span></div>
    </div>
    <p class="sub">Classify ingest: <b>${cfg.classify_ingest ? "on" : "off"}</b> · Auto-route: <b>${cfg.auto_route ? "on" : "off"}</b> · Auto-publish watch: <b>${cfg.auto_publish_watch ? "on" : "off"}</b></p>
    <ul class="admin-checklist">${checks}</ul>
  `;

  const chOpts = (defaults.postable_channels || [])
    .map(
      (c) =>
        `<option value="${escapeHtml(c.channel_id)}">${escapeHtml(c.title || c.username || c.channel_id)}</option>`
    )
    .join("");
  defaultsEl.innerHTML = (defaults.upload_types || [])
    .map((t) => {
      const sel = `<select class="input pipeline-src-select" data-upload-type="${escapeHtml(t.upload_type)}">
        <option value="">— not set —</option>${chOpts}
      </select>`;
      const cur = t.source_channel_id || "";
      return `<div class="admin-list-row pipeline-default-row">
        <span><b>${escapeHtml(t.label || t.upload_type)}</b></span>
        ${sel}
        <button type="button" class="btn secondary btn-sm pipeline-save-src" data-upload-type="${escapeHtml(t.upload_type)}">Save</button>
      </div>`;
    })
    .join("");
  defaultsEl.querySelectorAll(".pipeline-src-select").forEach((sel) => {
    const row = sel.closest(".pipeline-default-row");
    const ut = sel.dataset.uploadType;
    const match = (defaults.upload_types || []).find((x) => x.upload_type === ut);
    if (match?.source_channel_id) sel.value = match.source_channel_id;
  });
  defaultsEl.querySelectorAll(".pipeline-save-src").forEach((btn) => {
    btn.onclick = async () => {
      const ut = btn.dataset.uploadType;
      const sel = defaultsEl.querySelector(`select[data-upload-type="${ut}"]`);
      const source_channel_id = sel?.value || null;
      await adminApi(`/api/admin/pipeline/defaults/${encodeURIComponent(ut)}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ source_channel_id }),
      });
      await loadPipelineAdmin();
    };
  });

  const mp = defaults.media_publish_channel;
  if (mp) {
    defaultsEl.insertAdjacentHTML(
      "beforeend",
      `<p class="sub">Media publish (watch library): <b>${escapeHtml(mp.title || mp.username || mp.channel_id)}</b> — set in bot Library setup</p>`
    );
  }

  jobsEl.innerHTML = (jobs.jobs || []).length
    ? (jobs.jobs || [])
        .map(
          (j) =>
            `<div class="admin-list-row"><b>#${j.id}</b> ${escapeHtml(j.name)} · <code>${escapeHtml(j.status)}</code> · ${escapeHtml(j.content_lane)} · ${j.total_items} items · source ${j.target_channel_id ? "✓" : "—"}</div>`
        )
        .join("")
    : "<p class=\"sub\">No upload jobs yet — create one in Telegram Upload pipeline.</p>";

  dupesEl.innerHTML = (dupes.items || []).length
    ? (dupes.items || [])
        .map(
          (d) =>
            `<div class="admin-list-row">#${d.id} ${escapeHtml(d.file_name)} · lane ${escapeHtml(d.content_lane)} · dup of #${d.duplicate_of_upload_id || "?"}</div>`
        )
        .join("")
    : "<p class=\"sub\">No duplicate holds.</p>";
}

async function loadAdminDashboard() {
  const stats = await adminApi("/api/admin/dashboard");
  const el = document.getElementById("adminStats");
  if (!el) return;
  const lanes = stats.channels_by_lane || {};
  const laneText = Object.entries(lanes)
    .map(([k, v]) => `${k}: ${v}`)
    .join(" · ");
  el.innerHTML = `
    <div class="stat-card"><span class="stat-n">${stats.media_library_titles ?? 0}</span><span class="stat-l">Media titles</span></div>
    <div class="stat-card"><span class="stat-n">${stats.course_library_titles ?? 0}</span><span class="stat-l">Courses (published)</span></div>
    <div class="stat-card"><span class="stat-n">${stats.archive_library_titles ?? 0}</span><span class="stat-l">Archive titles</span></div>
    <div class="stat-card"><span class="stat-n">${stats.shortform_library_titles ?? 0}</span><span class="stat-l">Shortform titles</span></div>
    <div class="stat-card"><span class="stat-n">${stats.adult_library_titles ?? 0}</span><span class="stat-l">Adult vault titles</span></div>
    <div class="stat-card"><span class="stat-n">${stats.non_catalog_titles ?? 0}</span><span class="stat-l">Skip catalog only</span></div>
    <div class="stat-card"><span class="stat-n">${stats.published_catalog ?? 0}</span><span class="stat-l">Watch cards live</span></div>
    <div class="stat-card"><span class="stat-n">${stats.unpublished_catalog_slots ?? 0}</span><span class="stat-l">Catalog to publish</span></div>
    <div class="stat-card"><span class="stat-n">${stats.pending_confirmations ?? 0}</span><span class="stat-l">Pending review</span></div>
    <div class="stat-card"><span class="stat-n">${stats.pending_user_requests ?? 0}</span><span class="stat-l">User requests</span></div>
    <div class="stat-card"><span class="stat-n">${stats.tracking_items ?? 0}</span><span class="stat-l">Tracking items</span></div>
    <div class="stat-card"><span class="stat-n">${stats.channels_active ?? 0}</span><span class="stat-l">Active channels</span></div>
    <div class="stat-card stat-warn"><span class="stat-n">${stats.metadata_gaps?.missing_any ?? 0}</span><span class="stat-l">Metadata gaps</span></div>
    <div class="stat-card"><span class="stat-n">${stats.metadata_gaps?.no_tmdb ?? 0}</span><span class="stat-l">No TMDB id</span></div>
    <div class="stat-card"><span class="stat-n">${stats.metadata_gaps?.no_poster ?? 0}</span><span class="stat-l">No poster in DB</span></div>
    ${laneText ? `<p class="sub dashboard-lanes">Channels by lane: ${escapeHtml(laneText)}</p>` : ""}`;
}

function sortTmdbSuggestionsByPoster(list) {
  return [...(list || [])].sort((a, b) => {
    const ap = a.poster_url ? 0 : 1;
    const bp = b.poster_url ? 0 : 1;
    if (ap !== bp) return ap - bp;
    return (a.index ?? 0) - (b.index ?? 0);
  });
}

function pickPayload(data, suggestion) {
  const body = {
    suggestion_index: suggestion.index ?? 0,
    tmdb_id: suggestion.tmdb_id ?? null,
    page: data.page || 1,
  };
  if (suggestion.title) body.title = suggestion.title;
  if (suggestion.media_type) body.media_type = suggestion.media_type;
  if (suggestion.year != null && suggestion.year !== "") {
    body.year = parseInt(suggestion.year, 10);
  }
  if (data.search_query) body.search_query = data.search_query;
  return body;
}

function renderTmdbPanel(ctxKey, panelId, data, handlers) {
  const panel = document.getElementById(panelId);
  if (!panel) return;

  if (!data.tmdb_enabled) {
    panel.innerHTML = '<p class="sub">TMDB not configured (TMDB_API_KEY in .env)</p>';
    return;
  }

  const allSuggestions =
    data._accumulated && data._accumulated.length
      ? data._accumulated
      : data.suggestions || [];
  data._accumulated = allSuggestions;

  let intro = `<p class="sub"><b>TMDB:</b> ${escapeHtml(data.search_label || "")}`;
  if (data.batch && data.file_count) {
    intro += ` · <b>${data.file_count}</b> files in batch`;
  }
  intro += "</p>";

  if (data.tmdb_unreachable) {
    intro +=
      '<p class="sub">Could not reach TMDB — wait a moment, then tap <b>Retry TMDB search</b>.</p>';
  } else if (!allSuggestions.length) {
    intro += '<p class="sub">No matches — try a different search below.</p>';
  } else {
    intro += `<p class="sub"><b>${allSuggestions.length}</b> match(es) loaded`;
    if (data.has_more) intro += " · more available";
    intro += ".</p>";
  }
  panel.innerHTML = intro;

  const actions = document.createElement("div");
  actions.className = "tmdb-actions-row";
  const retryBtn = document.createElement("button");
  retryBtn.type = "button";
  retryBtn.className = "btn secondary btn-sm";
  retryBtn.textContent = "🔄 Retry TMDB search";
  retryBtn.onclick = () => handlers.onRetry();
  actions.appendChild(retryBtn);
  if (data.has_more && handlers.onLoadMore) {
    const moreBtn = document.createElement("button");
    moreBtn.type = "button";
    moreBtn.className = "btn secondary btn-sm";
    moreBtn.textContent = "📄 Load more";
    moreBtn.onclick = () => handlers.onLoadMore();
    actions.appendChild(moreBtn);
  }
  panel.appendChild(actions);

  if (allSuggestions.length) {
    let filterType = data.filter_type || "all";

    const filterRow = document.createElement("div");
    filterRow.className = "tmdb-filter-row";
    const countEl = document.createElement("p");
    countEl.className = "sub";

    const grid = document.createElement("div");
    grid.className = "tmdb-suggestions";
    if (panelId.startsWith("gap-tmdb-")) {
      grid.classList.add("tmdb-suggestions--compact");
    }

    function mediaLabel(mt) {
      const m = (mt || "").toLowerCase();
      if (m === "tv" || m === "series") return "TV series";
      if (m === "movie") return "Movie";
      return mt || "?";
    }

    function renderCards() {
      grid.innerHTML = "";
      const list = allSuggestions;
      countEl.textContent = `${list.length} shown${data.has_more ? " · load more for next page" : ""}`;
      list.forEach((s) => {
      const card = document.createElement("div");
      card.className = "tmdb-card";
      const img = s.poster_url
        ? `<img src="${escapeHtml(s.poster_url)}" alt="" loading="lazy" />`
        : `<div class="tmdb-no-poster">No poster</div>`;
      const vote =
        s.vote_average != null && s.vote_average !== ""
          ? ` ★${parseFloat(s.vote_average).toFixed(1)}`
          : "";
      card.innerHTML = `
        ${img}
        <div class="tmdb-card-body">
          <div class="tmdb-card-title">${escapeHtml(s.title || "?")}</div>
          <div class="sub"><b>${escapeHtml(mediaLabel(s.media_type))}</b> · ${escapeHtml(String(s.year || "?"))}${vote}</div>
          <p class="tmdb-overview">${escapeHtml(s.overview || "")}</p>
          <button type="button" class="btn primary btn-sm" data-pick="${s.index}" data-tmdb-id="${s.tmdb_id || ""}">Select this title</button>
          ${s.tmdb_url ? `<a class="sub" href="${escapeHtml(s.tmdb_url)}" target="_blank" rel="noopener">TMDB ↗</a>` : ""}
        </div>`;
      grid.appendChild(card);
      });
    }

    ["all", "tv", "movie"].forEach((key) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = `btn secondary btn-sm${filterType === key ? " active" : ""}`;
      btn.textContent = key === "all" ? "All" : key === "tv" ? "TV series" : "Movies";
      btn.onclick = () => {
        if (handlers.onFilter) handlers.onFilter(key);
      };
      filterRow.appendChild(btn);
    });
    filterRow.appendChild(countEl);
    panel.appendChild(filterRow);
    panel.appendChild(grid);
    renderCards();

    function wirePickButtons() {
      panel.querySelectorAll("button[data-pick]").forEach((btn) => {
        btn.onclick = async () => {
          btn.disabled = true;
          try {
            const idx = parseInt(btn.dataset.pick, 10);
            const tidRaw = btn.dataset.tmdbId;
            const tid =
              tidRaw && String(tidRaw).trim() !== ""
                ? parseInt(tidRaw, 10)
                : null;
            const s =
              allSuggestions.find((x) => x.index === idx) || allSuggestions[idx];
            const pickTmdbId = tid && !Number.isNaN(tid) ? tid : s?.tmdb_id ?? null;
            if (!pickTmdbId) {
              toast("This result has no TMDB id — pick another card or search again.");
              return;
            }
            const body = pickPayload(data, {
              index: idx,
              tmdb_id: pickTmdbId,
              title: s?.title,
              media_type: s?.media_type,
              year: s?.year,
            });
            const r = await handlers.onPick(body);
            if (handlers.afterPick) {
              await handlers.afterPick(r);
              return;
            }
            toast(r.message || (r.ok ? "Linked" : r.error || "Failed"));
            if (!r.ok) return;
            if (handlers.pendingPick && r.sibling_count > 0 && !data.batch) {
              const sibBtn = document.createElement("button");
              sibBtn.type = "button";
              sibBtn.className = "btn secondary btn-sm";
              sibBtn.textContent = `📦 Apply same TMDB to ${r.sibling_count} similar`;
              sibBtn.onclick = async () => {
                const sr = await handlers.onPick({ ...body, apply_siblings: true });
                toast(sr.message || (sr.ok ? "Applied" : sr.error || "Failed"));
                if (sr.ok) loadAdminPending(adminPendingPage, adminBatchPage);
              };
              panel.appendChild(sibBtn);
            } else if (handlers.pendingPick) {
              loadAdminPending(adminPendingPage, adminBatchPage);
            }
          } catch (e) {
            toast(e.message || "TMDB pick failed");
          } finally {
            btn.disabled = false;
          }
        };
      });
    }
    wirePickButtons();
  }

  const searchRow = document.createElement("div");
  searchRow.className = "tmdb-search-row";
  const inputId = `tmdb-search-${ctxKey.replace(/[^a-z0-9]/gi, "_")}`;
  searchRow.innerHTML = `
    <input type="search" placeholder="Search TMDB…" id="${inputId}" value="${escapeHtml(data.search_query || "")}" />
    <button type="button" class="btn secondary btn-sm">Search</button>`;
  panel.appendChild(searchRow);
  searchRow.querySelector("button").onclick = () => {
    const q = document.getElementById(inputId)?.value?.trim();
    if (q) handlers.onSearch(q);
  };
}

function tmdbListParams(data, extra = {}) {
  const p = { page: String(extra.page || 1), filter_type: extra.filter_type || data.filter_type || "all" };
  if (data.search_query) p.q = data.search_query;
  return p;
}

function mergeTmdbPage(prev, next) {
  const acc = prev && prev._accumulated ? [...prev._accumulated] : [];
  const fresh = next.suggestions || [];
  const merged = sortTmdbSuggestionsByPoster(
    next.page > 1 ? [...acc, ...fresh] : fresh
  );
  return { ...next, _accumulated: merged, suggestions: merged };
}

function createUploadTmdbHandlers(uploadId, ctxKey, panelId, { pending = false, afterPick = null } = {}) {
  const apiBase = pending
    ? `/api/admin/pending/${uploadId}`
    : `/api/admin/uploads/${uploadId}`;
  const handlers = {
    onRetry: async () => {
      const r = await adminApi(`${apiBase}/tmdb-retry`, { method: "POST" });
      tmdbCache[ctxKey] = mergeTmdbPage(null, r);
      renderTmdbPanel(ctxKey, panelId, tmdbCache[ctxKey], handlers);
    },
    onPick: async (body) => {
      const r = await adminApi(`${apiBase}/tmdb-pick`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (afterPick) await afterPick(r);
      return r;
    },
    onSearch: async (q) => {
      const r = await adminApi(
        `${apiBase}/tmdb?${new URLSearchParams({ q, page: "1", filter_type: "all" })}`
      );
      tmdbCache[ctxKey] = mergeTmdbPage(null, r);
      renderTmdbPanel(ctxKey, panelId, tmdbCache[ctxKey], handlers);
    },
    onLoadMore: async () => {
      const cur = tmdbCache[ctxKey] || {};
      const page = (cur.page || 1) + 1;
      const params = tmdbListParams(cur, { page });
      const r = await adminApi(`${apiBase}/tmdb?${new URLSearchParams(params)}`);
      tmdbCache[ctxKey] = mergeTmdbPage(cur, r);
      renderTmdbPanel(ctxKey, panelId, tmdbCache[ctxKey], handlers);
    },
    onFilter: async (filterType) => {
      const cur = tmdbCache[ctxKey] || {};
      const params = tmdbListParams(cur, { page: 1, filter_type: filterType });
      const r = await adminApi(`${apiBase}/tmdb?${new URLSearchParams(params)}`);
      tmdbCache[ctxKey] = mergeTmdbPage(null, { ...r, filter_type: filterType });
      renderTmdbPanel(ctxKey, panelId, tmdbCache[ctxKey], handlers);
    },
    pendingPick: pending,
  };
  return handlers;
}

function pendingTmdbHandlers(uploadId, ctxKey, panelId) {
  return createUploadTmdbHandlers(uploadId, ctxKey, panelId, { pending: true });
}

function uploadRemapHandlers(uploadId, ctxKey, panelId, contentTitleId) {
  return createUploadTmdbHandlers(uploadId, ctxKey, panelId, {
    pending: false,
    afterPick: async (r) => {
      toast(r.message || (r.ok ? "TMDB updated" : r.error || "Failed"));
      if (r.ok && contentTitleId) {
        const container = document.getElementById(`title-remap-${contentTitleId}`);
        if (container) await mountTitleRemapPanel(contentTitleId, container);
        if (typeof openDetail === "function") openDetail(contentTitleId);
      }
    },
  });
}

async function toggleUploadRemapPanel(uploadId, contentTitleId) {
  const panelId = `upload-tmdb-${uploadId}`;
  const panel = document.getElementById(panelId);
  if (!panel) return;
  const opening = panel.classList.contains("hidden");
  if (!opening) {
    panel.classList.add("hidden");
    return;
  }
  panel.classList.remove("hidden");
  const ctxKey = tmdbCtxKey("upload", uploadId);
  if (!tmdbCache[ctxKey]) {
    panel.innerHTML = '<p class="sub">Loading TMDB…</p>';
    const r = await adminApi(`/api/admin/uploads/${uploadId}/tmdb`);
    tmdbCache[ctxKey] = mergeTmdbPage(null, r);
  }
  renderTmdbPanel(
    ctxKey,
    panelId,
    tmdbCache[ctxKey],
    uploadRemapHandlers(uploadId, ctxKey, panelId, contentTitleId)
  );
}

async function setUploadLane(uploadId, lane, contentTitleId) {
  try {
    const r = await adminApi(`/api/admin/uploads/${uploadId}/lane`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ lane }),
    });
    toast(r.message || (r.ok ? "Lane updated" : r.error || "Failed"));
    if (r.ok && contentTitleId) {
      const container = document.getElementById(`title-remap-${contentTitleId}`);
      if (container) await mountTitleRemapPanel(contentTitleId, container);
    }
  } catch (e) {
    toast(e.message || "Failed");
  }
}

async function setAllTitleLanes(contentTitleId, lane) {
  if (!lane) return;
  try {
    const r = await adminApi(`/api/admin/titles/${contentTitleId}/lane`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ lane }),
    });
    toast(r.message || (r.ok ? "Applied to all files" : r.error || "Failed"));
    if (r.ok) {
      const container = document.getElementById(`title-remap-${contentTitleId}`);
      if (container) await mountTitleRemapPanel(contentTitleId, container);
    }
  } catch (e) {
    toast(e.message || "Failed");
  }
}

async function queueUploadForTmdb(uploadId, contentTitleId) {
  try {
    const r = await adminApi(`/api/admin/uploads/${uploadId}/queue-tmdb-pending`, {
      method: "POST",
    });
    toast(r.message || (r.ok ? "Queued" : r.error || "Failed"));
    if (r.ok && contentTitleId) {
      const container = document.getElementById(`title-remap-${contentTitleId}`);
      if (container) await mountTitleRemapPanel(contentTitleId, container);
    }
  } catch (e) {
    toast(e.message || "Failed");
  }
}

function titleRemapActionButtons(row) {
  if (row.is_pending) {
    return '<span class="sub">In pending queue</span>';
  }
  if (row.lane_allows_tmdb) {
    return `<button type="button" class="btn secondary btn-sm" data-remap-tmdb="${row.upload_id}">🎬 Change TMDB</button>`;
  }
  return `<button type="button" class="btn secondary btn-sm" data-queue-tmdb="${row.upload_id}">⏳ Send to Pending (TMDB)</button>`;
}

function titleRemapCollapsedDefault() {
  return localStorage.getItem(TITLE_REMAP_COLLAPSED_KEY) !== "0";
}

function wireTitleRemapCollapse(container) {
  const trigger = container.querySelector(".admin-collapse-trigger");
  if (!trigger) return;
  trigger.onclick = () => {
    const collapsed = container.classList.toggle("is-collapsed");
    trigger.setAttribute("aria-expanded", collapsed ? "false" : "true");
    localStorage.setItem(TITLE_REMAP_COLLAPSED_KEY, collapsed ? "1" : "0");
  };
}

function buildTitleRemapShell(fileCount) {
  const collapsed = titleRemapCollapsedDefault();
  const meta =
    fileCount > 0
      ? `<span class="admin-collapse-meta sub">${fileCount} file(s)</span>`
      : "";
  return {
    collapsed,
    header: `
      <button type="button" class="admin-collapse-trigger" aria-expanded="${collapsed ? "false" : "true"}">
        <span class="admin-collapse-head">
          <span class="admin-collapse-title">Admin — TMDB &amp; content lane</span>
          ${meta}
        </span>
        <span class="admin-collapse-chevron" aria-hidden="true"></span>
      </button>
      <div class="admin-collapse-body">`,
  };
}

async function mountTitleRemapPanel(contentTitleId, container) {
  if (!container) return;
  container.innerHTML = '<p class="sub">Loading files…</p>';
  try {
    const data = await adminApi(`/api/admin/titles/${contentTitleId}/uploads`);
    if (!data.ok) {
      container.innerHTML = `<p class="sub">${escapeHtml(data.error || "Not found")}</p>`;
      return;
    }
    const lanes = data.lanes || [];
    const fileCount = data.uploads?.length || 0;
    const shell = buildTitleRemapShell(fileCount);
    container.classList.toggle("is-collapsed", shell.collapsed);
    const isCourse = (data.media_type || "").toLowerCase() === "course";
    let body = `<p class="sub">Change <b>content lane</b> per file. `;
    body += isCourse
      ? `For TMDB mapping, use <b>Send to Pending (TMDB)</b> or set lane to <b>Media library</b> then <b>Change TMDB</b>. `
      : `Use <b>Change TMDB</b> on Media/Adult lanes, or <b>Send to Pending (TMDB)</b> from Course/Archive/Shortform. `;
    body += `<b>Adult vault</b> hides files from public browse.</p>`;
    if (!fileCount) {
      body += '<p class="sub">No files linked to this title.</p>';
      container.innerHTML = shell.header + body;
      wireTitleRemapCollapse(container);
      return;
    }
    if (fileCount > 1) {
      const allLaneOpts = lanes
        .map((l) => `<option value="${escapeHtml(l.id)}">${escapeHtml(l.label)}</option>`)
        .join("");
      body += `<div class="title-lane-all-row">
        <label class="sub">Set <b>all ${fileCount} files</b> to lane
          <select id="title-lane-all-${contentTitleId}" class="input input-sm portal-select">${allLaneOpts}</select>
        </label>
        <button type="button" class="btn secondary btn-sm" id="title-lane-all-btn-${contentTitleId}">Apply to all</button>
      </div>`;
    }
    container.innerHTML = shell.header + body;
    if (fileCount > 1) {
      document
        .getElementById(`title-lane-all-btn-${contentTitleId}`)
        ?.addEventListener("click", () => {
          const sel = document.getElementById(`title-lane-all-${contentTitleId}`);
          setAllTitleLanes(contentTitleId, sel?.value || "");
        });
    }
    const list = document.createElement("div");
    list.className = "admin-remap-list";
    data.uploads.forEach((row) => {
      const wrap = document.createElement("div");
      wrap.className = "admin-pending-item admin-remap-item";
      const panelId = `upload-tmdb-${row.upload_id}`;
      const ep =
        row.season_number != null
          ? ` · S${row.season_number}${row.episode_number != null ? `E${row.episode_number}` : ""}`
          : "";
      const laneOpts = lanes
        .map(
          (l) =>
            `<option value="${escapeHtml(l.id)}"${l.id === row.content_lane ? " selected" : ""}>${escapeHtml(l.label)}</option>`
        )
        .join("");
      wrap.innerHTML = `
        <div class="admin-row">
          <div class="admin-row-main">
            <strong>${escapeHtml(row.file_name || "?")}</strong>
            <div class="sub">#${row.upload_id}${ep} · lane: <b>${escapeHtml(row.content_lane_label || row.content_lane)}</b>${row.is_pending ? " · <b>pending TMDB</b>" : ""}${row.library_visible ? "" : " · hidden"}</div>
          </div>
          <div class="admin-row-actions">
            <label class="sub">Lane
              <select class="input input-sm portal-select" data-lane-upload="${row.upload_id}" aria-label="Content lane">${laneOpts}</select>
            </label>
            ${titleRemapActionButtons(row)}
          </div>
        </div>
        <div id="${panelId}" class="tmdb-panel hidden"></div>`;
      list.appendChild(wrap);
      wrap.querySelector(`[data-remap-tmdb="${row.upload_id}"]`)?.addEventListener("click", () =>
        toggleUploadRemapPanel(row.upload_id, contentTitleId)
      );
      wrap.querySelector(`[data-queue-tmdb="${row.upload_id}"]`)?.addEventListener("click", () =>
        queueUploadForTmdb(row.upload_id, contentTitleId)
      );
      wrap.querySelector(`[data-lane-upload="${row.upload_id}"]`).onchange = (ev) => {
        setUploadLane(row.upload_id, ev.target.value, contentTitleId);
      };
    });
    container.querySelector(".admin-collapse-body")?.appendChild(list);
    wireTitleRemapCollapse(container);
  } catch (e) {
    container.innerHTML = `<p class="sub">Could not load — ${escapeHtml(e.message || "error")}</p>`;
  }
}

function batchTmdbHandlers(matchKey, ctxKey, panelId) {
  const enc = encodeURIComponent(matchKey);
  const handlers = {
    onRetry: async () => {
      const r = await adminApi(`/api/admin/pending/batches/${enc}/tmdb`);
      tmdbCache[ctxKey] = mergeTmdbPage(null, r);
      renderTmdbPanel(ctxKey, panelId, tmdbCache[ctxKey], handlers);
    },
    onPick: async (body) =>
      adminApi(`/api/admin/pending/batches/${enc}/tmdb-pick`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }),
    pendingPick: true,
    onSearch: async (q) => {
      const r = await adminApi(
        `/api/admin/pending/batches/${enc}/tmdb?${new URLSearchParams({ q, page: "1", filter_type: "all" })}`
      );
      tmdbCache[ctxKey] = mergeTmdbPage(null, r);
      renderTmdbPanel(ctxKey, panelId, tmdbCache[ctxKey], handlers);
    },
    onLoadMore: async () => {
      const cur = tmdbCache[ctxKey] || {};
      const page = (cur.page || 1) + 1;
      const params = tmdbListParams(cur, { page });
      const r = await adminApi(
        `/api/admin/pending/batches/${enc}/tmdb?${new URLSearchParams(params)}`
      );
      tmdbCache[ctxKey] = mergeTmdbPage(cur, r);
      renderTmdbPanel(ctxKey, panelId, tmdbCache[ctxKey], handlers);
    },
    onFilter: async (filterType) => {
      const cur = tmdbCache[ctxKey] || {};
      const params = tmdbListParams(cur, { page: 1, filter_type: filterType });
      const r = await adminApi(
        `/api/admin/pending/batches/${enc}/tmdb?${new URLSearchParams(params)}`
      );
      tmdbCache[ctxKey] = mergeTmdbPage(null, { ...r, filter_type: filterType });
      renderTmdbPanel(ctxKey, panelId, tmdbCache[ctxKey], handlers);
    },
  };
  return handlers;
}

async function toggleTmdbPanel(uploadId, contentLane) {
  if (contentLane && !laneAllowsTmdb(contentLane)) {
    toast("TMDB mapping is only for Media or Adult lane — set lane first.");
    return;
  }
  const panelId = `tmdb-panel-${uploadId}`;
  const panel = document.getElementById(panelId);
  if (!panel) return;
  const opening = panel.classList.contains("hidden");
  document.querySelectorAll(".tmdb-panel").forEach((p) => p.classList.add("hidden"));
  if (!opening) {
    panel.classList.add("hidden");
    return;
  }
  panel.classList.remove("hidden");
  const ctxKey = tmdbCtxKey("file", uploadId);
  if (!tmdbCache[ctxKey]) {
    panel.innerHTML = '<p class="sub">Loading TMDB…</p>';
    const r = await adminApi(`/api/admin/pending/${uploadId}/tmdb`);
    if (!r.ok && r.error) {
      panel.innerHTML = `<p class="sub">${escapeHtml(r.error)}</p>`;
      return;
    }
    tmdbCache[ctxKey] = mergeTmdbPage(null, r);
  }
  renderTmdbPanel(
    ctxKey,
    panelId,
    tmdbCache[ctxKey],
    pendingTmdbHandlers(uploadId, ctxKey, panelId)
  );
}

async function toggleBatchTmdbPanel(matchKey, contentLane, laneUniform) {
  if (!laneUniform || contentLane === "mixed" || !laneAllowsTmdb(contentLane)) {
    toast("Set the whole batch to Media or Adult lane before TMDB batch pick.");
    return;
  }
  const panelId = `batch-tmdb-${matchKey.replace(/[^a-z0-9]/gi, "_")}`;
  const panel = document.getElementById(panelId);
  if (!panel) return;
  const opening = panel.classList.contains("hidden");
  document.querySelectorAll(".tmdb-panel").forEach((p) => p.classList.add("hidden"));
  if (!opening) {
    panel.classList.add("hidden");
    return;
  }
  panel.classList.remove("hidden");
  const ctxKey = tmdbCtxKey("batch", matchKey);
  if (!tmdbCache[ctxKey]) {
    panel.innerHTML = '<p class="sub">Loading TMDB…</p>';
    const r = await adminApi(
      `/api/admin/pending/batches/${encodeURIComponent(matchKey)}/tmdb`
    );
    if (!r.ok && r.error) {
      panel.innerHTML = `<p class="sub">${escapeHtml(r.error)}</p>`;
      return;
    }
    tmdbCache[ctxKey] = mergeTmdbPage(null, r);
  }
  renderTmdbPanel(
    ctxKey,
    panelId,
    tmdbCache[ctxKey],
    batchTmdbHandlers(matchKey, ctxKey, panelId)
  );
}

async function retryAllPendingTmdb() {
  const btn = document.getElementById("adminRetryAllTmdb");
  if (btn) btn.disabled = true;
  try {
    const r = await adminApi("/api/admin/pending/retry-all-tmdb", { method: "POST" });
    toast(r.message || `Retried ${r.retried ?? 0} file(s)`);
    await loadAdminPending(adminPendingPage, adminBatchPage);
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function pendingBatchAction(matchKey, act) {
  const enc = encodeURIComponent(matchKey);
  const path =
    act === "defer"
      ? `/api/admin/pending/batches/${enc}/defer`
      : `/api/admin/pending/batches/${enc}/skip-catalog`;
  const r = await adminApi(path, { method: "POST" });
  toast(r.message || (r.ok ? "Done" : r.error || "Failed"));
  if (r.ok) await loadAdminPending(adminPendingPage, adminBatchPage);
}

async function loadAdminPending(page = 1, batchPage = 1) {
  adminPendingPage = page;
  adminBatchPage = batchPage;
  const data = await adminApi(
    `/api/admin/pending?page=${page}&batch_page=${batchPage}`
  );
  const summary = document.getElementById("adminPendingSummary");
  if (summary) {
    summary.textContent = `${data.pending_total ?? data.total} pending · ${data.batched_file_count ?? 0} in ${data.batch_total ?? 0} batch(es)`;
  }

  const batchList = document.getElementById("adminBatchList");
  const batchPag = document.getElementById("adminBatchPag");
  const list = document.getElementById("adminPendingList");
  const pag = document.getElementById("adminPendingPag");

  if (batchList) {
    batchList.innerHTML = "";
    if (!data.batches?.length) {
      batchList.innerHTML = '<p class="sub">No batches on this page.</p>';
    } else {
      data.batches.forEach((b) => {
        const panelId = `batch-tmdb-${(b.match_key || "").replace(/[^a-z0-9]/gi, "_")}`;
        const batchFiles = b.files || [];
        const preview =
          batchFiles.length > 0
            ? batchFiles
                .map(
                  (f) => `
            <div class="pending-file-play-row">
              <span class="pending-file-play-name">${escapeHtml(f.file_name || "?")}</span>
              <button type="button" class="btn ghost btn-sm pending-play-inline" data-play-id="${f.upload_id}" data-play-mode="browser" title="Play in browser">▶</button>
              <button type="button" class="btn ghost btn-sm pending-play-inline" data-tg-play-id="${f.upload_id}" title="Send to Telegram">📱</button>
            </div>`
                )
                .join("")
            : (b.preview_files || [])
                .map((f) => `<div class="pending-file-play-name">${escapeHtml(f)}</div>`)
                .join("");
        const deferTag = b.deferred ? " · deferred" : "";
        const lane = b.content_lane || "media";
        const canTmdb = b.lane_uniform !== false && laneAllowsTmdb(lane);
        const wrap = document.createElement("div");
        wrap.className = "admin-pending-item";
        wrap.innerHTML = `
          <div class="admin-row pending-row">
            <div class="admin-row-main">
              <strong>${escapeHtml(b.show_name || b.label || b.match_key)}</strong>
              <div class="sub">${b.file_count} files · ${escapeHtml(b.media_type || "")}${deferTag}</div>
              <div class="batch-preview">${preview}</div>
            </div>
            <div class="admin-row-actions pending-actions-stack">
              <div class="pending-action-btns">
                <button type="button" class="btn secondary btn-sm" data-batch-tmdb ${canTmdb ? "" : "disabled"} title="${canTmdb ? "TMDB pick for whole batch" : "Media or Adult lane only"}">🎬 TMDB batch</button>
                <button type="button" class="btn secondary btn-sm" data-batch-defer>⏭ Skip for now</button>
                <button type="button" class="btn ghost btn-sm" data-batch-skip-catalog>🚫 Skip catalog</button>
              </div>
            </div>
          </div>
          <div id="${panelId}" class="tmdb-panel hidden"></div>`;
        batchList.appendChild(wrap);
        wrap.querySelectorAll("[data-play-id]").forEach((btn) => {
          const uid = parseInt(btn.dataset.playId, 10);
          const f = batchFiles.find((x) => x.upload_id === uid);
          btn.onclick = () =>
            playPendingFile(uid, f?.can_stream !== false, f?.file_name, f?.browser_play !== false);
        });
        wrap.querySelectorAll("[data-tg-play-id]").forEach((btn) => {
          const uid = parseInt(btn.dataset.tgPlayId, 10);
          btn.onclick = () => window.sendToTelegram?.(uid);
        });
        mountPendingLaneSelect(
          wrap.querySelector(".pending-actions-stack"),
          lane,
          { batchKey: b.match_key, fileIds: b.file_ids || [] }
        );
        wrap.querySelector("[data-batch-tmdb]").onclick = () =>
          toggleBatchTmdbPanel(b.match_key, lane, b.lane_uniform !== false);
        wrap.querySelector("[data-batch-defer]").onclick = () =>
          pendingBatchAction(b.match_key, "defer");
        wrap.querySelector("[data-batch-skip-catalog]").onclick = () =>
          pendingBatchAction(b.match_key, "skip-catalog");
      });
    }
  }

  if (batchPag) {
    batchPag.innerHTML = "";
    if (batchPag) {
      renderAdminPagination(batchPag, data.batch_page, data.batch_page_count, (p) =>
        loadAdminPending(adminPendingPage, p)
      );
    }
  }

  if (!list) return;
  list.innerHTML = "";
  const items = data.items || [];
  if (!items.length) {
    list.innerHTML = '<p class="sub">No pending files on this page.</p>';
  }
  items.forEach((row) => {
    const lane = row.content_lane || "media";
    const canTmdb = laneAllowsTmdb(lane);
    const wrap = document.createElement("div");
    wrap.className = "admin-pending-item";
    wrap.innerHTML = `
      <div class="admin-row pending-row">
        <div class="admin-row-main">
          <strong>#${row.id}</strong> ${escapeHtml(row.parsed_name)}
          <div class="sub pending-file-name">${escapeHtml(row.file_name)}</div>
          <div class="sub">${escapeHtml(row.channel_title || "")}</div>
        </div>
        <div class="admin-row-actions pending-actions-stack">
          <div class="pending-action-btns">
            ${
              canTmdb
                ? `<button type="button" class="btn primary btn-sm" data-tmdb="${row.id}" title="Map to TMDB — required to leave pending">🎬 TMDB map</button>`
                : `<button type="button" class="btn primary btn-sm" data-act="confirm" data-id="${row.id}" title="Confirm without TMDB (course / archive / shortform)">Confirm</button>`
            }
            <button type="button" class="btn secondary btn-sm" data-act="defer" data-id="${row.id}">⏭ Skip</button>
            <button type="button" class="btn ghost btn-sm" data-act="skip-catalog" data-id="${row.id}">🚫 Skip catalog</button>
            <button type="button" class="btn ghost btn-sm" data-act="skip" data-id="${row.id}">Remove</button>
          </div>
        </div>
      </div>
      <div id="tmdb-panel-${row.id}" class="tmdb-panel hidden"></div>`;
    list.appendChild(wrap);
    mountPendingPlayButtons(
      wrap.querySelector(".pending-actions-stack"),
      row.id,
      row.can_stream !== false,
      row.file_name,
      row.browser_play !== false,
      { canConvert: row.can_convert_mp4, mp4Cached: row.mp4_cached }
    );
    mountPendingLaneSelect(wrap.querySelector(".pending-actions-stack"), lane, {
      uploadId: row.id,
    });
    wrap.querySelector(`button[data-tmdb="${row.id}"]`)?.addEventListener("click", () =>
      toggleTmdbPanel(row.id, lane)
    );
  });
  list.querySelectorAll("button[data-act]").forEach((btn) => {
    btn.onclick = async () => {
      const id = btn.dataset.id;
      const act = btn.dataset.act;
      const path =
        act === "confirm"
          ? `/api/admin/pending/${id}/confirm`
          : act === "defer"
            ? `/api/admin/pending/${id}/defer`
            : act === "skip-catalog"
              ? `/api/admin/pending/${id}/skip-catalog`
              : `/api/admin/pending/${id}/skip`;
      const r = await adminApi(path, { method: "POST" });
      toast(r.message || (r.ok ? "Done" : r.error || "Failed"));
      if (r.ok) loadAdminPending(adminPendingPage, adminBatchPage);
    };
  });
  if (pag) {
    renderAdminPagination(pag, data.page, data.page_count, (p) =>
      loadAdminPending(p, adminBatchPage)
    );
  }

  const retryAll = document.getElementById("adminRetryAllTmdb");
  if (retryAll && !retryAll._bound) {
    retryAll._bound = true;
    retryAll.onclick = retryAllPendingTmdb;
  }
}

function adminInfoCard({ poster, title, badge, lines, actionsHtml }) {
  const card = document.createElement("article");
  card.className = "admin-info-card";
  const img = poster
    ? `<img class="admin-info-poster" src="${escapeHtml(poster)}" alt="" loading="lazy" />`
    : `<div class="admin-info-poster placeholder">No poster</div>`;
  card.innerHTML = `
    ${img}
    <div class="admin-info-body">
      <div class="admin-info-head">
        <h3 class="admin-info-title">${escapeHtml(title || "?")}</h3>
        ${badge ? `<span class="admin-info-badge">${escapeHtml(badge)}</span>` : ""}
      </div>
      ${(lines || []).map((l) => `<p class="sub admin-info-line">${l}</p>`).join("")}
      ${actionsHtml ? `<div class="admin-info-actions">${actionsHtml}</div>` : ""}
    </div>`;
  return card;
}

async function loadAdminRequests(page = 1) {
  requestsPage = page;
  const list = document.getElementById("adminRequestsList");
  const meta = document.getElementById("requestsListMeta");
  const pag = document.getElementById("requestsPag");
  if (!list) return;
  showAdminListSkeleton(list, POSTER_GRID_PAGE_SIZE, "grid");
  if (meta) meta.textContent = "";
  try {
    const data = await adminApi(
      `/api/admin/requests?page=${page}&limit=${POSTER_GRID_PAGE_SIZE}`
    );
    list.classList.remove("is-loading");
    list.innerHTML = "";
    if (meta) {
      meta.textContent = `${data.total ?? 0} request(s) · page ${data.page} of ${data.pages}`;
    }
    if (!data.items?.length) {
      list.innerHTML = '<p class="sub" style="grid-column:1/-1">No pending user requests.</p>';
      renderAdminPagination(pag, page, data.pages || 1, loadAdminRequests);
      return;
    }
    data.items.forEach((r) => {
      const created = r.created_at ? new Date(r.created_at).toLocaleString() : "";
      const subText = `${r.media_type || "movie"}${r.release_year ? ` · ${r.release_year}` : ""} · User ${r.user_id}`;
      const card = libraryPosterCard({
        title: r.title,
        posterUrl: r.poster_url,
        subText: created ? `${subText} · ${created}` : subText,
        badgeText: "Request",
        badgeClass: "gap",
        actionsHtml: `
          <button type="button" class="btn primary btn-sm" data-req="done" data-id="${r.id}">Done</button>
          <button type="button" class="btn ghost btn-sm" data-req="rejected" data-id="${r.id}">Reject</button>`,
      });
      list.appendChild(card);
    });
    list.querySelectorAll("button[data-req]").forEach((btn) => {
    btn.onclick = async () => {
      const res = await adminApi(`/api/admin/requests/${btn.dataset.id}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status: btn.dataset.req }),
      });
      toast(res.message || "Updated");
      loadAdminRequests(requestsPage);
    };
    });
    renderAdminPagination(pag, page, data.pages || 1, loadAdminRequests);
  } catch (e) {
    list.classList.remove("is-loading");
    list.innerHTML = `<p class="sub">Could not load requests — ${escapeHtml(e.message || "error")}</p>`;
  }
}

function trackingProgressLabel(item) {
  if (item.kind === "tv") {
    const idx = item.indexed_episodes ?? 0;
    const tmdb = item.tmdb_episodes != null ? ` / ${item.tmdb_episodes}` : "";
    return `${idx} episode(s) indexed · ${item.indexed_seasons ?? 0} season(s)${tmdb}`;
  }
  if (item.kind === "multipart") {
    return `${item.indexed_parts ?? 0} / ${item.total_parts ?? "?"} parts`;
  }
  if (item.kind === "collection") {
    let s = `${item.indexed_parts ?? 0} / ${item.total_parts ?? "?"} released`;
    if (item.upcoming_count) s += ` · ${item.upcoming_count} upcoming`;
    return s;
  }
  return "";
}

function trackingCompletionBadge(item) {
  const st = item.completion_status || (item.is_complete ? "complete" : "incomplete");
  if (st === "complete") {
    return '<span class="badge">Complete</span>';
  }
  if (st === "unknown") {
    if (item.kind === "tv" && item.tmdb_id && item.tmdb_episodes == null) {
      return '<span class="badge missing" title="Could not load episode total from TMDB">TMDB unavailable</span>';
    }
    if (item.kind === "multipart" && !item.total_parts) {
      return '<span class="badge missing" title="Part count not set">Parts unknown</span>';
    }
    return '<span class="badge missing">Unknown</span>';
  }
  return '<span class="badge missing">Incomplete</span>';
}

function trackingCardLines(item) {
  const lines = [];
  if (item.kind === "tv") {
    lines.push(
      `<b>Indexed</b> ${item.indexed_episodes ?? 0} episode(s) · ${item.indexed_seasons ?? 0} season(s) · ${item.file_count ?? 0} file(s)`
    );
    if (item.tmdb_episodes != null) {
      lines.push(`<b>TMDB total</b> ${item.tmdb_episodes} episode(s)`);
    }
    if (item.seasons_indexed?.length) {
      const parts = item.seasons_indexed.map(
        (s) => `S${s.season}: ${s.episodes} ep`
      );
      lines.push(`<b>By season</b> ${parts.join(" · ")}`);
    }
    if (item.tmdb_url) {
      lines.push(`<a href="${escapeHtml(item.tmdb_url)}" target="_blank" rel="noopener">TMDB ↗</a>`);
    }
    return lines;
  }
  if (item.kind === "multipart") {
    lines.push(
      `<b>Parts</b> ${item.indexed_parts ?? 0} / ${item.total_parts ?? "?"} indexed`
    );
    if (item.parts_label) lines.push(`<b>Set</b> ${escapeHtml(item.parts_label)}`);
    return lines;
  }
  if (item.kind === "collection") {
    lines.push(
      `<b>Released</b> ${item.indexed_parts ?? 0} / ${item.total_parts ?? "?"} in library`
    );
    if (item.upcoming_count) lines.push(`<b>Upcoming</b> ${item.upcoming_count}`);
    return lines;
  }
  return [escapeHtml(trackingProgressLabel(item))];
}

function metadataGapLabel(issue) {
  if (issue === "no_tmdb") return "No TMDB id";
  if (issue === "no_poster") return "No poster";
  if (issue === "no_both") return "No TMDB + poster";
  return "Gap";
}

async function toggleMetadataGapTmdb(contentTitleId, btn) {
  const panelId = `gap-tmdb-${contentTitleId}`;
  const panel = document.getElementById(panelId);
  if (!panel) return;
  const opening = panel.classList.contains("hidden");
  document.querySelectorAll(".metadata-gap-panel:not(.hidden)").forEach((p) => {
    if (p.id !== panelId) p.classList.add("hidden");
  });
  document.querySelectorAll(".metadata-gap-row.is-expanded").forEach((r) => {
    if (r.dataset.ctId !== String(contentTitleId)) r.classList.remove("is-expanded");
  });
  if (!opening) {
    panel.classList.add("hidden");
    btn?.closest(".metadata-gap-row")?.classList.remove("is-expanded");
    return;
  }
  panel.classList.remove("hidden");
  btn?.closest(".metadata-gap-row")?.classList.add("is-expanded");
  const ctxKey = tmdbCtxKey("gap", contentTitleId);
  if (tmdbCache[ctxKey]?.upload_id) {
    renderTmdbPanel(
      ctxKey,
      panelId,
      tmdbCache[ctxKey],
      tmdbCache[ctxKey]._handlers
    );
    return;
  }
  panel.innerHTML = '<p class="sub">Loading…</p>';
  let uploadId = panel.dataset.uploadId ? parseInt(panel.dataset.uploadId, 10) : 0;
  if (!uploadId) {
    try {
      const files = await adminApi(`/api/admin/titles/${contentTitleId}/uploads`);
      if (!files.ok || !files.uploads?.length) {
        panel.innerHTML =
          '<p class="sub">No indexed files for this title — fix via Pending or link a file first.</p>';
        return;
      }
      uploadId = files.uploads[0].upload_id;
      panel.dataset.uploadId = String(uploadId);
      if (files.uploads.length > 1) {
        panel.dataset.multiUploads = "1";
      }
    } catch (e) {
      panel.innerHTML = `<p class="sub">${escapeHtml(e.message || "Could not load files")}</p>`;
      return;
    }
  }
  try {
    const r = await adminApi(`/api/admin/uploads/${uploadId}/tmdb`);
    const handlers = createUploadTmdbHandlers(uploadId, ctxKey, panelId, {
      pending: false,
      afterPick: async (pickRes) => {
        toast(pickRes.message || (pickRes.ok ? "TMDB updated" : pickRes.error || "Failed"));
        if (pickRes.ok) {
          delete tmdbCache[ctxKey];
          await loadMetadataGaps(metadataGapsPage);
        }
      },
    });
    const merged = mergeTmdbPage(null, r);
    merged.upload_id = uploadId;
    merged._handlers = handlers;
    tmdbCache[ctxKey] = merged;
    if (panel.dataset.multiUploads === "1") {
      merged._multiNote = true;
    }
    renderTmdbPanel(ctxKey, panelId, merged, handlers);
    if (merged._multiNote) {
      const note = document.createElement("p");
      note.className = "sub metadata-gap-multi-note";
      note.textContent =
        "TMDB pick applies to the first file on this title. Use Open for per-file lane/remap if needed.";
      panel.insertBefore(note, panel.firstChild?.nextSibling || panel.firstChild);
    }
  } catch (e) {
    panel.innerHTML = `<p class="sub">${escapeHtml(e.message || "TMDB load failed")}</p>`;
  }
}

function metadataGapFilesHtml(item) {
  const names = item.file_names || [];
  if (!names.length) {
    return '<p class="sub metadata-gap-files">No linked filenames</p>';
  }
  const extra = item.file_names_extra ?? 0;
  const lines = names
    .map((n) => `<li class="metadata-gap-file-item">${escapeHtml(n)}</li>`)
    .join("");
  const more =
    extra > 0
      ? `<li class="metadata-gap-file-item metadata-gap-file-more">+ ${extra} more file(s)</li>`
      : "";
  return `<ul class="metadata-gap-files" title="Indexed filenames">${lines}${more}</ul>`;
}

function metadataGapRow(item) {
  const wrap = document.createElement("div");
  wrap.className = "metadata-gap-row";
  wrap.dataset.ctId = String(item.content_title_id);
  const panelId = `gap-tmdb-${item.content_title_id}`;
  const issueLabel = (item.issues || []).map((i) => metadataGapLabel(i)).join(" · ") || "Gap";
  const thumb = item.poster_url
    ? `<img class="metadata-gap-thumb" src="${escapeHtml(item.poster_url)}" alt="" loading="lazy" />`
    : `<div class="metadata-gap-thumb placeholder" aria-hidden="true">—</div>`;
  const tmdbLink = item.tmdb_url
    ? ` · <a href="${escapeHtml(item.tmdb_url)}" target="_blank" rel="noopener">TMDB</a>`
    : "";
  wrap.innerHTML = `
    <div class="metadata-gap-main">
      ${thumb}
      <div class="metadata-gap-body">
        <h3 class="metadata-gap-title">${escapeHtml(item.title || "?")}</h3>
        <p class="sub metadata-gap-meta">${escapeHtml(item.media_type || "movie")}${item.release_year ? ` · ${item.release_year}` : ""} · ${item.upload_count ?? 0} file(s) · <span class="badge gap">${escapeHtml(issueLabel)}</span>${tmdbLink}</p>
        ${metadataGapFilesHtml(item)}
      </div>
      <div class="metadata-gap-actions">
        <button type="button" class="btn primary btn-sm" data-gap-fix="${item.content_title_id}">Fix TMDB</button>
        <button type="button" class="btn ghost btn-sm" data-gap-open="${item.content_title_id}">Open</button>
      </div>
    </div>
    <div id="${panelId}" class="metadata-gap-panel tmdb-panel-compact hidden"></div>`;
  wrap.querySelector("[data-gap-fix]")?.addEventListener("click", (e) => {
    e.stopPropagation();
    toggleMetadataGapTmdb(item.content_title_id, e.currentTarget);
  });
  wrap.querySelector("[data-gap-open]")?.addEventListener("click", (e) => {
    e.stopPropagation();
    if (typeof openDetail === "function") openDetail(parseInt(item.content_title_id, 10));
  });
  return wrap;
}

async function loadMetadataGaps(page = 1) {
  metadataGapsPage = page;
  const list = document.getElementById("metadataGapsList");
  const meta = document.getElementById("metadataGapsMeta");
  const summaryEl = document.getElementById("metadataGapsSummary");
  const pag = document.getElementById("metadataGapsPag");
  if (!list) return;
  list.classList.add("is-loading");
  list.innerHTML = "";
  for (let i = 0; i < 8; i++) {
    const sk = document.createElement("div");
    sk.className = "metadata-gap-row skeleton-gap-row";
    list.appendChild(sk);
  }
  if (meta) meta.textContent = "";
  try {
    const data = await adminApi(
      `/api/admin/metadata-gaps?issue=${encodeURIComponent(metadataGapsFilter)}&page=${page}&limit=${METADATA_GAPS_PAGE_SIZE}`
    );
    const s = data.summary || {};
    if (summaryEl) {
      summaryEl.innerHTML = `
        <div class="stat-card stat-warn"><span class="stat-n">${s.missing_any ?? 0}</span><span class="stat-l">Any gap</span></div>
        <div class="stat-card"><span class="stat-n">${s.no_tmdb ?? 0}</span><span class="stat-l">No TMDB id</span></div>
        <div class="stat-card"><span class="stat-n">${s.no_poster ?? 0}</span><span class="stat-l">No poster</span></div>
        <div class="stat-card"><span class="stat-n">${s.no_both ?? 0}</span><span class="stat-l">Both missing</span></div>`;
    }
    if (meta) {
      let hint = `Page ${data.page} of ${data.pages} · ${data.total ?? 0} total`;
      if (!data.tmdb_enabled) hint += " · TMDB API not configured";
      meta.textContent = hint;
    }
    list.classList.remove("is-loading");
    list.innerHTML = "";
    if (!data.items?.length) {
      list.innerHTML = '<p class="sub">No titles match this filter.</p>';
      pag?.classList.add("hidden");
      return;
    }
    data.items.forEach((item) => list.appendChild(metadataGapRow(item)));
    if (pag && data.pages > 1) {
      renderAdminPagination(pag, data.page, data.pages, loadMetadataGaps);
    } else {
      pag?.classList.add("hidden");
    }
  } catch (e) {
    list.classList.remove("is-loading");
    list.innerHTML = `<p class="sub">Could not load metadata gaps — ${escapeHtml(e.message || "error")}</p>`;
  }
}

async function loadFilenameRules() {
  const list = document.getElementById("filenameRulesList");
  const meta = document.getElementById("filenameRulesMeta");
  if (!list) return;
  list.innerHTML = "";
  try {
    const data = await adminApi("/api/admin/filename-rules");
    const rules = data.rules || [];
    if (meta) meta.textContent = `${rules.length} rule(s)`;
    if (!rules.length) {
      list.innerHTML = '<p class="sub">No rules yet — add a prefix above.</p>';
      return;
    }
    rules.forEach((rule) => {
      const row = document.createElement("div");
      row.className = "info-card filename-rule-row";
      const note = rule.note ? ` · ${escapeHtml(rule.note)}` : "";
      const regexTag = rule.is_regex ? " · regex" : "";
      row.innerHTML = `
        <div class="filename-rule-text">
          <code>${escapeHtml(rule.pattern)}</code>${note}${regexTag}
        </div>
        <button type="button" class="btn ghost btn-sm" data-del-rule="${rule.id}">Delete</button>`;
      list.appendChild(row);
    });
    list.querySelectorAll("[data-del-rule]").forEach((btn) => {
      btn.onclick = async () => {
        const id = btn.dataset.delRule;
        if (!id || !confirm("Delete this prefix rule?")) return;
        await adminApi(`/api/admin/filename-rules/${id}`, { method: "DELETE" });
        toast("Rule deleted");
        await loadFilenameRules();
      };
    });
  } catch (e) {
    list.innerHTML = `<p class="sub">${escapeHtml(String(e.message || e))}</p>`;
  }
}

function bindFilenameRuleForms() {
  const form = document.getElementById("filenameRuleForm");
  const previewForm = document.getElementById("filenameRulePreviewForm");
  if (form && !form._bound) {
    form._bound = true;
    form.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const pattern = document.getElementById("filenameRulePattern")?.value?.replace(/\r?\n/g, "") ?? "";
      if (!pattern.trim()) {
        toast("Enter a prefix");
        return;
      }
      const note = document.getElementById("filenameRuleNote")?.value?.trim() || null;
      const is_regex = !!document.getElementById("filenameRuleRegex")?.checked;
      const r = await adminApi("/api/admin/filename-rules", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pattern, note, is_regex }),
      });
      if (!r.ok) {
        toast(r.error || "Could not save");
        return;
      }
      form.reset();
      toast("Prefix saved");
      await loadFilenameRules();
    });
  }
  if (previewForm && !previewForm._bound) {
    previewForm._bound = true;
    previewForm.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const filename = document.getElementById("filenameRuleSample")?.value?.trim();
      const out = document.getElementById("filenameRulePreviewOut");
      if (!filename || !out) return;
      const r = await adminApi("/api/admin/filename-rules/preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ filename }),
      });
      out.classList.remove("hidden");
      out.innerHTML = `
        After strip: <code>${escapeHtml(r.stripped || "")}</code><br/>
        Parsed title: <b>${escapeHtml(r.parsed_title || "?")}</b>
        ${r.year ? ` (${r.year})` : ""}`;
    });
  }
}

async function loadAdminTracking(page = 1) {
  trackingPage = page;
  const list = document.getElementById("adminTrackingList");
  const meta = document.getElementById("trackingListMeta");
  const pag = document.getElementById("trackingPag");
  if (!list) return;
  showAdminListSkeleton(list);
  if (meta) {
    meta.textContent =
      trackingCompletion !== "all" || trackingFilter !== "all"
        ? "Loading filtered list…"
        : "";
  }
  try {
    const data = await adminApi(
      `/api/admin/tracking?filter=${encodeURIComponent(trackingFilter)}&completion=${encodeURIComponent(trackingCompletion)}&page=${page}&page_size=${ADMIN_LIST_PAGE_SIZE}`
    );
    list.classList.remove("is-loading");
    list.innerHTML = "";
    if (meta) {
      meta.textContent = `${data.total ?? 0} total · page ${data.page} of ${data.pages} · incomplete first, newest first`;
    }
    if (!data.items?.length) {
      list.innerHTML = '<p class="sub">Nothing in tracking for this filter.</p>';
      return;
    }
    data.items.forEach((item) => {
      const kindBadge =
        item.kind === "tv"
          ? "TV series"
          : item.kind === "collection"
            ? "Collection"
            : "Multipart";
      const lines = trackingCardLines(item);
      lines.push(trackingCompletionBadge(item));
      const card = adminInfoCard({
        poster: item.poster_url,
        title: item.title,
        badge: kindBadge,
        lines,
        actionsHtml: item.content_title_id
          ? `<button type="button" class="btn secondary btn-sm" data-open-ct="${item.content_title_id}">Open title</button>`
          : "",
      });
      const openBtn = card.querySelector("[data-open-ct]");
      if (openBtn) {
        openBtn.onclick = () => {
          if (typeof openDetail === "function") openDetail(parseInt(openBtn.dataset.openCt, 10));
        };
      }
      list.appendChild(card);
    });
    renderAdminPagination(pag, page, data.pages || 1, loadAdminTracking);
  } catch (e) {
    list.classList.remove("is-loading");
    list.innerHTML = `<p class="sub">Could not load tracking — ${escapeHtml(e.message || "error")}</p>`;
  }
}

function watchCatalogCard(item) {
  const seasonLabel = item.season_number != null ? ` · S${item.season_number}` : "";
  const published = !!item.is_published;
  const vote = item.vote_average ? ` ★${parseFloat(item.vote_average).toFixed(1)}` : "";
  const subText =
    (item.media_type || "") + (item.release_year ? ` · ${item.release_year}` : "") + vote;

  let overlayButton = null;
  if (published) {
    overlayButton = document.createElement("button");
    overlayButton.type = "button";
    overlayButton.className = "card-unpublish";
    overlayButton.textContent = "Unpublish";
    overlayButton.onclick = async (e) => {
      e.stopPropagation();
      if (!confirm(`Unpublish "${item.title}"${seasonLabel}?`)) return;
      overlayButton.disabled = true;
      try {
        const r = await adminApi("/api/admin/catalog/unpublish", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            content_title_id: item.content_title_id,
            season_number: item.season_number,
          }),
        });
        toast(r.message || (r.ok ? "Unpublished" : "Failed"));
        if (r.ok) loadWatchLibrary(watchLibPage);
      } finally {
        overlayButton.disabled = false;
      }
    };
  }

  return libraryPosterCard({
    title: (item.title || "?") + seasonLabel,
    posterUrl: item.poster_url,
    subText,
    badgeText: published ? "Published" : "Unpublished",
    badgeClass: published ? "published" : "unpublished",
    overlayButton,
    onClick: () => {
      if (item.content_title_id && typeof openDetail === "function") {
        openDetail(item.content_title_id);
      }
    },
  });
}

async function loadWatchLibrary(page = 1) {
  watchLibPage = page;
  const grid = document.getElementById("watchLibGrid");
  if (grid) showAdminListSkeleton(grid, POSTER_GRID_PAGE_SIZE, "grid");
  const params = new URLSearchParams({
    page: String(page),
    limit: "28",
    status: watchLibFilter,
    sort: watchLibSort,
    order: watchLibOrder,
  });
  if (watchLibQuery) params.set("q", watchLibQuery);
  let data;
  try {
    data = await adminApi(`/api/admin/catalog?${params}`);
  } catch (e) {
    if (grid) {
      grid.classList.remove("is-loading");
      grid.innerHTML = `<p class="sub">Could not load — ${escapeHtml(e.message || "error")}</p>`;
    }
    return;
  }
  const meta = document.getElementById("watchLibMeta");
  if (meta) {
    const filterLabel =
      watchLibFilter === "published"
        ? "Published"
        : watchLibFilter === "unpublished"
          ? "Unpublished"
          : "All";
    const qHint = watchLibQuery ? ` · filter “${watchLibQuery}”` : "";
    const slowHint = data.fast_path === false ? " · slower scan (unpublished slots)" : "";
    meta.textContent = `${filterLabel}: ${data.total} slot(s) · ${data.published_count ?? 0} published · ${data.unpublished_count ?? 0} unpublished · page ${data.page} of ${data.page_count}${qHint}${slowHint}`;
  }
  const unpubEl = document.getElementById("adminCatalogUnpub");
  if (unpubEl) {
    unpubEl.textContent =
      (data.unpublished_count ?? 0) > 0
        ? `${data.unpublished_count} unpublished — use Publish next 10 or Publish all.`
        : "All catalog slots are published.";
  }
  if (grid) {
    grid.classList.remove("is-loading");
    grid.innerHTML = "";
    if (!data.items?.length) {
      grid.innerHTML = '<p class="sub">No catalog slots match this filter.</p>';
    } else {
      data.items.forEach((item) => grid.appendChild(watchCatalogCard(item)));
    }
  }
  const pag = document.getElementById("watchLibPag");
  if (pag) renderAdminPagination(pag, data.page, data.page_count, loadWatchLibrary);
  bindWatchPublishButtons();
}

function updateAdminSearchPlaceholder() {
  const input = document.getElementById("searchInput");
  if (!input) return;
  const placeholders = {
    media: "Search media library…",
    courses: "Search courses…",
    archive: "Search archive…",
    shortform: "Search shortform…",
    adult: "Search adult vault…",
    noncatalog: "Search skip-catalog titles…",
    watch: "Filter watch catalog…",
    pending: "Search pending (coming soon)…",
    metadata: "Open a title to fix TMDB…",
    tracking: "Use tracking filters below…",
  };
  input.placeholder = placeholders[adminSection] || "Search titles…";
}

function handleAdminSearch(q) {
  const trimmed = (q || "").trim();
  if (adminSection === "watch") {
    watchLibQuery = trimmed.length >= 2 ? trimmed : "";
    watchLibPage = 1;
    loadWatchLibrary(1);
    return true;
  }
  if (
    adminSection === "media" ||
    adminSection === "courses" ||
    adminSection === "archive" ||
    adminSection === "shortform" ||
    adminSection === "adult" ||
    adminSection === "noncatalog"
  ) {
    adminBrowseQuery = trimmed.length >= 2 ? trimmed : "";
    if (typeof window.setBrowsePage === "function") window.setBrowsePage(1);
    if (typeof loadPortalBrowse === "function") loadPortalBrowse();
    return true;
  }
  return false;
}

function setWatchPublishBusy(busy) {
  document.getElementById("adminPublishBtn")?.toggleAttribute("disabled", busy);
  document.getElementById("adminPublishAllBtn")?.toggleAttribute("disabled", busy);
}

function setWatchPublishStatus(text, running = false) {
  const el = document.getElementById("watchLibPublishStatus");
  if (!el) return;
  if (!text) {
    el.classList.add("hidden");
    el.classList.remove("running");
    el.textContent = "";
    return;
  }
  el.textContent = text;
  el.classList.remove("hidden");
  el.classList.toggle("running", running);
}

function stopPublishAllPoll() {
  if (publishAllPollTimer) {
    clearInterval(publishAllPollTimer);
    publishAllPollTimer = null;
  }
}

async function pollPublishAllStatus() {
  try {
    const st = await adminApi("/api/admin/catalog/publish-all/status");
    if (st.status === "running") {
      let line = "Publishing catalog cards…";
      if (st.total != null && st.processed != null) {
        line += ` ${st.processed} / ${st.total}`;
      }
      if (st.remaining != null) {
        line += ` · ${st.remaining} left`;
      }
      setWatchPublishStatus(line, true);
      return;
    }
    stopPublishAllPoll();
    setWatchPublishBusy(false);
    setWatchPublishStatus("");
    if (st.status === "done" || st.status === "error") {
      toast(st.message || (st.status === "done" ? "Publish all finished" : "Publish failed"));
    }
    loadWatchLibrary(watchLibPage);
  } catch (e) {
    stopPublishAllPoll();
    setWatchPublishBusy(false);
    setWatchPublishStatus("");
    toast(e.message || "Could not check publish status");
  }
}

async function startPublishAll() {
  if (
    !confirm(
      "Publish all unpublished catalog cards to the watch channel? This may take several minutes."
    )
  ) {
    return;
  }
  setWatchPublishBusy(true);
  setWatchPublishStatus("Starting publish all…", true);
  try {
    const r = await adminApi("/api/admin/catalog/publish-all", { method: "POST" });
    if (!r.ok && r.status !== "running") {
      toast(r.message || "Could not start publish");
      setWatchPublishBusy(false);
      setWatchPublishStatus("");
      return;
    }
    toast(r.message || "Publishing in background…");
    stopPublishAllPoll();
    publishAllPollTimer = setInterval(pollPublishAllStatus, 3000);
    pollPublishAllStatus();
  } catch (e) {
    setWatchPublishBusy(false);
    setWatchPublishStatus("");
    toast(e.message || "Publish all failed");
  }
}

function bindWatchPublishButtons() {
  const pubBtn = document.getElementById("adminPublishBtn");
  const pubAllBtn = document.getElementById("adminPublishAllBtn");
  if (pubBtn && !pubBtn._bound) {
    pubBtn._bound = true;
    pubBtn.onclick = async () => {
      setWatchPublishBusy(true);
      try {
        const r = await adminApi("/api/admin/catalog/publish?limit=10", {
          method: "POST",
        });
        toast(r.message || "Publish finished");
        loadWatchLibrary(watchLibPage);
      } finally {
        setWatchPublishBusy(false);
      }
    };
  }
  if (pubAllBtn && !pubAllBtn._bound) {
    pubAllBtn._bound = true;
    pubAllBtn.onclick = startPublishAll;
  }
  adminApi("/api/admin/catalog/publish-all/status")
    .then((st) => {
      if (st.status === "running") {
        setWatchPublishBusy(true);
        stopPublishAllPoll();
        publishAllPollTimer = setInterval(pollPublishAllStatus, 3000);
        pollPublishAllStatus();
      }
    })
    .catch(() => {});
}

window.hideAllAdminSections = hideAllAdminSections;
window.loadAdminSection = loadAdminSection;
window.mountTitleRemapPanel = mountTitleRemapPanel;
window.toggleUploadRemapPanel = toggleUploadRemapPanel;
window.handleAdminSearch = handleAdminSearch;
window.getAdminBrowseQuery = () => adminBrowseQuery;
