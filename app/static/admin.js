const $ = (id) => document.getElementById(id);

async function refreshSession() {
  const r = await fetch("/api/session");
  const data = await r.json();
  if (data.admin) {
    $("loginSection").classList.add("hidden");
    $("manageSection").classList.remove("hidden");
    $("btnLogout").classList.remove("hidden");
    await loadProjects();
  } else {
    $("loginSection").classList.remove("hidden");
    $("manageSection").classList.add("hidden");
    $("btnLogout").classList.add("hidden");
  }
}

async function loadProjects() {
  const r = await fetch("/api/admin/projects");
  if (!r.ok) {
    $("projects").textContent = "Errore di caricamento.";
    return;
  }
  const projects = await r.json();
  const el = $("projects");
  el.innerHTML = "";
  if (!projects.length) {
    el.innerHTML = '<div class="muted">Ancora nessun progetto.</div>';
    return;
  }
  for (const p of projects) {
    const card = document.createElement("div");
    card.className = "admin-card";
    card.innerHTML = `
      <div class="admin-card-head">
        <div>
          <div class="project-name">${p.name}</div>
          <div class="project-slug muted">${p.slug}</div>
        </div>
        <div>
          <button data-act="edit">Modifica</button>
          <button data-act="del" class="danger">Elimina</button>
        </div>
      </div>
      <div class="admin-card-body muted">
        <div>📷 ${p.photos_path}</div>
        <div>🗺️ ${p.plans_path}</div>
      </div>
      <div class="admin-card-edit hidden">
        <label>Nome <input data-f="name" value="${p.name}"></label>
        <label>Percorso foto/video <input data-f="photos_path" value="${p.photos_path}"></label>
        <label>Percorso planimetrie <input data-f="plans_path" value="${p.plans_path}"></label>
        <label>Nuova password visualizzazione (vuoto = invariata) <input data-f="view_password" type="text" autocomplete="off"></label>
        <label>Nuova password modifica (vuoto = invariata) <input data-f="edit_password" type="text" autocomplete="off"></label>
        <div style="display:flex;gap:8px;margin-top:6px">
          <button data-act="save">Salva</button>
          <button data-act="cancel">Annulla</button>
        </div>
        <div class="error hidden" data-err></div>
      </div>
    `;
    const editBox = card.querySelector(".admin-card-edit");
    const errBox = card.querySelector("[data-err]");
    card.querySelector('[data-act="edit"]').onclick = () => editBox.classList.toggle("hidden");
    card.querySelector('[data-act="cancel"]').onclick = () => editBox.classList.add("hidden");
    card.querySelector('[data-act="del"]').onclick = async () => {
      if (!confirm(`Eliminare definitivamente il progetto "${p.name}"? I file sul filesystem restano intatti, ma posizionamenti e tag andranno persi.`)) return;
      const r = await fetch("/api/admin/projects/" + encodeURIComponent(p.slug), { method: "DELETE" });
      if (r.ok) loadProjects();
      else alert("Errore eliminazione");
    };
    card.querySelector('[data-act="save"]').onclick = async () => {
      errBox.classList.add("hidden");
      const payload = {};
      for (const f of editBox.querySelectorAll("[data-f]")) {
        const v = f.value.trim();
        if (v) payload[f.dataset.f] = v;
      }
      const r = await fetch("/api/admin/projects/" + encodeURIComponent(p.slug), {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (r.ok) {
        loadProjects();
      } else {
        const txt = await r.text();
        errBox.textContent = "Errore: " + txt;
        errBox.classList.remove("hidden");
      }
    };
    el.appendChild(card);
  }
}

$("loginForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  $("loginErr").classList.add("hidden");
  const password = $("adminPw").value;
  const r = await fetch("/api/admin/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ password }),
  });
  if (r.ok) {
    refreshSession();
  } else {
    $("loginErr").textContent = "Password errata.";
    $("loginErr").classList.remove("hidden");
  }
});

$("btnLogout").addEventListener("click", async () => {
  await fetch("/api/admin/logout", { method: "POST" });
  refreshSession();
});

$("createForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  $("createErr").classList.add("hidden");
  $("createOk").classList.add("hidden");
  const payload = {
    slug: $("newSlug").value.trim(),
    name: $("newName").value.trim(),
    photos_path: $("newPhotos").value.trim(),
    plans_path: $("newPlans").value.trim(),
    view_password: $("newViewPw").value,
    edit_password: $("newEditPw").value,
  };
  const r = await fetch("/api/admin/projects", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (r.ok) {
    $("createOk").textContent = "Progetto creato.";
    $("createOk").classList.remove("hidden");
    $("createForm").reset();
    loadProjects();
  } else {
    const txt = await r.text();
    $("createErr").textContent = "Errore: " + txt;
    $("createErr").classList.remove("hidden");
  }
});

refreshSession();
