
# Miloš Mobile v2

Mobile Web-App für das persönliche Multi-Agent-Team.

## Was diese Version kann

- iPhone-freundliche Chat-Oberfläche
- Miloš als zentraler Einstieg
- Handoffs zu Mirjana, Milorad, Doktor Mladen, Scout, James Bond und Pinky
- Anzeige des aktuell antwortenden Agenten
- lokaler/persistenter Gesprächskontext über SQLite-Sessions
- API-Key bleibt serverseitig und wird NICHT im Browser gespeichert

## Lokal starten

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export OPENAI_API_KEY="DEIN_API_KEY"
uvicorn app:app --reload
```

Dann `http://127.0.0.1:8000` öffnen.

## Auf dem iPhone verwenden

Das iPhone selbst soll nicht der Python-Server sein.
Deploye diesen Ordner auf einen Python-fähigen Hostingdienst und hinterlege dort:

`OPENAI_API_KEY=...`

Danach öffnest du die HTTPS-Adresse in Safari.

### Zum Home-Bildschirm

Safari → Teilen → "Zum Home-Bildschirm"

Dann erscheint Miloš wie eine App auf dem iPhone.

## Sicherheit

- API-Key niemals in `index.html`, JavaScript oder GitHub veröffentlichen.
- Key nur als Secret/Environment Variable auf dem Server hinterlegen.
- Für eine öffentlich erreichbare Instanz später Login/Authentifizierung ergänzen.

## Nächste Ausbaustufe

- Projektakten
- Council-Modus
- echte Recherchetools für Scout
- strukturierte Handoff-Ereignisse statt nur End-Agent-Anzeige
- Sprache / Realtime
- Login
