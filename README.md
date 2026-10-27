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
