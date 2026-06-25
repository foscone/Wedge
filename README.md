# Wedge

[Italiano](#italiano) · [English](#english)

---

## Italiano

Webapp per posizionare un cono ottico (punto + direzione + FOV) — un "wedge"
sulla pianta — di ogni foto o video di una planimetria di edificio. Una sola
istanza può ospitare più progetti, ognuno con percorsi e password proprie.

### Funzionalità
- **Multi-progetto**: ogni progetto ha una cartella di foto/video e una di
  planimetrie indipendenti.
- **Due password per progetto** (nessun utente, solo password):
  - **visualizzazione** → consente di vedere foto, video e posizionamenti
  - **modifica** → consente anche di posizionare, taggare, annotare, gestire
- **Foto e video**: l'estensione determina il tipo. I video usano un singolo
  cono come le foto (in una versione futura supporteranno un percorso della
  camera con waypoint sulla planimetria).
- **Admin a livello istanza**: una password admin (env var) per creare,
  modificare ed eliminare progetti dalla pagina `/admin`.
- **Note sulle foto**: testo libero, generico oppure legato a un punto
  preciso della foto (pin sull'immagine).

### Avvio

1. Copia `.env.example` in `.env` e imposta:
   - `ADMIN_PASSWORD` — password amministratore dell'istanza
   - `SECRET_KEY` — stringa lunga, casuale e segreta (firma i cookie di sessione).
     Generala con: `python3 -c "import secrets; print(secrets.token_urlsafe(48))"`

2. Aggiungi i bind-mount dei progetti in `docker-compose.override.yml`
   (copialo da `docker-compose.override.yml.example`; è gitignorato, così
   locale e produzione hanno mount diversi senza conflitti). Per ogni
   progetto monti **due cartelle host indipendenti** dentro `/projects/<nome>`:
   le foto sotto `photos/` e le planimetrie sotto `plans/`. Puoi quindi usare
   la cartella foto che hai già nel tuo archivio e una cartella planimetrie
   creata apposta, anche in punti diversi del disco.
   ```yaml
   services:
     wedge:
       volumes:
         - /mnt/archivio/CasaRossi/Foto:/projects/casa-rossi/photos:ro
         - /mnt/wedge-planimetrie/casa-rossi:/projects/casa-rossi/plans:ro
   ```
   **Monta sempre in sola lettura con `:ro`.** Wedge non scrive mai in queste
   cartelle (legge solo i file e gli EXIF; le thumbnail le genera in
   `/data/thumbs`), e `:ro` lo garantisce anche a livello di sistema: le tue
   cartelle di lavoro dell'archivio non possono essere modificate o manomesse.

3. `docker compose up -d --build` (o `make avvia`)

4. Apri `http://host:8092/admin`, fai login con `ADMIN_PASSWORD`, poi
   crea il progetto: il campo **Cartella progetto** è un menù a tendina
   con tutte le cartelle montate sotto `/projects/` che hanno le
   sottocartelle `photos/` e `plans/`.

5. Dalla landing `/` clicca sul progetto, inserisci la password di
   visualizzazione o di modifica.

### Struttura
- `data/` — stato persistente (SQLite + thumbnail), montato come `/data`
- `app/` — codice FastAPI + frontend statico
- I percorsi delle foto/video e delle planimetrie di ogni progetto sono
  liberi: bastano i bind-mount nel docker-compose.

I file multimediali **non sono esposti direttamente sul filesystem web**: sono
serviti solo via API autenticata.

### Tipi di file supportati
- **Foto**: `.jpg .jpeg .png .webp .gif .tif .tiff .bmp`
- **Video**: `.mp4 .mov .webm .mkv .m4v .avi`
- **Planimetrie**: `.jpg .jpeg .png .webp .svg .gif .pdf` (i PDF vengono
  rasterizzati automaticamente: viene usata la prima pagina)

Le thumbnail dei video sono generate con ffmpeg al primo accesso.

### Reverse proxy

Per esporre Wedge su un dominio dedicato via **Nginx Proxy Manager** vedi
[`docs/nginx-proxy-manager.md`](docs/nginx-proxy-manager.md).

Se invece servi sotto un sub-path (es. `/wedge/`), imposta `ROOT_PATH=/wedge`
nel file `.env`. Esempio nginx vanilla:
```nginx
location /wedge/ {
    proxy_pass http://127.0.0.1:8092/;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    client_max_body_size 50m;
}
```

### Stati dei media
- `unplaced` — nuovo, da decidere
- `placed` — posizionato (plan + x + y + angle + fov)
- `skipped` — saltato di proposito

Aggiungere nuovi file nella cartella di un progetto li riporta automaticamente
in stato `unplaced` (vengono rilevati al refresh del progetto, da pulsante o
ricaricando la pagina).

### Manutenzione

Il `Makefile` espone alcuni comandi utili:
- `make avvia` / `make spegni` — avvio / spegnimento container
- `make rebuild-dopo-modifiche` — rebuild dopo modifiche al codice
- `make elimina-progetto SLUG=nome-progetto` — cancella tutti i dati di un
  singolo progetto (riga DB con cascade + thumbnail); i file originali sui
  bind-mount NON vengono toccati
- `make elimina-tutto` — cancella TUTTI i dati del portale (DB + thumbnail)
  e riavvia il container con DB vuoto

### Licenza

Wedge è distribuito sotto licenza **GNU Affero General Public License v3.0**
(AGPL-3.0). Vedi il file [LICENSE](LICENSE) per il testo completo.

In sintesi:
- Puoi usare, studiare, modificare e ridistribuire il codice.
- Le opere derivate **devono** essere distribuite con la stessa licenza
  AGPL-3.0.
- Se ospiti una versione modificata come servizio web accessibile a terzi,
  **devi** rendere disponibile il codice sorgente delle tue modifiche agli
  utenti del servizio.
- Devi mantenere le note di copyright e di attribuzione esistenti.

Copyright (C) 2026 Fosco Ventura (GitHub: [@foscone](https://github.com/foscone))

---

## English

Web app to place an optical cone (point + direction + FOV) — a "wedge" on the
floor plan — for every photo or video taken inside a building. A single
instance can host multiple projects, each with its own paths and passwords.

### Features
- **Multi-project**: each project has its own photos/videos folder and its
  own plans folder.
- **Two passwords per project** (no users, only passwords):
  - **view** → see photos, videos, and placements
  - **edit** → also place, tag, annotate, and manage
- **Photos and videos**: the file extension determines the type. Videos use
  a single cone like photos (a future version will support a camera path
  with waypoints on the plan).
- **Instance-level admin**: an admin password (env var) lets you create,
  edit, and delete projects from the `/admin` page.
- **Photo notes**: free-text notes on photos, either generic to the photo
  or pinned to a specific point of the image.

### Setup

1. Copy `.env.example` to `.env` and set:
   - `ADMIN_PASSWORD` — instance admin password
   - `SECRET_KEY` — a long, random, secret string (signs session cookies).
     Generate one with: `python3 -c "import secrets; print(secrets.token_urlsafe(48))"`

2. Add the project bind-mounts in `docker-compose.override.yml` (copy it from
   `docker-compose.override.yml.example`; it is gitignored, so local and
   production can mount different folders without conflicts). For each project
   mount **two independent host folders** under `/projects/<name>`: the photos
   under `photos/` and the plans under `plans/`. You can reuse the photo folder
   you already have in your archive and a plans folder made on purpose, even in
   different places on disk.
   ```yaml
   services:
     wedge:
       volumes:
         - /mnt/archive/CasaRossi/Photos:/projects/casa-rossi/photos:ro
         - /mnt/wedge-plans/casa-rossi:/projects/casa-rossi/plans:ro
   ```
   **Always mount read-only with `:ro`.** Wedge never writes to these folders
   (it only reads the files and EXIF; thumbnails go to `/data/thumbs`), and
   `:ro` guarantees this at the OS level too: your archive working folders
   cannot be modified or tampered with.

3. `docker compose up -d --build` (or `make avvia`)

4. Open `http://host:8092/admin`, log in with `ADMIN_PASSWORD`, then
   create a project: the **Cartella progetto** field is a drop-down listing
   every folder mounted under `/projects/` that contains the required
   `photos/` and `plans/` subfolders.

5. From the landing page `/` click the project and enter the view or edit
   password.

### Layout
- `data/` — persistent state (SQLite + thumbnails), mounted as `/data`
- `app/` — FastAPI code + static frontend
- Photo/video and plan paths for each project are arbitrary: just bind-mount
  them in docker-compose.

Media files are **not exposed directly on the web filesystem**: they are
only served through the authenticated API.

### Supported file types
- **Photos**: `.jpg .jpeg .png .webp .gif .tif .tiff .bmp`
- **Videos**: `.mp4 .mov .webm .mkv .m4v .avi`
- **Plans**: `.jpg .jpeg .png .webp .svg .gif .pdf` (PDFs are rasterized
  automatically: the first page is used)

Video thumbnails are generated with ffmpeg on first access.

### Reverse proxy

To expose Wedge on a dedicated domain via **Nginx Proxy Manager** see
[`docs/nginx-proxy-manager.md`](docs/nginx-proxy-manager.md).

For sub-path mounting (e.g., `/wedge/`), set `ROOT_PATH=/wedge` in the
`.env` file. Vanilla nginx example:
```nginx
location /wedge/ {
    proxy_pass http://127.0.0.1:8092/;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    client_max_body_size 50m;
}
```

### Media states
- `unplaced` — new, awaiting a decision
- `placed` — placed (plan + x + y + angle + fov)
- `skipped` — intentionally skipped

Adding new files to a project's folder automatically marks them as `unplaced`
(they are detected on project refresh, either via the button or by reloading
the page).

### Maintenance

The `Makefile` exposes a few helpers:
- `make avvia` / `make spegni` — start / stop the container
- `make rebuild-dopo-modifiche` — rebuild after code changes
- `make elimina-progetto SLUG=project-slug` — wipe all data for a single
  project (DB row with cascade + thumbnails); source files on bind-mounts
  are NOT touched
- `make elimina-tutto` — wipe ALL portal data (DB + thumbnails) and restart
  the container with an empty DB

### License

Wedge is distributed under the **GNU Affero General Public License v3.0**
(AGPL-3.0). See the [LICENSE](LICENSE) file for the full text.

In short:
- You can use, study, modify, and redistribute the code.
- Derivative works **must** be distributed under the same AGPL-3.0 license.
- If you host a modified version as a network-accessible service, you
  **must** make the source code of your modifications available to the
  service's users.
- You must preserve existing copyright and attribution notices.

Copyright (C) 2026 Fosco Ventura (GitHub: [@foscone](https://github.com/foscone))
