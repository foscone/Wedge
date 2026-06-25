const $ = (id) => document.getElementById(id);

// Slug from URL: /p/{slug}
const SLUG = decodeURIComponent((location.pathname.match(/\/p\/([^/]+)/) || [])[1] || "");
if (!SLUG) { location.href = "/"; }
const API_BASE = "/api/projects/" + encodeURIComponent(SLUG);
const LOGIN_URL = "/p/" + encodeURIComponent(SLUG) + "/login";

async function api(path, opts) {
  const r = await fetch(API_BASE + path, opts);
  if (r.status === 401) {
    const here = location.pathname + location.search + location.hash;
    location.href = LOGIN_URL + "?next=" + encodeURIComponent(here);
    throw new Error("unauthorized");
  }
  return r;
}

let state = { plans: [], media: [], new_count: 0, tag_types: [], tags: [], level: "view" };
let coneHitboxes = [];
let tagFilter = new Set();
let view = { scale: 1, tx: 0, ty: 0 };
let panning = null;
let currentPlan = null;
let planImg = null;
let selectedMedia = null;
let fov = 60;
let filter = "unplaced";
let placing = null;
let mode = "place";
let timeline = [];
let pinningNote = false;
let pendingSharedMedia = new URLSearchParams(location.search).get('media') || null;
let selectedForPdf = new Set();

const canvas = $("canvas");
const ctx = canvas.getContext("2d");

function canEdit() { return state.level === "edit"; }

async function loadState() {
  const r = await api("/state");
  state = await r.json();
  document.title = "Wedge · " + (state.project?.name || SLUG);
  $("projectName").textContent = state.project?.name || SLUG;
  applyLevelToUI();
  if (!currentPlan && state.plans.length) currentPlan = state.plans[0];
  renderPlans();
  renderMediaList();
  rebuildTimeline();
  await loadPlanImage();
  draw();
  if (pendingSharedMedia) {
    const shared = pendingSharedMedia;
    pendingSharedMedia = null;
    if (state.media.find(m => m.name === shared)) {
      selectMedia(shared);
    }
  }
}

function applyLevelToUI() {
  const edit = canEdit();
  // hide place-only controls when read-only
  document.body.classList.toggle("view-only", !edit);
  $("modePlace").style.display = edit ? "" : "none";
  if (!edit && mode === "place") setMode("view");
}

function rebuildTimeline() {
  timeline = state.media
    .filter(p => !p.missing && (mode === "place" ? true : p.status === "placed"))
    .filter(p => mode !== "view" || photoMatchesTagFilter(p))
    .slice()
    .sort((a, b) => (a.taken_at || "").localeCompare(b.taken_at || "") || a.name.localeCompare(b.name));
  const range = $("tlRange");
  range.max = Math.max(0, timeline.length - 1);
  if (mode === "view") {
    const idx = timeline.findIndex(p => p.name === selectedMedia);
    if (idx >= 0) { range.value = idx; updateTlLabel(idx); }
    else if (timeline.length) { range.value = 0; selectTimelineIndex(0); }
    else updateTlLabel(-1);
  }
}

function updateTlLabel(idx) {
  const lbl = $("tlLabel");
  if (idx < 0 || !timeline[idx]) { lbl.textContent = "—"; return; }
  const p = timeline[idx];
  const d = p.taken_at ? new Date(p.taken_at).toLocaleString() : "senza data";
  lbl.textContent = `${idx + 1}/${timeline.length} · ${d}`;
}

function selectTimelineIndex(idx) {
  if (!timeline[idx]) return;
  const p = timeline[idx];
  selectMedia(p.name);
  $("tlRange").value = idx;
  updateTlLabel(idx);
}

function renderPlans() {
  const grid = $("planGrid");
  grid.innerHTML = "";
  if (!state.plans.length) {
    grid.innerHTML = '<div style="font-size:11px;color:#888">(nessuna planimetria)</div>';
    return;
  }
  const n = state.plans.length;
  grid.style.gridTemplateColumns = `repeat(${n <= 4 ? 2 : 3}, 1fr)`;
  for (const p of state.plans) {
    const d = document.createElement("div");
    d.className = "plan-item" + (p === currentPlan ? " selected" : "");
    d.innerHTML = `<img src="${API_BASE}/plan/${encodeURIComponent(p)}" alt=""><div class="plan-name">${p}</div>`;
    d.onclick = async () => {
      currentPlan = p;
      renderPlans();
      await loadPlanImage();
      draw();
    };
    grid.appendChild(d);
  }
}

function renderMediaList() {
  const list = $("photoList");
  list.innerHTML = "";
  let counts = { unplaced: 0, placed: 0, skipped: 0 };
  for (const p of state.media) counts[p.status]++;
  $("counts").textContent = `Da posizionare: ${counts.unplaced} · Posizionati: ${counts.placed} · Saltati: ${counts.skipped}`;

  const filtered = state.media
    .filter(p => filter === "all" || p.status === filter)
    .filter(p => mode !== "view" || photoMatchesTagFilter(p))
    .slice()
    .sort((a, b) => (a.taken_at || "").localeCompare(b.taken_at || "") || a.name.localeCompare(b.name));
  for (const p of filtered) {
    const div = document.createElement("div");
    div.className = "photo-item" + (selectedMedia === p.name ? " selected" : "");
    const badge = p.kind === "video" ? '<span class="kind-badge">▶</span>' : '';
    const checked = selectedForPdf.has(p.name) ? "checked" : "";
    div.innerHTML = `
      <input type="checkbox" class="pdf-check" ${checked} title="Includi nel PDF">
      <div class="thumb-wrap">
        <img src="${API_BASE}/thumb/${encodeURIComponent(p.name)}" alt="">
        ${badge}
      </div>
      <span class="name">${p.name}${p.taken_at ? `<br><span style="color:#888;font-size:10px">${new Date(p.taken_at).toLocaleString()}</span>` : ''}</span>
      <span class="dot ${p.status}" title="${p.status}"></span>
    `;
    const cb = div.querySelector(".pdf-check");
    cb.onclick = (e) => {
      e.stopPropagation();
      if (cb.checked) selectedForPdf.add(p.name);
      else selectedForPdf.delete(p.name);
      updatePdfCount();
    };
    div.onclick = () => selectMedia(p.name);
    list.appendChild(div);
  }
  updatePdfCount();
}

function updatePdfCount() {
  const n = selectedForPdf.size;
  const btn = $("btnExportPdf");
  if (btn) btn.textContent = `Esporta PDF (${n})`;
  const sel = $("pdfSelCount");
  if (sel) sel.textContent = n;
}

function currentFilteredMedia() {
  return state.media
    .filter(p => filter === "all" || p.status === filter)
    .filter(p => mode !== "view" || photoMatchesTagFilter(p));
}

function selectMedia(name) {
  selectedMedia = name;
  const p = state.media.find(x => x.name === name);
  $("previewName").textContent = name;
  $("btnShare").disabled = !p;
  renderPreviewMedia(p);
  $("previewInfo").textContent = p ? `Tipo: ${p.kind} · Stato: ${p.status}${p.plan ? ' · ' + p.plan : ''}${p.angle != null ? ' · ' + Math.round(p.angle) + '°' : ''}` : '';
  renderPhotoTags(p);
  renderNotes(p);
  cancelPinningMode();
  const edit = canEdit();
  $("btnSkip").disabled = !edit || mode !== "place";
  $("btnReset").disabled = !edit || mode !== "place" || !(p && p.status !== 'unplaced');
  if (p && p.status === 'placed' && p.plan && p.plan !== currentPlan) {
    currentPlan = p.plan;
    renderPlans();
    loadPlanImage().then(draw);
  }
  if (p && p.fov) { fov = p.fov; $("fov").value = fov; $("fovVal").textContent = fov; }
  renderMediaList();
  draw();
}

function renderPreviewMedia(p) {
  const wrap = $("previewMedia");
  wrap.innerHTML = "";
  if (!p) return;
  if (p.kind === "video") {
    const v = document.createElement("video");
    v.controls = true;
    v.preload = "metadata";
    v.src = API_BASE + "/media/" + encodeURIComponent(p.name);
    v.style.width = "100%";
    v.style.background = "#111";
    wrap.appendChild(v);
  } else {
    const img = document.createElement("img");
    img.id = "previewImg";
    img.src = API_BASE + "/media/" + encodeURIComponent(p.name);
    img.onload = () => renderNotePins(p);
    wrap.appendChild(img);
  }
}

function renderNotes(p) {
  const list = $("notesList");
  const actions = $("notesActions");
  list.innerHTML = "";
  if (!p) {
    actions.classList.add("hidden");
    return;
  }
  if (canEdit()) {
    actions.classList.remove("hidden");
    $("btnAddPin").style.display = (p.kind === "image") ? "" : "none";
  } else {
    actions.classList.add("hidden");
  }
  const notes = p.notes || [];
  for (const n of notes) {
    const row = document.createElement("div");
    row.className = "note-row" + (n.x != null ? " pinned" : "");
    const text = document.createElement("div");
    text.className = "note-text";
    text.textContent = n.text;
    if (canEdit()) {
      text.title = "Click per modificare";
      text.onclick = () => editNote(n);
    }
    row.appendChild(text);
    if (canEdit()) {
      const del = document.createElement("button");
      del.className = "note-del";
      del.textContent = "×";
      del.title = "Elimina nota";
      del.onclick = async (e) => {
        e.stopPropagation();
        if (!confirm("Eliminare questa nota?")) return;
        await api("/notes/" + n.id, { method: "DELETE" });
        await loadState();
        if (selectedMedia) selectMedia(selectedMedia);
      };
      row.appendChild(del);
    }
    list.appendChild(row);
  }
  renderNotePins(p);
}

function renderNotePins(p) {
  const wrap = $("previewMedia");
  const old = wrap.querySelector(".note-overlay");
  if (old) old.remove();
  if (!p || p.kind !== "image") return;
  const notes = (p.notes || []).filter(n => n.x != null);
  if (!notes.length) return;
  const overlay = document.createElement("div");
  overlay.className = "note-overlay";
  for (const n of notes) {
    const pin = document.createElement("div");
    pin.className = "note-pin";
    pin.style.left = (n.x * 100) + "%";
    pin.style.top = (n.y * 100) + "%";
    pin.title = n.text;
    overlay.appendChild(pin);
  }
  wrap.appendChild(overlay);
}

async function editNote(n) {
  const t = prompt("Modifica nota:", n.text);
  if (t === null) return;
  const text = t.trim();
  if (!text) return;
  await api("/notes/" + n.id, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  await loadState();
  if (selectedMedia) selectMedia(selectedMedia);
}

function cancelPinningMode() {
  if (!pinningNote) return;
  pinningNote = false;
  $("previewMedia").classList.remove("pinning");
  $("btnAddPin").classList.remove("active");
}

async function loadPlanImage() {
  if (!currentPlan) { planImg = null; return; }
  return new Promise((res) => {
    const img = new Image();
    img.onload = () => { planImg = img; resizeCanvas(); res(); };
    img.onerror = () => { planImg = null; res(); };
    img.src = API_BASE + "/plan/" + encodeURIComponent(currentPlan);
  });
}

function resizeCanvas() {
  const w = canvas.parentElement.clientWidth;
  const h = canvas.parentElement.clientHeight;
  canvas.width = w;
  canvas.height = h;
  fitPlan();
}

function fitPlan() {
  if (!planImg) { view = { scale: 1, tx: 0, ty: 0 }; return; }
  const s = Math.min(canvas.width / planImg.width, canvas.height / planImg.height);
  view.scale = s;
  view.tx = (canvas.width - planImg.width * s) / 2;
  view.ty = (canvas.height - planImg.height * s) / 2;
}

function screenToPlan(sx, sy) {
  return { x: (sx - view.tx) / view.scale, y: (sy - view.ty) / view.scale };
}

function dayKey(iso) {
  if (!iso) return null;
  return iso.slice(0, 10);
}
function addDays(iso, d) {
  const dt = new Date(iso + "T00:00:00");
  dt.setDate(dt.getDate() + d);
  return dt.toISOString().slice(0, 10);
}

function conesToShow() {
  let all = state.media.filter(p => p.status === 'placed' && p.plan === currentPlan);
  if (mode === "view") return all.filter(photoMatchesTagFilter);
  const cur = state.media.find(p => p.name === selectedMedia);
  const curDay = cur ? dayKey(cur.taken_at) : null;
  if (!curDay) return all;
  const allowed = new Set([addDays(curDay, -1), curDay, addDays(curDay, 1)]);
  return all.filter(p => allowed.has(dayKey(p.taken_at)));
}

function draw() {
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.fillStyle = "#15151a";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.setTransform(view.scale, 0, 0, view.scale, view.tx, view.ty);
  if (planImg) ctx.drawImage(planImg, 0, 0);
  coneHitboxes = [];
  const coneLen = planImg ? Math.max(planImg.width, planImg.height) * 0.12 : 100;
  for (const p of conesToShow()) {
    drawCone(p.x, p.y, p.angle, p.fov || 60, p.name === selectedMedia, coneLen, p.kind);
    coneHitboxes.push({ p, x: p.x, y: p.y, angle: p.angle, fov: p.fov || 60, len: coneLen });
  }
  if (placing) {
    drawCone(placing.x, placing.y, placing.angle, fov, true, coneLen, null);
  }
  ctx.setTransform(1, 0, 0, 1, 0, 0);
}

function hitCone(cx, cy) {
  for (const h of coneHitboxes) {
    const dx = cx - h.x, dy = cy - h.y;
    const dist = Math.hypot(dx, dy);
    if (dist > h.len || dist < 1) continue;
    let a = Math.atan2(dy, dx) * 180 / Math.PI;
    let da = ((a - h.angle + 540) % 360) - 180;
    if (Math.abs(da) <= h.fov / 2) return h.p;
  }
  return null;
}

function drawCone(x, y, angleDeg, fovDeg, highlight, len, kind) {
  if (!len) len = 100;
  const a = angleDeg * Math.PI / 180;
  const half = (fovDeg / 2) * Math.PI / 180;
  ctx.beginPath();
  ctx.moveTo(x, y);
  ctx.arc(x, y, len, a - half, a + half);
  ctx.closePath();
  const isVideo = kind === "video";
  if (highlight) {
    ctx.fillStyle = isVideo ? "rgba(255,180,80,0.45)" : "rgba(108,200,255,0.45)";
    ctx.strokeStyle = isVideo ? "#fb6" : "#6cf";
  } else {
    ctx.fillStyle = isVideo ? "rgba(220,150,60,0.35)" : "rgba(76,200,140,0.35)";
    ctx.strokeStyle = isVideo ? "#d96" : "#4c8";
  }
  ctx.fill();
  ctx.lineWidth = 2 / view.scale;
  ctx.stroke();
  ctx.beginPath();
  ctx.arc(x, y, 5 / view.scale, 0, Math.PI * 2);
  ctx.fillStyle = highlight
    ? (isVideo ? "#fb6" : "#6cf")
    : (isVideo ? "#d96" : "#4c8");
  ctx.fill();
}

function canvasCoords(e) {
  const r = canvas.getBoundingClientRect();
  const sx = (e.clientX - r.left) * (canvas.width / r.width);
  const sy = (e.clientY - r.top) * (canvas.height / r.height);
  return screenToPlan(sx, sy);
}
function rawCoords(e) {
  const r = canvas.getBoundingClientRect();
  return {
    x: (e.clientX - r.left) * (canvas.width / r.width),
    y: (e.clientY - r.top) * (canvas.height / r.height),
  };
}

let dragging = false;
canvas.addEventListener("wheel", (e) => {
  e.preventDefault();
  const r = rawCoords(e);
  const factor = Math.exp(-e.deltaY * 0.0015);
  const newScale = Math.max(0.05, Math.min(20, view.scale * factor));
  const k = newScale / view.scale;
  view.tx = r.x - (r.x - view.tx) * k;
  view.ty = r.y - (r.y - view.ty) * k;
  view.scale = newScale;
  draw();
}, { passive: false });

canvas.addEventListener("contextmenu", (e) => e.preventDefault());

canvas.addEventListener("mousedown", (e) => {
  if (e.button === 1 || e.button === 2 || e.shiftKey) {
    const r = rawCoords(e);
    panning = { sx: r.x, sy: r.y, tx0: view.tx, ty0: view.ty };
    canvas.style.cursor = "grabbing";
    e.preventDefault();
    return;
  }
  if (mode === "view") {
    const c = canvasCoords(e);
    const hit = hitCone(c.x, c.y);
    if (hit) {
      const idx = timeline.findIndex(p => p.name === hit.name);
      if (idx >= 0) selectTimelineIndex(idx);
      else selectMedia(hit.name);
    }
    return;
  }
  if (!canEdit()) return;
  if (!selectedMedia || !planImg) return;
  const c = canvasCoords(e);
  placing = { x: c.x, y: c.y, angle: 0 };
  dragging = true;
  draw();
});
canvas.addEventListener("mousemove", (e) => {
  if (panning) {
    const r = rawCoords(e);
    view.tx = panning.tx0 + (r.x - panning.sx);
    view.ty = panning.ty0 + (r.y - panning.sy);
    draw();
    return;
  }
  if (mode === "view") {
    const c = canvasCoords(e);
    canvas.style.cursor = hitCone(c.x, c.y) ? "pointer" : "default";
    return;
  }
  if (!dragging || !placing) return;
  const c = canvasCoords(e);
  const dx = c.x - placing.x;
  const dy = c.y - placing.y;
  if (dx * dx + dy * dy > 4) {
    placing.angle = Math.atan2(dy, dx) * 180 / Math.PI;
  }
  draw();
});
canvas.addEventListener("mouseup", async (e) => {
  if (panning) {
    panning = null;
    canvas.style.cursor = mode === "place" ? "crosshair" : "default";
    return;
  }
  if (!dragging || !placing) return;
  dragging = false;
  await api("/place", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      name: selectedMedia,
      plan: currentPlan,
      x: placing.x, y: placing.y,
      angle: placing.angle, fov,
    }),
  });
  placing = null;
  const idx = state.media.findIndex(p => p.name === selectedMedia);
  await loadState();
  const next = state.media.find((p, i) => i > idx && p.status === 'unplaced');
  if (next) selectMedia(next.name);
});

$("fov").addEventListener("input", (e) => {
  fov = +e.target.value;
  $("fovVal").textContent = fov;
  draw();
});
$("filter").addEventListener("change", (e) => { filter = e.target.value; renderMediaList(); });

$("btnSkip").onclick = async () => {
  if (!selectedMedia) return;
  await api("/skip", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: selectedMedia }) });
  const idx = state.media.findIndex(p => p.name === selectedMedia);
  await loadState();
  const next = state.media.find((p, i) => i > idx && p.status === 'unplaced');
  if (next) selectMedia(next.name);
};
$("btnReset").onclick = async () => {
  if (!selectedMedia) return;
  await api("/reset", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: selectedMedia }) });
  await loadState();
  selectMedia(selectedMedia);
};

$("btnLogout").onclick = async () => {
  await api("/logout", { method: "POST" });
  location.href = "/";
};

function setMode(m) {
  mode = m;
  cancelPinningMode();
  $("modePlace").classList.toggle("active", m === "place");
  $("modeView").classList.toggle("active", m === "view");
  $("timeline").classList.toggle("hidden", m !== "view");
  $("sidebar").classList.toggle("view-mode", m === "view");
  canvas.style.cursor = m === "place" ? "crosshair" : "default";
  if (m === "view") {
    filter = "placed";
    $("filter").value = "placed";
  }
  renderMediaList();
  rebuildTimeline();
  draw();
}
$("modePlace").onclick = () => setMode("place");
$("modeView").onclick = () => setMode("view");

$("tlRange").addEventListener("input", (e) => selectTimelineIndex(+e.target.value));
$("tlPrev").onclick = () => { const i = Math.max(0, (+$("tlRange").value) - 1); selectTimelineIndex(i); };
$("tlNext").onclick = () => { const i = Math.min(timeline.length - 1, (+$("tlRange").value) + 1); selectTimelineIndex(i); };
window.addEventListener("resize", () => { resizeCanvas(); draw(); });
window.addEventListener("keydown", (e) => {
  if (e.key === "0" && (e.ctrlKey || e.metaKey)) { fitPlan(); draw(); e.preventDefault(); return; }
  if (mode !== "view") return;
  if (e.target.tagName === "INPUT" || e.target.tagName === "SELECT") return;
  if (e.key === "ArrowLeft") { $("tlPrev").click(); e.preventDefault(); }
  if (e.key === "ArrowRight") { $("tlNext").click(); e.preventDefault(); }
});

function renderPhotoTags(p) {
  const el = $("photoTags");
  el.innerHTML = "";
  const header = document.querySelector("#tagsBox .tags-header strong");
  if (mode === "view") {
    header.textContent = "Filtro per tag";
    $("manageTags").classList.add("hidden");
    renderTagFilter(el);
    return;
  }
  header.textContent = "Tag";
  if (canEdit()) $("manageTags").classList.remove("hidden");
  else $("manageTags").classList.add("hidden");
  if (!p) return;
  const assigned = new Set(p.tag_ids || []);
  for (const t of state.tag_types) {
    const block = document.createElement("div");
    block.className = "tag-type-block";
    const lbl = document.createElement("div");
    lbl.className = "tag-type-label";
    lbl.textContent = t.name;
    lbl.style.color = t.color;
    block.appendChild(lbl);
    const tagsOfType = state.tags.filter(tg => tg.type_id === t.id);
    for (const tg of tagsOfType) {
      const chip = document.createElement("span");
      chip.className = "tag-chip" + (assigned.has(tg.id) ? " on" : "");
      chip.style.borderColor = t.color;
      chip.textContent = tg.name;
      if (canEdit()) {
        chip.onclick = async () => {
          if (assigned.has(tg.id)) assigned.delete(tg.id); else assigned.add(tg.id);
          await api("/media_tags", { method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name: p.name, tag_ids: [...assigned] }) });
          await loadState();
          selectMedia(p.name);
        };
      } else {
        chip.style.cursor = "default";
      }
      block.appendChild(chip);
    }
    if (canEdit()) {
      const add = document.createElement("span");
      add.className = "tag-chip";
      add.textContent = "+";
      add.title = "Aggiungi nuovo tag per " + t.name;
      add.onclick = async () => {
        const name = prompt(`Nuovo tag "${t.name}":`);
        if (!name) return;
        const r = await api("/tags", { method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ type_id: t.id, name }) });
        if (!r.ok) { alert("Errore creazione tag"); return; }
        const { id } = await r.json();
        assigned.add(id);
        await api("/media_tags", { method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name: p.name, tag_ids: [...assigned] }) });
        await loadState();
        selectMedia(p.name);
      };
      block.appendChild(add);
    }
    el.appendChild(block);
  }
}

function renderTagFilter(el) {
  for (const t of state.tag_types) {
    const tagsOfType = state.tags.filter(tg => tg.type_id === t.id);
    if (!tagsOfType.length) continue;
    const block = document.createElement("div");
    block.className = "tag-type-block";
    const lbl = document.createElement("div");
    lbl.className = "tag-type-label";
    lbl.textContent = t.name;
    lbl.style.color = t.color;
    block.appendChild(lbl);
    for (const tg of tagsOfType) {
      const chip = document.createElement("span");
      chip.className = "tag-chip" + (tagFilter.has(tg.id) ? " on" : "");
      chip.style.borderColor = t.color;
      chip.textContent = tg.name;
      chip.onclick = () => {
        if (tagFilter.has(tg.id)) tagFilter.delete(tg.id); else tagFilter.add(tg.id);
        applyTagFilter();
      };
      block.appendChild(chip);
    }
    el.appendChild(block);
  }
  if (tagFilter.size) {
    const clear = document.createElement("button");
    clear.textContent = "Azzera filtri";
    clear.style.marginTop = "6px";
    clear.onclick = () => { tagFilter.clear(); applyTagFilter(); };
    el.appendChild(clear);
  }
}

function photoMatchesTagFilter(p) {
  if (!tagFilter.size) return true;
  const byType = {};
  for (const tid of tagFilter) {
    const tg = state.tags.find(x => x.id === tid);
    if (!tg) continue;
    (byType[tg.type_id] ||= []).push(tid);
  }
  const ids = new Set(p.tag_ids || []);
  for (const typeId in byType) {
    if (!byType[typeId].some(tid => ids.has(tid))) return false;
  }
  return true;
}

function applyTagFilter() {
  renderMediaList();
  rebuildTimeline();
  if (selectedMedia) {
    const p = state.media.find(x => x.name === selectedMedia);
    if (p && !photoMatchesTagFilter(p)) {
      selectedMedia = null;
      if (timeline.length) selectTimelineIndex(0);
    }
  }
  renderPhotoTags(state.media.find(x => x.name === selectedMedia));
  draw();
}

function renderTagTypesList() {
  const el = $("tagTypesList");
  el.innerHTML = "";
  for (const t of state.tag_types) {
    const row = document.createElement("div");
    row.className = "tt-row";
    row.style.borderColor = t.color;
    const header = document.createElement("div");
    header.className = "tt-header";
    header.innerHTML = `<span class="tt-title" style="color:${t.color}">${t.name}</span>`;
    const del = document.createElement("button");
    del.textContent = "Elimina tipologia";
    del.onclick = async () => {
      if (!confirm(`Eliminare la tipologia "${t.name}" e tutti i suoi tag?`)) return;
      await api("/tag_types/" + t.id, { method: "DELETE" });
      await loadState();
      renderTagTypesList();
      if (selectedMedia) selectMedia(selectedMedia);
    };
    header.appendChild(del);
    row.appendChild(header);
    const tagsOfType = state.tags.filter(tg => tg.type_id === t.id);
    const list = document.createElement("div");
    for (const tg of tagsOfType) {
      const chip = document.createElement("span");
      chip.className = "tag-chip";
      chip.style.borderColor = t.color;
      chip.innerHTML = `${tg.name}<span class="x">×</span>`;
      chip.querySelector(".x").onclick = async () => {
        if (!confirm(`Eliminare il tag "${tg.name}"?`)) return;
        await api("/tags/" + tg.id, { method: "DELETE" });
        await loadState();
        renderTagTypesList();
        if (selectedMedia) selectMedia(selectedMedia);
      };
      list.appendChild(chip);
    }
    row.appendChild(list);
    const addForm = document.createElement("div");
    addForm.style.marginTop = "6px";
    const inp = document.createElement("input");
    inp.type = "text"; inp.placeholder = "Nuovo tag";
    const btn = document.createElement("button");
    btn.textContent = "Aggiungi";
    btn.onclick = async () => {
      if (!inp.value.trim()) return;
      await api("/tags", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ type_id: t.id, name: inp.value.trim() }) });
      inp.value = "";
      await loadState();
      renderTagTypesList();
      if (selectedMedia) selectMedia(selectedMedia);
    };
    addForm.appendChild(inp); addForm.appendChild(btn);
    row.appendChild(addForm);
    el.appendChild(row);
  }
}

$("manageTags").onclick = () => { renderTagTypesList(); $("tagsModal").classList.remove("hidden"); };
$("closeTagsModal").onclick = () => $("tagsModal").classList.add("hidden");

// ----------------------- selezione + esportazione PDF -----------------------
$("btnSelectAll").onclick = () => {
  for (const p of currentFilteredMedia()) selectedForPdf.add(p.name);
  renderMediaList();
};
$("btnSelectNone").onclick = () => {
  selectedForPdf.clear();
  renderMediaList();
};

$("btnExportPdf").onclick = () => {
  if (selectedForPdf.size === 0) {
    alert("Seleziona almeno una foto (spunta le caselle nella lista).");
    return;
  }
  const placed = state.media.filter(p => selectedForPdf.has(p.name) && p.status === "placed").length;
  $("pdfModalInfo").textContent =
    `${selectedForPdf.size} foto selezionate · ${placed} con cono ottico sulla planimetria.`;
  $("pdfHeader").value = localStorage.getItem("wedge_pdf_header") || "";
  $("pdfFooter").value = localStorage.getItem("wedge_pdf_footer") || "";
  const savedSize = localStorage.getItem("wedge_pdf_size") || "A4";
  const sizeRadio = document.querySelector(`input[name="pdfSize"][value="${savedSize}"]`);
  if (sizeRadio) sizeRadio.checked = true;
  const savedOrient = localStorage.getItem("wedge_pdf_orient") || "portrait";
  const orientRadio = document.querySelector(`input[name="pdfOrient"][value="${savedOrient}"]`);
  if (orientRadio) orientRadio.checked = true;
  $("pdfModal").classList.remove("hidden");
};
$("pdfCancel").onclick = () => $("pdfModal").classList.add("hidden");

$("pdfGenerate").onclick = async () => {
  const page_size = document.querySelector('input[name="pdfSize"]:checked')?.value || "A4";
  const orientation = document.querySelector('input[name="pdfOrient"]:checked')?.value || "portrait";
  const header_text = $("pdfHeader").value;
  const footer_text = $("pdfFooter").value;
  localStorage.setItem("wedge_pdf_header", header_text);
  localStorage.setItem("wedge_pdf_footer", footer_text);
  localStorage.setItem("wedge_pdf_size", page_size);
  localStorage.setItem("wedge_pdf_orient", orientation);
  // ordina i nomi selezionati come compaiono nella lista (per data/nome)
  const ordered = state.media
    .filter(p => selectedForPdf.has(p.name))
    .slice()
    .sort((a, b) => (a.taken_at || "").localeCompare(b.taken_at || "") || a.name.localeCompare(b.name))
    .map(p => p.name);
  const btn = $("pdfGenerate");
  const old = btn.textContent;
  btn.disabled = true;
  btn.textContent = "Generazione…";
  try {
    const r = await api("/export_pdf", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ media_names: ordered, page_size, orientation, header_text, footer_text }),
    });
    if (!r.ok) { alert("Errore durante la generazione del PDF."); return; }
    const blob = await r.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${SLUG}-stampa.pdf`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    $("pdfModal").classList.add("hidden");
  } catch (e) {
    alert("Errore durante la generazione del PDF.");
  } finally {
    btn.disabled = false;
    btn.textContent = old;
  }
};
$("addType").onclick = async () => {
  const name = $("newTypeName").value.trim();
  const color = $("newTypeColor").value;
  if (!name) return;
  const r = await api("/tag_types", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, color }) });
  if (!r.ok) { alert("Errore (forse esiste già)"); return; }
  $("newTypeName").value = "";
  await loadState();
  renderTagTypesList();
  if (selectedMedia) selectMedia(selectedMedia);
};

$("btnRefresh").onclick = async () => {
  const before = new Set(state.media.map(p => p.name));
  await loadState();
  const added = state.media.filter(p => !before.has(p.name));
  if (added.length === 0) {
    $("status").textContent = "Nessun nuovo media trovato.";
  } else {
    $("status").textContent = `Trovati ${added.length} nuovi media.`;
    filter = "unplaced";
    $("filter").value = "unplaced";
    renderMediaList();
    selectMedia(added[0].name);
  }
};

$("btnShare").onclick = async () => {
  if (!selectedMedia) return;
  const base = location.href.split('?')[0].split('#')[0];
  const url = `${base}?media=${encodeURIComponent(selectedMedia)}`;
  const btn = $("btnShare");
  const orig = btn.textContent;
  try {
    await navigator.clipboard.writeText(url);
    btn.textContent = "Copiato!";
    setTimeout(() => { btn.textContent = orig; }, 1500);
  } catch (e) {
    prompt("Link di condivisione (Ctrl+C per copiare):", url);
  }
};

$("btnAddNote").onclick = async () => {
  if (!selectedMedia) return;
  const text = prompt("Testo nota:");
  if (text === null) return;
  const t = text.trim();
  if (!t) return;
  await api("/notes", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name: selectedMedia, text: t }),
  });
  await loadState();
  selectMedia(selectedMedia);
};

$("btnAddPin").onclick = () => {
  if (!selectedMedia) return;
  const p = state.media.find(x => x.name === selectedMedia);
  if (!p || p.kind !== "image") return;
  if (pinningNote) { cancelPinningMode(); return; }
  pinningNote = true;
  $("previewMedia").classList.add("pinning");
  $("btnAddPin").classList.add("active");
};

$("previewMedia").addEventListener("click", async (e) => {
  if (!pinningNote) return;
  const img = $("previewMedia").querySelector("img");
  if (!img) return;
  const rect = img.getBoundingClientRect();
  const x = (e.clientX - rect.left) / rect.width;
  const y = (e.clientY - rect.top) / rect.height;
  if (x < 0 || x > 1 || y < 0 || y > 1) return;
  cancelPinningMode();
  const text = prompt(`Testo nota (punto ${Math.round(x*100)}%, ${Math.round(y*100)}%):`);
  if (text === null) return;
  const t = text.trim();
  if (!t) return;
  await api("/notes", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name: selectedMedia, text: t, x, y }),
  });
  await loadState();
  selectMedia(selectedMedia);
});

(() => {
  const resizer = $("previewResizer");
  const appEl = $("app");
  const saved = localStorage.getItem("previewWidth");
  if (saved) appEl.style.gridTemplateColumns = `280px 1fr 6px ${saved}px`;
  let drag = false;
  resizer.addEventListener("mousedown", (e) => { drag = true; e.preventDefault(); document.body.style.userSelect = "none"; });
  window.addEventListener("mousemove", (e) => {
    if (!drag) return;
    const w = Math.min(Math.max(window.innerWidth - e.clientX, 120), window.innerWidth - 400);
    appEl.style.gridTemplateColumns = `280px 1fr 6px ${w}px`;
  });
  window.addEventListener("mouseup", () => {
    if (!drag) return;
    drag = false;
    document.body.style.userSelect = "";
    const cols = appEl.style.gridTemplateColumns.split(" ");
    const w = parseInt(cols[cols.length - 1]);
    if (w) localStorage.setItem("previewWidth", w);
  });
})();

loadState();
