# Wedge dietro Nginx Proxy Manager

[Italiano](#italiano) · [English](#english)

---

## Italiano

Guida per esporre Wedge su un dominio dedicato (es. `wedge.tuodominio.it`)
tramite [Nginx Proxy Manager](https://nginxproxymanager.com/) (NPM), con
certificato Let's Encrypt automatico.

### Prerequisiti

- Wedge è in esecuzione (`make avvia`) e risponde su `http://localhost:8092`.
- NPM è installato e accessibile sulla sua interfaccia web (di default su
  porta 81).
- Il dominio `wedge.tuodominio.it` punta (record A o AAAA) all'IP del
  server dove gira NPM.
- Le porte 80 e 443 del server sono raggiungibili da internet (necessarie
  per la sfida HTTP di Let's Encrypt e per il traffico HTTPS).

### Scenario A — NPM e Wedge sulla stessa macchina, reti separate

È il setup più semplice: NPM raggiunge Wedge tramite la porta esposta
sull'host (`8092`).

1. In NPM, vai su **Hosts → Proxy Hosts → Add Proxy Host**.

2. Scheda **Details**:
   - **Domain Names**: `wedge.tuodominio.it`
   - **Scheme**: `http`
   - **Forward Hostname / IP**:
     - se NPM gira in Docker: l'IP del bridge Docker dell'host
       (di solito `172.17.0.1`), oppure l'IP LAN del server
     - se NPM gira nativo sull'host: `127.0.0.1`
   - **Forward Port**: `8092`
   - **Cache Assets**: OFF (l'app gestisce il caching da sola)
   - **Block Common Exploits**: ON
   - **Websockets Support**: OFF (Wedge non usa websocket)

3. Scheda **SSL**:
   - **SSL Certificate**: `Request a new SSL Certificate`
   - **Force SSL**: ON
   - **HTTP/2 Support**: ON
   - **HSTS Enabled**: ON (opzionale, dopo aver verificato che tutto funziona)
   - Accetta i termini Let's Encrypt e inserisci l'email.

4. **Save**. Dopo qualche secondo il certificato è emesso e
   `https://wedge.tuodominio.it` apre Wedge.

### Scenario B — NPM e Wedge sulla stessa rete Docker (consigliato)

Più sicuro: la porta `8092` non serve esposta sull'host, NPM raggiunge
Wedge direttamente via rete interna Docker.

1. Crea una rete Docker condivisa (se non esiste già):
   ```bash
   docker network create proxy
   ```

2. Aggiungi NPM a quella rete (nel suo `docker-compose.yml`):
   ```yaml
   services:
     npm:
       # ...
       networks:
         - proxy
   networks:
     proxy:
       external: true
   ```

3. Aggiungi Wedge alla stessa rete (in [docker-compose.yml](../docker-compose.yml)):
   ```yaml
   services:
     wedge:
       # ...
       networks:
         - default
         - proxy
   networks:
     proxy:
       external: true
   ```

4. Riavvia entrambi: `docker compose up -d` su entrambi i progetti.
   A questo punto puoi anche rimuovere la riga `ports: - "8092:8000"` da
   Wedge se non ti serve l'accesso diretto in LAN.

5. In NPM, **Proxy Host**:
   - **Forward Hostname / IP**: `wedge` (il `container_name`)
   - **Forward Port**: `8000` (porta interna del container, vedi `Dockerfile`)
   - Tutto il resto come nello Scenario A.

### Variabili d'ambiente di Wedge

Quando Wedge sta dietro a un reverse proxy:

- **`ROOT_PATH`** deve restare vuoto se usi un dominio dedicato (es.
  `wedge.tuodominio.it`). Impostalo (es. `/wedge`) solo se servi sotto
  sub-path (es. `tuodominio.it/wedge/`).
- Il container già parte con `--proxy-headers` e
  `--forwarded-allow-ips=*` (vedi [Dockerfile](../Dockerfile)), quindi
  riconosce gli header `X-Forwarded-*` di NPM senza ulteriori
  configurazioni.

### Note su upload e streaming

- Wedge **non** ha endpoint di upload via web: foto, video e planimetrie
  arrivano dai bind-mount nel `docker-compose.yml`. Quindi
  `client_max_body_size` di NPM non è critico.
- I video vengono serviti con HTTP Range Requests (streaming). NPM li
  inoltra correttamente con la configurazione di default. Se noti che i
  video grandi non partono o si bloccano, vai sulla scheda **Advanced**
  del Proxy Host e aggiungi:
  ```nginx
  proxy_buffering off;
  proxy_request_buffering off;
  ```

### Troubleshooting

- **502 Bad Gateway**: NPM non riesce a raggiungere Wedge. Verifica con
  `docker exec -it nginx-proxy-manager curl http://wedge:8000/` (Scenario B)
  o `curl http://172.17.0.1:8092/` (Scenario A).
- **Login con cookie non funziona**: il container Wedge si aspetta
  `X-Forwarded-Proto: https`. NPM lo invia di default; se hai disabilitato
  "Force SSL", abilitalo.
- **CSS/JS rotti dopo aver impostato un sub-path**: hai messo
  `ROOT_PATH=/wedge` ma stai accedendo via dominio dedicato. Riportalo a
  stringa vuota in `.env` e ricarica il container.

---

## English

Guide to expose Wedge on a dedicated domain (e.g. `wedge.example.com`)
through [Nginx Proxy Manager](https://nginxproxymanager.com/) (NPM), with
automatic Let's Encrypt certificate.

### Prerequisites

- Wedge is running (`make avvia`) and responds at `http://localhost:8092`.
- NPM is installed and reachable on its admin UI (default port 81).
- The domain `wedge.example.com` points (A or AAAA record) to the IP of
  the host where NPM runs.
- Ports 80 and 443 on the host are reachable from the internet (required
  for Let's Encrypt HTTP challenge and HTTPS traffic).

### Scenario A — NPM and Wedge on the same host, separate networks

Simplest setup: NPM reaches Wedge through the port published on the host
(`8092`).

1. In NPM, go to **Hosts → Proxy Hosts → Add Proxy Host**.

2. **Details** tab:
   - **Domain Names**: `wedge.example.com`
   - **Scheme**: `http`
   - **Forward Hostname / IP**:
     - if NPM runs in Docker: the host's Docker bridge IP
       (usually `172.17.0.1`), or the server's LAN IP
     - if NPM runs natively on the host: `127.0.0.1`
   - **Forward Port**: `8092`
   - **Cache Assets**: OFF (the app handles caching itself)
   - **Block Common Exploits**: ON
   - **Websockets Support**: OFF (Wedge does not use websockets)

3. **SSL** tab:
   - **SSL Certificate**: `Request a new SSL Certificate`
   - **Force SSL**: ON
   - **HTTP/2 Support**: ON
   - **HSTS Enabled**: ON (optional, after verifying everything works)
   - Accept the Let's Encrypt terms and enter an email.

4. **Save**. After a few seconds the certificate is issued and
   `https://wedge.example.com` opens Wedge.

### Scenario B — NPM and Wedge on the same Docker network (recommended)

More secure: port `8092` does not need to be published on the host; NPM
reaches Wedge directly via the internal Docker network.

1. Create a shared Docker network (if you don't already have one):
   ```bash
   docker network create proxy
   ```

2. Add NPM to that network (in its `docker-compose.yml`):
   ```yaml
   services:
     npm:
       # ...
       networks:
         - proxy
   networks:
     proxy:
       external: true
   ```

3. Add Wedge to the same network (in [docker-compose.yml](../docker-compose.yml)):
   ```yaml
   services:
     wedge:
       # ...
       networks:
         - default
         - proxy
   networks:
     proxy:
       external: true
   ```

4. Restart both: `docker compose up -d` on each project. At this point
   you can also remove the `ports: - "8092:8000"` line from Wedge if you
   no longer need direct LAN access.

5. In NPM, **Proxy Host**:
   - **Forward Hostname / IP**: `wedge` (the `container_name`)
   - **Forward Port**: `8000` (the container's internal port — see `Dockerfile`)
   - Everything else as in Scenario A.

### Wedge environment variables

When Wedge is behind a reverse proxy:

- **`ROOT_PATH`** must stay empty when using a dedicated domain
  (e.g., `wedge.example.com`). Set it (e.g. `/wedge`) only if you serve
  under a sub-path (e.g. `example.com/wedge/`).
- The container already starts with `--proxy-headers` and
  `--forwarded-allow-ips=*` (see [Dockerfile](../Dockerfile)), so it
  honours NPM's `X-Forwarded-*` headers with no extra configuration.

### Notes on uploads and streaming

- Wedge has **no** web upload endpoint: photos, videos and plans come
  from bind-mounts declared in `docker-compose.yml`. So NPM's
  `client_max_body_size` is not critical.
- Videos are served using HTTP Range Requests (streaming). NPM forwards
  them correctly with the default configuration. If you notice that
  large videos won't start or stall, open the **Advanced** tab of the
  Proxy Host and add:
  ```nginx
  proxy_buffering off;
  proxy_request_buffering off;
  ```

### Troubleshooting

- **502 Bad Gateway**: NPM cannot reach Wedge. Test with
  `docker exec -it nginx-proxy-manager curl http://wedge:8000/`
  (Scenario B) or `curl http://172.17.0.1:8092/` (Scenario A).
- **Login cookies don't stick**: the Wedge container expects
  `X-Forwarded-Proto: https`. NPM sends it by default; if you disabled
  "Force SSL", turn it back on.
- **Broken CSS/JS after configuring a sub-path**: you set
  `ROOT_PATH=/wedge` but you're accessing via a dedicated domain. Set
  it back to an empty string in `.env` and recreate the container.
