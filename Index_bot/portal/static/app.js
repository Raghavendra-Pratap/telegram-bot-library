const TOKEN_KEY = "portal_token";
/** Items per page — keep divisible by 2, 4, and 7 for full grid rows on all breakpoints */
const BROWSE_PAGE = 28;
let filter = "all";
let browseScope = "media";
let portalIsAdmin = false;
let activeToolPanel = null;
let browsePage = 1;

const FILTER_LABELS = {
  all: "All",
  movie: "Movies",
  tv: "Series",
  course: "Courses",
};

const SORT_LABELS = {
  recent: "Recent",
  rating: "Rating",
  year: "Year",
  title: "Title",
};
let browsePageCount = 1;
let browseTotal = 0;
let streamProgressTimer = null;
let currentTitleId = null;
window.portalFfmpegTranscode = false;

function token() {
  return localStorage.getItem(TOKEN_KEY) || "";
}

function setToken(t) {
  if (t) localStorage.setItem(TOKEN_KEY, t);
  else localStorage.removeItem(TOKEN_KEY);
}

async function api(path, opts = {}) {
  const headers = { ...(opts.headers || {}) };
  if (token()) headers.Authorization = `Bearer ${token()}`;
  const res = await fetch(path, { ...opts, headers });
  if (res.status === 401) {
    setToken("");
    showLogin();
    throw new Error("Login required");
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || data.error || res.statusText);
  return data;
}

function toast(msg) {
  const el = document.getElementById("toast");
  el.textContent = msg;
  el.classList.remove("hidden");
  setTimeout(() => el.classList.add("hidden"), 3500);
}

function showLogin() {
  document.getElementById("login").classList.remove("hidden");
  document.getElementById("app").classList.add("hidden");
}

async function loadPortalHealth() {
  try {
    const h = await api("/api/health");
    window.portalFfmpegTranscode = !!h.ffmpeg_transcode;
  } catch {
    window.portalFfmpegTranscode = false;
  }
}

function showApp() {
  document.getElementById("login").classList.add("hidden");
  document.getElementById("app").classList.remove("hidden");
  loadPortalHealth();
}

function posterCard(item, onClick) {
  const div = document.createElement("div");
  div.className = "card";
  const img = document.createElement("img");
  img.src = item.poster_url || "/static/placeholder.svg";
  img.alt = item.title || "";
  img.onerror = () => {
    img.src =
      "data:image/svg+xml," +
      encodeURIComponent(
        '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="300"><rect fill="#21262d" width="100%" height="100%"/><text x="50%" y="50%" fill="#8b949e" text-anchor="middle" font-size="14">No poster</text></svg>'
      );
  };
  const meta = document.createElement("div");
  meta.className = "meta";
  const t = document.createElement("div");
  t.className = "title";
  t.textContent = item.title || "?";
  const sub = document.createElement("div");
  sub.className = "sub";
  const yr = item.release_year ? ` · ${item.release_year}` : "";
  const vote = item.vote_average ? ` ★${parseFloat(item.vote_average).toFixed(1)}` : "";
  sub.textContent = (item.media_type || "") + yr + vote;
  const badge = document.createElement("span");
  badge.className = "badge" + (item.in_library ? "" : " missing");
  badge.textContent = item.in_library ? "Available" : "Request";
  meta.append(t, sub, badge);
  div.append(img, meta);
  div.onclick = onClick;
  return div;
}

function updateBrowseToolLabels() {
  const typeLabel = document.getElementById("typeMenuLabel");
  const sortLabel = document.getElementById("sortMenuLabel");
  if (typeLabel) typeLabel.textContent = FILTER_LABELS[filter] || "All";
  if (sortLabel) {
    const sort = document.getElementById("browseSort")?.value || "recent";
    const order = document.getElementById("browseOrder")?.value || "desc";
    const arrow = order === "asc" ? "↑" : "↓";
    sortLabel.textContent = `${SORT_LABELS[sort] || sort} ${arrow}`;
  }
}

function setBrowseChromeVisible(show) {
  const chrome = document.getElementById("browseChrome");
  if (!chrome) return;
  chrome.classList.toggle("hidden", !show);
  if (!show) closeToolPanels();
}

function closeToolPanels() {
  activeToolPanel = null;
  document.querySelectorAll(".tool-panel").forEach((p) => p.classList.add("hidden"));
  document.querySelectorAll(".tool-btn").forEach((b) => {
    b.classList.remove("open");
    b.setAttribute("aria-expanded", "false");
  });
}

function toggleToolPanel(panelId, btnId) {
  const panel = document.getElementById(panelId);
  const btn = document.getElementById(btnId);
  if (!panel || !btn) return;
  const opening = panel.classList.contains("hidden");
  closeToolPanels();
  if (opening) {
    panel.classList.remove("hidden");
    btn.classList.add("open");
    btn.setAttribute("aria-expanded", "true");
    activeToolPanel = panelId;
  }
}

function applyBrowseFilters() {
  browsePage = 1;
  updateBrowseToolLabels();
  closeToolPanels();
  loadBrowse();
}

function clearBrowseFilters() {
  const minRating = document.getElementById("minRating");
  const minYear = document.getElementById("minYear");
  const maxYear = document.getElementById("maxYear");
  const browseSort = document.getElementById("browseSort");
  const browseOrder = document.getElementById("browseOrder");
  if (browseSort) browseSort.value = "recent";
  if (browseOrder) browseOrder.value = "desc";
  if (minRating) minRating.value = "";
  if (minYear) minYear.value = "";
  if (maxYear) maxYear.value = "";
  applyBrowseFilters();
}

function updateTypeFilterVisibility() {
  const courseBtn = document.querySelector('.filter-btn[data-filter="course"]');
  if (!courseBtn) return;
  if (browseScope === "course") {
    courseBtn.classList.add("active");
    courseBtn.classList.remove("hidden");
    document.querySelectorAll(".filter-btn").forEach((b) => {
      if (b.dataset.filter !== "course") b.classList.remove("active");
    });
    filter = "course";
  } else {
    courseBtn.classList.add("hidden");
    if (filter === "course") {
      filter = "all";
      document.querySelectorAll(".filter-btn").forEach((b) => {
        b.classList.toggle("active", b.dataset.filter === "all");
      });
    }
  }
  if (browseScope === "adult" && filter === "course") {
    filter = "all";
    document.querySelectorAll(".filter-btn").forEach((b) => {
      b.classList.toggle("active", b.dataset.filter === "all");
    });
  }
}

function setPortalBrowseScope(scope) {
  const s = (scope || "media").toLowerCase();
  browseScope =
    s === "course"
      ? "course"
      : s === "adult"
        ? "adult"
        : s === "archive"
          ? "archive"
          : s === "shortform"
            ? "shortform"
            : s === "non_catalog" || s === "non-catalog" || s === "noncatalog"
              ? "non_catalog"
              : "media";
  browsePage = 1;
  updateTypeFilterVisibility();
  updateBrowseToolLabels();
}

function titleScopeQuery() {
  let scope = browseScope;
  if (portalIsAdmin && typeof window.getAdminBrowseScope === "function") {
    const adminScope = window.getAdminBrowseScope();
    if (adminScope) scope = adminScope;
  }
  if (
    scope === "adult" ||
    scope === "non_catalog" ||
    scope === "archive" ||
    scope === "shortform" ||
    scope === "course" ||
    scope === "media"
  ) {
    return `?scope=${encodeURIComponent(scope)}`;
  }
  return "";
}

window.setPortalBrowseScope = setPortalBrowseScope;
window.loadPortalBrowse = loadBrowse;
window.setBrowsePage = (p) => {
  browsePage = Math.max(1, parseInt(p, 10) || 1);
};
window.setPortalPageTitle = (text) => {
  const el = document.getElementById("pageTitleText");
  if (el) el.textContent = text || "Library";
};

function browseQuery() {
  const sort = document.getElementById("browseSort")?.value || "recent";
  const order = document.getElementById("browseOrder")?.value || "desc";
  const minRating = document.getElementById("minRating")?.value;
  const minYear = document.getElementById("minYear")?.value;
  const maxYear = document.getElementById("maxYear")?.value;
  let scope = browseScope;
  if (portalIsAdmin && typeof window.getAdminBrowseScope === "function") {
    const adminScope = window.getAdminBrowseScope();
    if (adminScope) scope = adminScope;
  }
  const p = new URLSearchParams({
    limit: String(BROWSE_PAGE),
    page: String(browsePage),
    type: filter,
    scope,
    sort,
    order,
  });
  if (minRating) p.set("min_rating", minRating);
  if (minYear) p.set("min_year", minYear);
  if (maxYear) p.set("max_year", maxYear);
  const adminQ =
    typeof window.getAdminBrowseQuery === "function" ? window.getAdminBrowseQuery() : "";
  if (adminQ) p.set("q", adminQ);
  return p.toString();
}

function renderPagination() {
  const nav = document.getElementById("pagination");
  if (!nav) return;
  if (typeof window.renderPortalPagination === "function") {
    window.renderPortalPagination(nav, browsePage, browsePageCount, (p) => {
      browsePage = p;
      loadBrowse().catch((e) => toast(e.message || "Could not load page"));
    });
    return;
  }
  if (browsePageCount <= 1) {
    nav.classList.add("hidden");
    nav.innerHTML = "";
    return;
  }
  nav.classList.remove("hidden");
  nav.innerHTML = "";
}

async function loadBrowse() {
  const grid = document.getElementById("grid");
  if (grid) {
    grid.innerHTML = "";
    grid.classList.add("is-loading");
    for (let i = 0; i < 12; i++) {
      const sk = document.createElement("div");
      sk.className = "card skeleton";
      grid.appendChild(sk);
    }
  }
  let data;
  try {
    data = await api(`/api/browse?${browseQuery()}`);
  } catch (e) {
    if (grid) {
      grid.classList.remove("is-loading");
      grid.innerHTML = `<p class="sub" style="grid-column:1/-1;padding:1rem">Could not load — ${escapeHtml(e.message || "error")}</p>`;
    }
    return;
  }
  if (data.page != null) browsePage = data.page;
  if (grid) grid.classList.remove("is-loading");
  if (grid) grid.innerHTML = "";
  data.items.forEach((item) => {
    if (!item.content_title_id) return;
    grid.appendChild(
      posterCard(item, () => openDetail(item.content_title_id))
    );
  });
  browseTotal = data.total ?? 0;
  browsePageCount = data.page_count ?? 1;
  const meta = document.getElementById("browseMeta");
  if (meta) {
    const from = browseTotal ? (browsePage - 1) * BROWSE_PAGE + 1 : 0;
    const to = Math.min(browsePage * BROWSE_PAGE, browseTotal);
    meta.textContent =
      browseTotal > 0
        ? `Page ${browsePage} of ${browsePageCount} · titles ${from}–${to} of ${browseTotal}`
        : "No titles match — try clearing filters.";
  }
  renderPagination();
  updateBrowseToolLabels();
}

async function loadFavorites() {
  const data = await api("/api/favorites");
  const grid = document.getElementById("grid");
  grid.innerHTML = "";
  data.items.forEach((item) => {
    grid.appendChild(
      posterCard(item, () => openDetail(item.content_title_id))
    );
  });
}

async function loadWatchlist() {
  const data = await api("/api/watchlist");
  const grid = document.getElementById("grid");
  grid.innerHTML = "";
  if (!data.items.length) {
    grid.innerHTML =
      '<p class="sub" style="grid-column:1/-1;padding:1rem">Nothing saved yet — open a title and tap <b>Watch later</b>.</p>';
    return;
  }
  data.items.forEach((item) => {
    grid.appendChild(
      posterCard(item, () => openDetail(item.content_title_id))
    );
  });
}

async function openDetail(ctId) {
  currentTitleId = ctId;
  const scopeQ = titleScopeQuery();
  const d = await api(`/api/title/${ctId}${scopeQ}`);
  const eps = await api(`/api/title/${ctId}/episodes${scopeQ}`);
  const root = document.getElementById("detailView");
  root.classList.remove("hidden");
  document.getElementById("browseView").classList.add("hidden");
  document.getElementById("searchView").classList.add("hidden");
  setBrowseChromeVisible(false);

  const favLabel = d.is_favorite ? "★ Favorited" : "☆ Favorite";
  const wlLabel = d.on_watchlist ? "⏱ On watch later" : "⏱ Watch later";
  const genres =
    d.genres && d.genres.length
      ? `<p class="sub detail-meta"><b>Genres</b> ${d.genres.map((g) => escapeHtml(g)).join(" · ")}</p>`
      : "";
  const cast =
    d.cast && d.cast.length
      ? `<p class="sub detail-meta"><b>Cast</b> ${d.cast.map((c) => escapeHtml(c)).join(", ")}</p>`
      : "";
  const directors =
    d.directors && d.directors.length
      ? `<p class="sub detail-meta"><b>Director</b> ${d.directors.map((x) => escapeHtml(x)).join(", ")}</p>`
      : "";
  const writers =
    d.writers && d.writers.length
      ? `<p class="sub detail-meta"><b>Writer</b> ${d.writers.map((x) => escapeHtml(x)).join(", ")}</p>`
      : "";
  root.innerHTML = `
    <button type="button" class="btn ghost" id="backBtn">← Back</button>
    <div class="detail-hero">
      <img src="${d.poster_url || "/static/placeholder.svg"}" alt="" />
      <div class="info">
        <h2>${escapeHtml(d.title)}</h2>
        <p class="sub">${d.media_type} ${d.release_year || ""} ${d.vote_average ? "★" + parseFloat(d.vote_average).toFixed(1) : ""}</p>
        ${genres}
        ${cast}
        ${directors}
        ${writers}
        <p class="overview">${escapeHtml(d.overview || "")}</p>
        <div class="actions">
          ${d.available ? '<button class="btn primary" id="watchBtn">▶ Watch</button>' : ""}
          <button class="btn secondary" id="wlBtn">${wlLabel}</button>
          <button class="btn secondary" id="favBtn">${favLabel}</button>
          ${!d.available && d.tmdb_id ? '<button class="btn ghost" id="reqBtn">📨 Request</button>' : ""}
        </div>
      </div>
    </div>
    <div class="list-panel" id="episodePanel">
      <h3>${d.media_type === "course" ? "Lessons" : d.media_type === "tv" ? "Episodes" : "Versions"}</h3>
      <div id="episodeList"></div>
    </div>
    <div class="list-panel hidden" id="qualityPanel">
      <h3>Choose quality</h3>
      <div id="qualityList"></div>
    </div>
    ${portalIsAdmin ? `<div class="list-panel admin-remap-panel" id="title-remap-${ctId}"></div>` : ""}
  `;
  if (portalIsAdmin && typeof mountTitleRemapPanel === "function") {
    mountTitleRemapPanel(ctId, document.getElementById(`title-remap-${ctId}`));
  }
  document.getElementById("backBtn").onclick = backFromDetail;
  document.getElementById("wlBtn").onclick = async () => {
    const r = await api(`/api/watchlist/${ctId}`, { method: "POST" });
    toast(r.on_watchlist ? "Added to watch later" : "Removed from watch later");
    openDetail(ctId);
  };
  document.getElementById("favBtn").onclick = async () => {
    const r = await api(`/api/favorites/${ctId}`, { method: "POST" });
    toast(r.favorited ? "Added to favorites" : "Removed from favorites");
    openDetail(ctId);
  };
  if (document.getElementById("reqBtn")) {
    document.getElementById("reqBtn").onclick = async () => {
      await api("/api/requests", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          tmdb_id: d.tmdb_id,
          media_type: d.media_type,
          title: d.title,
          release_year: d.release_year,
        }),
      });
      toast("Request submitted");
    };
  }
  const epList = document.getElementById("episodeList");
  const isMovie = d.media_type === "movie" && eps.episodes.length <= 1;
  if (isMovie && d.available) {
    document.getElementById("watchBtn").onclick = () =>
      pickQuality(ctId, null, null);
  } else if (document.getElementById("watchBtn")) {
    document.getElementById("watchBtn").onclick = () =>
      toast("Pick a lesson or episode below");
  }
  eps.episodes.forEach((ep) => {
    const row = document.createElement("div");
    row.className = "episode-row";
    row.innerHTML = `<span class="ep-main">${escapeHtml(ep.label)}</span><span class="ep-meta">${escapeHtml(ep.versions_label || "")}</span>`;
    row.onclick = () => pickQuality(ctId, ep.season, ep.episode, ep.label);
    epList.appendChild(row);
  });
}

async function pickQuality(ctId, season, episode, episodeLabel) {
  let url = `/api/title/${ctId}/qualities`;
  const params = new URLSearchParams();
  if (season != null) params.set("season", season);
  if (episode != null) params.set("episode", episode);
  let scope = browseScope;
  if (portalIsAdmin && typeof window.getAdminBrowseScope === "function") {
    const adminScope = window.getAdminBrowseScope();
    if (adminScope) scope = adminScope;
  }
  if (
    scope === "adult" ||
    scope === "non_catalog" ||
    scope === "archive" ||
    scope === "shortform" ||
    scope === "course" ||
    scope === "media"
  ) {
    params.set("scope", scope);
  }
  if (params.toString()) url += "?" + params.toString();
  const data = await api(url);
  const panel = document.getElementById("qualityPanel");
  const list = document.getElementById("qualityList");
  panel.classList.remove("hidden");
  const heading = panel.querySelector("h3");
  if (heading) {
    heading.textContent = episodeLabel ? `Quality — ${episodeLabel}` : "Choose quality";
  }
  list.innerHTML = "";
  data.qualities.forEach((q) => {
    const row = document.createElement("div");
    row.className = "quality-row";
    row.innerHTML = `<span>${escapeHtml(q.quality)} · ${escapeHtml(q.size)}</span>`;
    const actions = document.createElement("div");
    const play = document.createElement("button");
    play.className = "btn primary";
    play.textContent = "Play";
    play.style.marginRight = "0.35rem";
    play.onclick = async (e) => {
      e.stopPropagation();
      if (!q.can_stream) {
        toast("Browser play unavailable — run telethon_login.py on the server");
        return;
      }
      playInBrowser(q.upload_id);
    };
    actions.appendChild(play);
    const tg = document.createElement("button");
    tg.className = "btn secondary";
    tg.textContent = "📲 Telegram";
    tg.onclick = async (e) => {
      e.stopPropagation();
      await sendToTelegram(q.upload_id);
    };
    actions.appendChild(tg);
    row.appendChild(actions);
    list.appendChild(row);
  });
}

function streamUrl(uploadId) {
  return `/api/stream/${uploadId}?token=${encodeURIComponent(token())}`;
}

function formatBytes(n) {
  if (!n || n <= 0) return "0 B";
  if (n >= 1e9) return (n / 1e9).toFixed(1) + " GB";
  if (n >= 1e6) return (n / 1e6).toFixed(0) + " MB";
  if (n >= 1e3) return (n / 1e3).toFixed(0) + " KB";
  return n + " B";
}

function setPlayerProgress(percent, label, show) {
  const wrap = document.getElementById("playerProgressWrap");
  const bar = document.getElementById("playerProgressBar");
  const lbl = document.getElementById("playerProgressLabel");
  if (!wrap || !bar) return;
  wrap.classList.toggle("hidden", !show);
  bar.style.width = `${Math.min(100, Math.max(0, percent))}%`;
  if (lbl) lbl.textContent = label || "";
}

function setPlayerStatus(msg, show) {
  const el = document.getElementById("playerStatus");
  if (!el) return;
  el.textContent = msg || "";
  el.classList.toggle("hidden", !show);
}

function stopStreamProgressPoll() {
  if (streamProgressTimer) {
    clearInterval(streamProgressTimer);
    streamProgressTimer = null;
  }
}

function startStreamProgressPoll(uploadId, video) {
  stopStreamProgressPoll();
  streamProgressTimer = setInterval(async () => {
    try {
      const p = await api(`/api/stream/${uploadId}/progress`);
      if (p.error || p.phase === "failed") {
        stopStreamProgressPoll();
        setPlayerProgress(0, "", false);
        setPlayerStatus(
          (p.error || "Stream failed") + " — try 📱 Telegram on Pending list",
          true
        );
        return;
      }
      let bufferPct = 0;
      if (video && video.buffered.length && video.duration) {
        bufferPct = (video.buffered.end(0) / video.duration) * 100;
      }
      const tgPct = p.request_percent || p.file_percent || 0;
      const pct = Math.max(tgPct, bufferPct);
      const label = p.active
        ? `Telegram → server: ${tgPct}% (${formatBytes(p.bytes_from_telegram)} loaded)`
        : bufferPct > 0
          ? `Buffered: ${Math.round(bufferPct)}%`
          : "Starting playback…";
      setPlayerProgress(pct, label, true);
      setPlayerStatus(label, !video || video.readyState < 2);
      if (!p.active && video && video.readyState >= 2) {
        setPlayerProgress(bufferPct, "", false);
        setPlayerStatus("", false);
      }
    } catch {
      stopStreamProgressPoll();
    }
  }, 500);
}

function playInBrowser(uploadId, fileName) {
  const overlay = document.getElementById("playerOverlay");
  const video = document.getElementById("playerVideo");
  if (!overlay || !video) return;
  const needsConvert =
    /\.(mkv|avi|mov|ts|m2ts|wmv|flv|mpeg|mpg)$/i.test(fileName || "") &&
    window.portalFfmpegTranscode;
  overlay.classList.remove("hidden");
  setPlayerStatus(
    needsConvert
      ? "Converting to MP4 for browser playback (first play may take a moment)…"
      : "Connecting to Telegram…",
    !!needsConvert
  );
  setPlayerProgress(
    0,
    needsConvert ? "ffmpeg remux/transcode…" : "Waiting for stream from Telegram…",
    true
  );
  startStreamProgressPoll(uploadId, video);
  video.onerror = () => {
    stopStreamProgressPoll();
    setPlayerProgress(0, "", false);
    setPlayerStatus(
      needsConvert
        ? "Conversion or playback failed — try 📱 Telegram"
        : "Playback failed — try Telegram or another quality.",
      true
    );
    toast(
      needsConvert
        ? "Could not play converted stream — try Telegram play"
        : "Video could not play in browser"
    );
  };
  video.onloadedmetadata = () => {
    if (video.readyState >= 2) {
      setPlayerProgress(0, "", false);
      setPlayerStatus("", false);
    }
  };
  video.oncanplay = () => {
    setPlayerProgress(0, "", false);
    setPlayerStatus("", false);
  };
  video.src = streamUrl(uploadId);
  video.load();
  video.play().catch(() => {
    setPlayerStatus("Loading… tap play when the bar moves.", true);
  });
}

function closePlayer() {
  stopStreamProgressPoll();
  const overlay = document.getElementById("playerOverlay");
  const video = document.getElementById("playerVideo");
  if (video) {
    video.onerror = null;
    video.onloadedmetadata = null;
    video.oncanplay = null;
    video.pause();
    video.removeAttribute("src");
    video.load();
  }
  setPlayerStatus("", false);
  setPlayerProgress(0, "", false);
  overlay?.classList.add("hidden");
}

async function sendToTelegram(uploadId) {
  try {
    const r = await api(`/api/play/${uploadId}`, { method: "POST" });
    toast(r.message || "Sent to your Telegram chat");
  } catch (e) {
    toast(e.message);
  }
}

function backFromDetail() {
  document.getElementById("detailView").classList.add("hidden");
  currentTitleId = null;
  const app = document.getElementById("app");
  if (app?.classList.contains("is-admin") && typeof loadAdminSection === "function") {
    const section = localStorage.getItem("portal_admin_section") || "dashboard";
    loadAdminSection(section, { persist: false });
    return;
  }
  document.getElementById("browseView").classList.remove("hidden");
  const activeTab = document.querySelector("nav.tabs-main button.active")?.dataset?.tab;
  setBrowseChromeVisible(activeTab === "browse");
}

function escapeHtml(s) {
  const d = document.createElement("div");
  d.textContent = s || "";
  return d.innerHTML;
}

async function runSearch(q) {
  if (!q || q.length < 2) return;
  const data = await api(`/api/search?q=${encodeURIComponent(q)}`);
  document.getElementById("browseView").classList.add("hidden");
  document.getElementById("detailView").classList.add("hidden");
  document.getElementById("searchView").classList.remove("hidden");
  setBrowseChromeVisible(false);
  const lib = document.getElementById("searchLib");
  const tmdb = document.getElementById("searchTmdb");
  lib.innerHTML = "";
  tmdb.innerHTML = "";
  data.library.forEach((item) => {
    lib.appendChild(
      posterCard(item, () => openDetail(item.content_title_id))
    );
  });
  data.tmdb.forEach((item) => {
    const div = posterCard(item, async () => {
      if (item.content_title_id) openDetail(item.content_title_id);
      else if (!item.request_pending) {
        await api("/api/requests", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            tmdb_id: item.tmdb_id,
            media_type: item.media_type,
            title: item.title,
            release_year: item.release_year,
          }),
        });
        toast("Request submitted");
      } else toast("Already requested");
    });
    tmdb.appendChild(div);
  });
}

document.querySelectorAll("nav.tabs-main button").forEach((btn) => {
  btn.onclick = () => {
    if (portalIsAdmin && typeof hideAllAdminSections === "function") {
      hideAllAdminSections();
    }
    document.querySelectorAll("nav.tabs-main button").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    document.querySelectorAll(".admin-section-view").forEach((v) => v.classList.add("hidden"));
    document.getElementById("searchView")?.classList.add("hidden");
    document.getElementById("detailView")?.classList.add("hidden");
    const tab = btn.dataset.tab;
    if (tab === "favorites") {
      setBrowseChromeVisible(false);
      document.getElementById("browseView").classList.remove("hidden");
      loadFavorites();
    } else if (tab === "watchlist") {
      setBrowseChromeVisible(false);
      document.getElementById("browseView").classList.remove("hidden");
      loadWatchlist();
    } else {
      setPortalBrowseScope("media");
      setBrowseChromeVisible(true);
      document.getElementById("browseView").classList.remove("hidden");
      window.setPortalPageTitle?.("Library");
      loadBrowse();
    }
  };
});

document.getElementById("typeMenuBtn")?.addEventListener("click", (e) => {
  e.stopPropagation();
  toggleToolPanel("typePanel", "typeMenuBtn");
});

document.getElementById("sortMenuBtn")?.addEventListener("click", (e) => {
  e.stopPropagation();
  toggleToolPanel("sortPanel", "sortMenuBtn");
});

document.querySelectorAll(".filter-btn").forEach((btn) => {
  btn.onclick = () => {
    document.querySelectorAll(".filter-btn").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    filter = btn.dataset.filter;
    updateBrowseToolLabels();
    closeToolPanels();
    browsePage = 1;
    loadBrowse();
  };
});

document.getElementById("applyFiltersBtn")?.addEventListener("click", applyBrowseFilters);
document.getElementById("clearFiltersBtn")?.addEventListener("click", clearBrowseFilters);

document.addEventListener("click", (e) => {
  if (!activeToolPanel) return;
  if (e.target.closest(".browse-chrome")) return;
  closeToolPanels();
});

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") closeToolPanels();
});

let searchTimer;
document.getElementById("searchInput").addEventListener("input", (e) => {
  clearTimeout(searchTimer);
  const q = e.target.value.trim();
  searchTimer = setTimeout(() => {
    if (
      portalIsAdmin &&
      typeof handleAdminSearch === "function" &&
      handleAdminSearch(q)
    ) {
      return;
    }
    if (q.length >= 2) runSearch(q);
    else {
      if (portalIsAdmin && typeof handleAdminSearch === "function") {
        handleAdminSearch("");
      }
      document.getElementById("searchView").classList.add("hidden");
      document.getElementById("browseView").classList.remove("hidden");
      setBrowseChromeVisible(true);
      document.querySelectorAll("nav.tabs-main button").forEach((b) => {
        b.classList.toggle("active", b.dataset.tab === "browse");
      });
      if (portalIsAdmin && typeof loadPortalBrowse === "function") loadPortalBrowse();
    }
  }, 400);
});

document.getElementById("playerClose")?.addEventListener("click", closePlayer);

window.playInBrowser = playInBrowser;
window.sendToTelegram = sendToTelegram;

async function init() {
  const params = new URLSearchParams(window.location.search);
  const t = params.get("token");
  if (t) {
    setToken(t);
    window.history.replaceState({}, "", window.location.pathname);
  }
  if (!token()) {
    showLogin();
    return;
  }
  try {
    const auth = await api("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token: token() }),
    });
    showApp();
    portalIsAdmin = auth.role === "admin";
    if (portalIsAdmin && typeof initAdminShell === "function") {
      document.getElementById("app")?.classList.add("is-admin");
      initAdminShell();
    } else {
      setBrowseChromeVisible(true);
      updateBrowseToolLabels();
      updateTypeFilterVisibility();
      loadBrowse();
    }
  } catch {
    showLogin();
  }
}

init();
