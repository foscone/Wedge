SHELL := /bin/bash

avvia:
	sudo docker compose up -d

spegni:
	sudo docker compose down

rebuild-dopo-modifiche:
	sudo docker compose up -d --build

# Elimina tutti i dati di un singolo progetto: riga DB (cascade su media, tag,
# media_tags, seen, tag_types) e thumbnail in data/thumbs/<id>/.
# I file originali sui bind-mount (photos_path / plans_path) NON vengono toccati.
# Uso: make elimina-progetto SLUG=nome-progetto
elimina-progetto:
	@if [ -z "$(SLUG)" ]; then \
		echo "Errore: specifica SLUG. Uso: make elimina-progetto SLUG=nome-progetto"; \
		exit 1; \
	fi
	@echo ""
	@echo "ATTENZIONE: stai per cancellare TUTTI i dati del progetto '$(SLUG)':"
	@echo "  - riga in data/wedge.db (con cascade su media, tag, ecc.)"
	@echo "  - data/thumbs/<id_progetto>/ (thumbnail generate)"
	@echo "I file originali sui bind-mount NON vengono toccati."
	@echo ""
	@read -p "Per confermare, digita il nome del progetto: " CONFIRM; \
	if [ "$$CONFIRM" != "$(SLUG)" ]; then \
		echo "Annullato."; \
		exit 1; \
	fi
	@sudo python3 -c "import sqlite3, shutil, sys; \
db = sqlite3.connect('data/wedge.db'); \
db.execute('PRAGMA foreign_keys = ON'); \
row = db.execute('SELECT id FROM projects WHERE slug=?', ('$(SLUG)',)).fetchone() or sys.exit('Progetto $(SLUG) non trovato.'); \
pid = row[0]; \
db.execute('DELETE FROM projects WHERE id=?', (pid,)); \
db.commit(); \
shutil.rmtree(f'data/thumbs/{pid}', ignore_errors=True); \
print(f'Progetto $(SLUG) eliminato (id={pid}).')"

# Elimina TUTTI i dati del portale Wedge: data/wedge.db e data/thumbs/.
# Ferma il container, cancella i dati e lo riavvia (il DB viene ricreato vuoto).
# I file originali sui bind-mount NON vengono toccati.
elimina-tutto:
	@echo ""
	@echo "ATTENZIONE: stai per cancellare TUTTI i dati del portale Wedge:"
	@echo "  - data/wedge.db (tutti i progetti, password, tag, posizionamenti)"
	@echo "  - data/thumbs/ (tutte le thumbnail)"
	@echo "I file originali sui bind-mount NON vengono toccati."
	@echo ""
	@read -p "Per confermare, digita 'CANCELLA TUTTO': " CONFIRM; \
	if [ "$$CONFIRM" != "CANCELLA TUTTO" ]; then \
		echo "Annullato."; \
		exit 1; \
	fi
	sudo docker compose down
	sudo rm -f data/wedge.db
	sudo rm -rf data/thumbs
	sudo docker compose up -d
	@echo "Portale resettato. DB ricreato vuoto al boot."
