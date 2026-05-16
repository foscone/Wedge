# Wedge

Webapp per posizionare un cono ottico (punto + direzione + FOV) — un "wedge"
sulla pianta — di ogni foto o video di una planimetria di edificio. Una sola
istanza può ospitare più progetti, ognuno con percorsi e password proprie.

## Funzionalità
- **Multi-progetto**: ogni progetto ha una cartella di foto/video e una di
  planimetrie indipendenti.
- **Due password per progetto** (nessun utente, solo password):
  - **visualizzazione** → consente di vedere foto, video e posizionamenti
  - **modifica** → consente anche di posizionare, taggare, gestire
- **Foto e video**: l'estensione determina il tipo. I video usano un singolo
  cono come le foto (in una versione futura supporteranno un percorso della
  camera con waypoint sulla planimetria).
- **Admin a livello istanza**: una password admin (env var) per creare,
  modificare ed eliminare progetti dalla pagina `/admin`.

## Avvio

1. Modifica `docker-compose.yml`:
   - imposta `ADMIN_PASSWORD` (password amministratore dell'istanza)
   - imposta `SECRET_KEY` con una stringa lunga, casuale e segreta (firma i
     cookie di sessione)
   - aggiungi i bind-mount delle cartelle di ogni progetto, ad esempio:
     ```yaml
     volumes:
       - ./data:/data
       - /percorso/host/casa-rossi/photos:/projects/casa-rossi/photos:ro
       - /percorso/host/casa-rossi/plans:/projects/casa-rossi/plans:ro
     ```
     (`:ro` se non vuoi che il container possa modificare i file originali)

2. `docker compose up -d --build`

3. Apri `http://host:8092/admin`, fai login con `ADMIN_PASSWORD` e crea il
   progetto inserendo i percorsi **come visti dentro al container** (es.
   `/projects/casa-rossi/photos`).

4. Dalla landing `/` clicca sul progetto, inserisci la password di
   visualizzazione o di modifica.

## Struttura
- `data/` — stato persistente (SQLite + thumbnail), montato come `/data`
- `app/` — codice FastAPI + frontend statico
- I percorsi delle foto/video e delle planimetrie di ogni progetto sono
  liberi: bastano i bind-mount nel docker-compose.

I file multimediali **non sono esposti direttamente sul filesystem web**: sono
serviti solo via API autenticata.

## Tipi di file supportati
- **Foto**: `.jpg .jpeg .png .webp .gif .tif .tiff .bmp`
- **Video**: `.mp4 .mov .webm .mkv .m4v .avi`
- **Planimetrie**: `.jpg .jpeg .png .webp .svg .gif`

Le thumbnail dei video sono generate con ffmpeg al primo accesso.

## Reverse proxy
Se servi sotto un sub-path (es. `/wedge/`), imposta `ROOT_PATH=/wedge`
nel `docker-compose.yml`. Esempio nginx:
```nginx
location /wedge/ {
    proxy_pass http://127.0.0.1:8092/;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    client_max_body_size 50m;
}
```

## Stati dei media
- `unplaced` — nuovo, da decidere
- `placed` — posizionato (plan + x + y + angle + fov)
- `skipped` — saltato di proposito

Aggiungere nuovi file nella cartella di un progetto li riporta automaticamente
in stato `unplaced` (vengono rilevati al refresh del progetto, da pulsante o
ricaricando la pagina).
