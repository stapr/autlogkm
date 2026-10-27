# autlogkm – Tesla kilometerregistratie via Apple Shortcut

Legt per rit de odometerstand van de Tesla vast bij **openen** en bij **sluiten**,
en berekent de afstand. De iPhone geeft het signaal, een klein Python-script
leest de odometer uit via de Tesla Fleet API.

```
iPhone Shortcut ──HTTP──▶ tesla_km.py serve ──Fleet API──▶ Tesla (odometer)
                                  └──▶ ritten.csv (start, eind, afstand)
```

## 1. Installatie

```bash
pip install -r requirements.txt
cp .env.example .env      # vul client id/secret, redirect-uri, VIN en WEBHOOK_TOKEN in
```

`WEBHOOK_TOKEN` is een eigen lang willekeurig geheim, bijvoorbeeld
`python -c "import secrets; print(secrets.token_urlsafe(32))"`.

De publieke sleutel staat al in `.well-known/appspecific/com.tesla.3p.public-key.pem`
(dit is wat Tesla bij de Fleet API-registratie opvraagt).

## 2. Eenmalig registreren en inloggen bij Tesla

Zet `TESLA_DOMEIN` in `.env` (het domein waarop de publieke sleutel bereikbaar is, zonder `https://`).

```bash
python tesla_km.py register        # domein registreren bij Tesla (EU-regio)
python tesla_km.py auth-url        # open de link, log in, geef toestemming
python tesla_km.py auth-code <code uit de redirect-url>
```

**Let op bij "redirect_uri is not registered":** in de Tesla-portal (Nederlandstalig) wordt de OAuth-redirect
gecontroleerd tegen **Toegestane doorlink-URI('s)**, niet tegen *Toegestane retour-URL('s)*. Zet
`TESLA_REDIRECT_URI` (bijv. `https://stapr.github.io/callback`) in het veld *doorlink-URI* en
zorg dat *Type OAuth Grant* `authorization-code` bevat. `register` werkt ook zonder dit, dus
een geslaagde `register` bewijst niet dat de redirect goed staat.

Tokens komen in `tokens.json` (niet in git). Het script ververst ze zelf; Tesla-refresh-tokens
zijn eenmalig bruikbaar, dus laat `tokens.json` schrijfbaar.

Test daarna direct:

```bash
python tesla_km.py open
python tesla_km.py close
python tesla_km.py report
```

## 3. Webhook draaien

```bash
python tesla_km.py serve           # luistert op PORT (standaard 8080)
```

Het moet vanaf je iPhone bereikbaar zijn (kleine VPS, thuisserver met Tailscale of
Cloudflare Tunnel). Zet er HTTPS voor als het publiek bereikbaar is.

| Pad       | Doet                                             |
|-----------|--------------------------------------------------|
| `/open`   | leest odometer, start een nieuwe rit             |
| `/close`  | leest odometer, sluit de laatste open rit        |
| `/report` | totaal en per maand (`?maand=2026-10` optioneel) |

Elke aanroep heeft `?token=<WEBHOOK_TOKEN>` of header `X-Token` nodig.

## 4. Apple Shortcuts

Maak twee persoonlijke automatiseringen (Opdrachten ▸ Automatisering ▸ Nieuwe automatisering):

| Automatisering | Trigger (kies één type)                                  | Actie                                  |
|----------------|----------------------------------------------------------|----------------------------------------|
| Tesla open     | Bluetooth/CarPlay **verbonden** met de Tesla             | *Haal inhoud van URL op*: `…/open?token=…`  |
| Tesla gesloten | Bluetooth/CarPlay **verbroken** van de Tesla             | *Haal inhoud van URL op*: `…/close?token=…` |

Zet “Vraag voor uitvoeren” uit en “Geef melding bij uitvoeren” naar wens aan.

Let op: iOS kan niet zien of de auto vergrendeld of ontgrendeld wordt. Bluetooth/CarPlay
verbinden en verbreken is de dichtstbijzijnde betrouwbare trigger. Alternatief: een NFC-tag in
de auto, of de Shortcut handmatig starten.

## Gedrag en randgevallen

- Slaapt de auto (HTTP 408), dan wordt hij wakker gemaakt en wordt tot 60 s gewacht.
- `/close` zonder open rit maakt een rij met alleen een eindstand.
- Twee keer `/open` achter elkaar laat de eerste rit onvolledig; zichtbaar als `onvolledig` in het rapport.
- Odometer komt van Tesla in mijlen en wordt omgerekend naar km (1 mi = 1,609344 km).
- `ritten.csv` opent direct in Excel/Google Sheets voor de administratie.

## Draaien op een eigen server (Ubuntu, bijv. Proxmox VM of LXC)

Een server die altijd aan staat is betrouwbaarder dan een laptop. Dit werkt op elke Ubuntu/Debian-machine.

1. **Tailscale installeren en aanmelden** op de server, zodat de iPhone erbij kan zonder poort open te zetten:
   ```bash
   curl -fsSL https://tailscale.com/install.sh | sh
   sudo tailscale up
   ```
   Noteer de naam of het `100.x.y.z`-adres in de Tailscale-app.
2. **Repo klonen en installeren:**
   ```bash
   git clone https://github.com/stapr/autlogkm.git && cd autlogkm
   sudo bash deploy/install.sh
   ```
3. **Instellingen overbrengen** (vanaf de Mac, waar je al ingelogd bent):
   ```bash
   scp .env tokens.json <gebruiker>@<server>:/tmp/
   ssh <gebruiker>@<server> 'sudo mv /tmp/.env /tmp/tokens.json /opt/autlogkm/ && \
     sudo chown teslakm:teslakm /opt/autlogkm/.env /opt/autlogkm/tokens.json && \
     sudo chmod 600 /opt/autlogkm/.env /opt/autlogkm/tokens.json'
   ```
   **Gebruik daarna `tokens.json` maar op één plek.** Tesla-refresh-tokens zijn eenmalig: draait het script
   ook nog op de Mac, dan maakt de ene kopie de andere ongeldig. Draai daarna alleen nog op de server.
4. **Starten en controleren:**
   ```bash
   sudo systemctl enable --now tesla-km
   systemctl status tesla-km
   journalctl -u tesla-km -f
   curl "http://localhost:8080/report?token=<WEBHOOK_TOKEN>"
   ```
5. **Shortcuts** wijzen naar `http://<tailscale-naam>:8080/open?token=…` en `/close?token=…`.

Ritten staan in `/opt/autlogkm/ritten.csv`. Maak een back-up via een Proxmox-snapshot of kopieer het bestand regelmatig.

### Als de server even niet bereikbaar is
Een mislukte aanroep betekent een gemiste meting. Zet daarom in elke Shortcut na *Haal inhoud van URL op* een
*Als*-stap: als het resultaat leeg is of `fout` bevat, toon dan een melding ("Tesla-km niet gelogd").
Zo weet je op het moment zelf dat je de stand handmatig moet noteren. Een `/close` zonder `/open`
levert een rit zonder begin op en staat als `onvolledig` in het rapport.
