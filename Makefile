avvia:
	sudo docker compose up -d

spegni:
	sudo docker compose down

rebuild-dopo-modifiche:
	sudo docker compose up -d --build