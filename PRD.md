# PRD — Gamified Trader (Trading-Lern-App)

> Stand: v0.2 vom 2026-09-21. v0.1 wurde aus der diktierten Produktbeschreibung erstellt und per
> grill-me verfeinert; die Entscheidungen stehen in §5. Release 1 (M1–M6) ist umsetzungsreif.
> M7–M9 sind vorläufig: vor M7 folgt eine eigene PRD-Iteration mit den offenen Punkten A19 und A20.
> Phasenstand: [IMPLEMENTATION.md](IMPLEMENTATION.md).

## 1. Problem & goal

Chartanalyse und Risikomanagement lernt man heute entweder mit echtem Geld (teuer) oder mit
Lehrbuchwissen ohne Rückmeldung (folgenlos). Die App schließt diese Lücke: Nutzer treffen auf
echten, anonymisierten historischen Tagescharts eine Kauf- oder Warte-Entscheidung, sehen sofort
den tatsächlichen Verlauf und erhalten Punkte sowie ein simuliertes Guthaben, das Fehlentscheidungen,
Kosten und Hebel spürbar macht. Gelöst ist das Problem, wenn ein Nutzer nach jeder Runde
nachvollziehen kann, welche Signale zu welchem Setup geführt hätten, und seine Trefferquote über
die Runden messbar steigt.

### Modi

| Modus | Zweck | Umfang |
|---|---|---|
| Spielmodus | Historischer Chart ohne Ticker, 1 von 6 Optionen wählen, Auflösung mit Punkten und Buchung | Release 1: M1–M4, M6 |
| Setup-/Maintenance-Modus | Nutzer, Startkapital, Reset, Hebel, Zins- und Gebührensatz | Release 1: M5 |
| Entdeckungsmodus | Beliebige Yahoo-Aktie, aktueller Chart, ML-gestützte Empfehlung (Horizont, Hebel) | Release 2: M7–M8 (vorläufig) |
| Lernmodus | Signalwissen, interaktives Setup-Labor, Feature Importance des Modells | Release 3: M9 (vorläufig) |

### Begriffe

- **Tag 0**: Entscheidungstag, die letzte sichtbare Kerze. **Tag 1**: der folgende Handelstag.
  Alle Tagesangaben sind Handelstage (Kerzen).
- **Snapshot**: Paar (Ticker, Tag 0) aus historischen Daten mit ≥ 120 Handelstagen Zukunft.
- **Pool**: die 50.000 vorberechneten Snapshots; zugleich Spielrunden und ML-Trainingsdaten.
- **Option**: eine der sechs Entscheidungen K10, K30, K120 (Kaufen für H Tage) und W10, W30, W120
  (Warten für H Tage).
- **Stufe**: Einfach (Hebel L = 1), Mittel (L = L_mittel, Default 5), Profi (L = L_profi, Default 10).
- **P0**: Schlusskurs an Tag 0 (Basis der Karte). **E**: Einstieg = Eröffnungskurs an Tag 1.
- **B**: Guthaben vor der Runde. **M**: Einsatz. **X = M·L**: Exposure. **G**: Gebühr.
  **F**: Finanzierungskosten.
- **V**: Optionswert, Ergebnis einer Option als Anteil von B (R7). **V\***: größtes V der Runde.

## 2. Non-goals

- Kein Echtgeld, keine Broker-Anbindung, keine Orderausführung, keine Anlageberatung.
- Keine Short-Positionen; kein anderes Hebelprodukt als der vereinfachte Knock-out aus R5.
- Keine Intraday-Daten, keine Echtzeitkurse; ausschließlich Tageskerzen.
- Keine Steuern, keine Dividendenbuchungen, keine Währungsumrechnung (Kurse sind split- und
  dividendenbereinigt). Kosten gibt es nur als Gebühr und Finanzierung nach R5.
- Keine wählbaren Indikatoren oder Indikatorparameter. Keine freie Eingabe von SL, TP oder
  Positionsgröße im Spielmodus (das leistet später das Setup-Labor in M9).
- Kein Überspringen einer Runde (verhindert Rosinenpicken).
- Kein Login, kein Mehrbenutzer-Serverbetrieb, kein Cloud-Deployment, keine native Mobile-App und
  kein eigenes Mobil-Layout (der Smartphone-Browser muss nur bedienbar sein, M6).
- Keine Bestenliste, kein Multiplayer, keine Sounds oder Animationen.
- Keine Mehrsprachigkeit: UI nur auf Deutsch.
- Keine pixelgenaue Nachbildung der Referenzbilder; sie geben Stil und Farben vor (§3 Design).

## 3. Constraints

**Technik**
- Python ≥ 3.11 mit `uv`. Die Repo-Regeln aus [AGENTS.md](AGENTS.md) gelten unverändert:
  Funktionen ≤ 50 Zeilen, Komplexität ≤ 10, pyright strict in `src/`, Branch-Coverage ≥ 85 %,
  Testsuite offline und ≤ 60 s, Red-Green.
- Web-UI mit NiceGUI 3.x, Charts mit Plotly (`ui.plotly`). UI-Tests mit dem NiceGUI-`User`-Fixture
  (`nicegui.testing`), ohne Browser.
- Start mit `uv run gt app`: `ui.run` auf Port 8537 (änderbar per `GT_PORT`), ohne Auto-Reload und
  ohne automatisches Browser-Öffnen. Nicht 8080/8501; 8502, 8511, 8520, 8530 und 8550 sind auf dem
  Entwicklungsrechner belegt.
- Button „App beenden" in der Kopfzeile: ruft `app.shutdown()` auf und beendet damit nur den eigenen
  Prozess. Kein Beenden per Port.
- Hell/Dunkel-Umschalter in der Kopfzeile (`ui.dark_mode`); Default folgt der Systemeinstellung; die
  Wahl bleibt nach Neuladen der Seite erhalten.
- Schichten: reine Kernlogik ohne I/O (Indikatoren, Regeln R1–R11, Simulation, Bewertung, Ziehung),
  Adapter (Yahoo, Parquet, SQLite), dünne UI und CLI. Kernlogik wird ohne Netz und Dateien getestet.
- Persistenz: Kurse und Pool als Parquet, Nutzer und Runden in SQLite (stdlib `sqlite3`), alles
  unter `GT_DATA_DIR` (Default `data/`, gitignored).
- CLI-Einstiegspunkt `gt`, eingetragen unter `[project.scripts]` in `pyproject.toml`.
- Betrieb lokal auf einem Linux-Rechner, ein Nutzer gleichzeitig; Desktop-Browser zuerst.

**Design** (Referenzbilder lokal unter `docs/ui/references/`, gitignored, weil fremde Bilder)
- Hell = `light-simplicity.jpg`: blasses Blaugrau, Indigo als Primärfarbe, Cyan als Akzent, stark
  abgerundete Karten (Radius ca. 20–24 px) mit weichen Schatten, Kennzahl-Kacheln, viel Weißraum.
- Dunkel = `dark-broker.jpg`: Navy-Hintergrund, große blaue Aktionsflächen, Kerzen grün/rot,
  Preisachse rechts, dezentes Gitter.
- Farb-Richtwerte (aus den Bildern geschätzt, als Design-Tokens an einer Stelle im Code):

| Token | Hell | Dunkel |
|---|---|---|
| Hintergrund | #E3EAF4 | #0A1628 |
| Fläche/Karte | #F4F7FB | #12233A |
| Primär | #5448E0 | #1E88E5 |
| Akzent | #1FC1F0 | #1FC1F0 |
| Text | #1B1F4B | #E8EEF6 |
| Kerze steigend / fallend | #22B35E / #E5484D | #22B35E / #E5484D |

- Schrift: Systemschrift (sans-serif); keine externen CDNs, die App läuft offline.

**Daten**
- Quelle: Yahoo Finance über `yfinance` (inoffiziell, Rate-Limits, gelegentliche Datenfehler).
  Nur private, nicht-kommerzielle Nutzung.
- Tagesdaten OHLCV mit `auto_adjust=True` und `period="max"`.

**Lizenzen**
- Nur Apache-2.0-kompatible Abhängigkeiten: nicegui (MIT), plotly (MIT), yfinance (Apache-2.0),
  pandas, numpy, scikit-learn (BSD-3), pyarrow (Apache-2.0). Jede neue Abhängigkeit wird vor Aufnahme
  geprüft.

**Prozess**
- Umsetzung durch Claude Code (Sonnet, effort medium), ein Meilenstein je Phase. Dieses PRD ist
  die Quelle der Wahrheit: Unklarheiten werden zurückgemeldet, nicht selbst entschieden. Das PRD
  ändert sich nur mit Zustimmung des Nutzers.

## 4. Milestones

### Fachregeln R1–R11 (normativ, die Akzeptanzkriterien verweisen darauf)

**R1 Indikatoren.** Feste Parameter. Alle kausal: der Wert an Tag t nutzt nur Kerzen ≤ t. Berechnet
auf der gesamten Historie vor dem Zuschnitt des Chartfensters.
- SMA50, SMA200: einfacher gleitender Durchschnitt des Schlusskurses; die ersten n − 1 Werte sind leer.
- Bollinger-Bänder: Mitte = SMA20; oben/unten = Mitte ± 2·σ20, σ als Populations-Standardabweichung
  (ddof = 0).
- RSI14 nach Wilder: Startwert = arithmetisches Mittel der ersten 14 Gewinne bzw. Verluste, danach
  Glättung mit α = 1/14. Durchschnittsverlust 0 und Durchschnittsgewinn > 0 → 100; beide 0 → 50.
- ATR14 nach Wilder (True Range, gleiche Glättung). Nur für R4, nicht im Chart.
- Volumen: Rohwert je Tag.

**R2 Chart in der Entscheidungsansicht**
- Fenster: die letzten min(1260, verfügbare) Kerzen bis einschließlich Tag 0.
- Drei Zeilen mit gemeinsamer x-Achse: (1) Kerzen, SMA50, SMA200, Bollinger oben/Mitte/unten;
  (2) Volumen, gefärbt nach Kerzenrichtung; (3) RSI14 mit Linien bei 30 und 70, y-Bereich 0–100.
  Preisachse rechts.
- x-Achse: relative Handelstage (…, −2, −1, 0). Kein Kalenderdatum, kein Ticker, kein Name, keine
  Währung in Titel, Achsen, Legende oder Hover.
- Preise: echte, bereinigte Kurse.
- Zoom-Presets 3M / 6M / 1J / 5J = die letzten 63 / 126 / 252 / 1260 Kerzen, Start-Zoom 1J. Ein Preset
  setzt die y-Achse der Preiszeile auf Min/Max der sichtbaren Kerzen und Bänder ± 3 %.
- Freies Zoomen und Verschieben mit der Maus; Klick auf die Legende blendet einen Indikator aus/ein.
- Farben aus den Design-Tokens des aktiven Themes; beim Umschalten wird der Chart neu eingefärbt.

**R3 Optionen.** Genau sechs: K10, K30, K120, W10, W30, W120. H in Handelstagen.

**R4 Stop-Loss und Take-Profit** (nur K-Optionen)
- Die Karte entsteht vor Handelsbeginn aus Daten bis Tag 0: A = ATR14 an Tag 0.
- k_H = 1,5 (H = 10), 2,5 (H = 30), 4,0 (H = 120).
- d = clamp(k_H·A/P0, 1 %, d_max(L)) mit d_max(1) = 30 % und d_max(L > 1) = 0,8/L; d wird auf
  0,01 Prozentpunkte gerundet. Die Abstände in Prozent sind verbindlich.
- Beim Einstieg zu E (Eröffnung Tag 1): SL = E·(1 − d) auf Cent abgerundet, TP = E·(1 + 2d) auf Cent
  aufgerundet (Chance-Risiko-Verhältnis 1 : 2). Die Cent-Rundung ist robust gegen Gleitkommafehler
  (z. B. über `Decimal`), sodass das Rechenbeispiel unten exakt aufgeht.

**R5 Positionsgröße, Hebel und Kosten**
- Risiko je Trade ρ = 1 % von B, bezogen auf die Kursbewegung bei Stufe Einfach; Kosten zählen nicht
  zum Risikobudget.
- Einsatzanteil f = min(1, ρ/d); Einsatz M = f·B, auf Cent abgerundet; Exposure X = M·L;
  Stückzahl q = X/E (Bruchstücke erlaubt).
- Hebel als vereinfachtes Knock-out-Produkt: KO = E·(1 − 1/L) für L > 1. Der Verlust eines Trades ist
  inklusive Kosten höchstens M, also kann B nie negativ werden.
- Gebühr (Spread und Order, für Kauf und Verkauf zusammen): G = g·M mit g = Gebührensatz des Nutzers
  (Default 2 %), auf allen Stufen.
- Finanzierung des geliehenen Teils: F = (L − 1)·M·z·n/252 mit z = Zinssatz des Nutzers (Default 5 %
  p. a.) und n = Haltedauer in Handelstagen (R6). Bei L = 1 ist F = 0.
- Jede K-Karte zeigt: Horizont und Stufe; SL (−d %) und TP (+2d %) mit voraussichtlichen Preisen auf
  Basis P0; CRV 1 : 2; M (€ und % von B); L; X; voraussichtliche Stückzahl X/P0; G (€); bei L > 1 die
  Finanzierung bei voller Haltedauer (€) und den KO-Abstand (−100/L %); Verlust bei SL (M·L·d + G) und
  Gewinn bei TP (M·L·2d − G) in €, jeweils ohne Finanzierung und ohne Kurslücken.

**R6 Simulation einer K-Option.** Einstieg zu E = O_1; SL, TP und KO nach R4/R5 auf Basis E. Für die
Tage i = 1 … H mit (O_i, H_i, L_i, C_i) gilt je Tag die erste zutreffende Zeile:
1. i ≥ 2, L > 1 und O_i ≤ KO → Exit zu O_i, Grund „KO".
2. i ≥ 2 und O_i ≤ SL → Exit zu O_i (Kurslücke), Grund „SL".
3. i ≥ 2 und O_i ≥ TP → Exit zu O_i, Grund „TP".
4. L_i ≤ SL → Exit zu SL, Grund „SL", auch wenn am selben Tag H_i ≥ TP (konservativ).
5. H_i ≥ TP → Exit zu TP, Grund „TP".

Ohne Exit bis Tag H: Exit zu C_H, Grund „Zeit". Haltedauer n = Index des Exit-Tages (1 … H).
Rendite r = Exitkurs/E − 1. G und F werden auf Cent gerundet (kaufmännisch).
P&L = max(−M, M·L·r − G − F), auf Cent gerundet. Weniger als H Kerzen nach Tag 0 → Fehler (im Pool
ausgeschlossen durch R10).

**R7 Optionswert.** V(K_H) = P&L/B aus R6. V(W_H) = −V(K_H) derselben Stufe: Warten ist genau dann
richtig, wenn der Kauf mit gleichem Horizont (inklusive Kosten) verloren hätte, und bringt den
vermiedenen Verlust als Wert.

**R8 Punkte** mit ε = 0,0001 (0,01 Prozentpunkte)
- V\* < ε → neutrale Runde: jede Wahl 0 Punkte, Hinweis „Keine Option war vorteilhaft".
- V ≥ V\* − ε → 100 Punkte, „optimal" (mehrere Optionen können optimal sein).
- sonst V > 0 → floor(100·V/V\* + 1e-9), höchstens 99.
- sonst 0 Punkte. Die Stufe verändert die Punkte nicht.

**R9 Buchung**
- Nur K-Optionen verändern B: B_neu = B + P&L (R6, inklusive Kosten). W-Optionen buchen nichts.
- Invariante B ≥ 0. Ist B < 1 % des Startkapitals, sind K-Optionen gesperrt, mit Hinweis auf den
  Reset im Setup.

**R10 Eignung eines Snapshots**
- Tag 0 ≥ 2000-01-01; ≥ 250 Kerzen bis einschließlich Tag 0; ≥ 120 Kerzen danach.
- Keine Kalenderlücke > 10 Tage zwischen aufeinanderfolgenden Kerzen im Bereich
  [Tag 0 − 250 Kerzen, Tag 0 + 120 Kerzen].
- Schlusskurs an Tag 0 ≥ 1,00; Median von Schlusskurs·Volumen über die letzten 20 Kerzen
  ≥ 1.000.000; ATR14 > 0.
- Snapshots desselben Tickers liegen ≥ 20 Kerzen auseinander.

**R11 Signal-Ereignisse an Tag 0.** Kreuzungen zählen, wenn sie in den letzten 3 Kerzen bis Tag 0
liegen; Zustände gelten an Tag 0.
- Kreuzungen: GOLDEN_CROSS (SMA50 kreuzt SMA200 aufwärts), DEATH_CROSS (abwärts), SMA200_UP
  (Schlusskurs kreuzt SMA200 aufwärts), SMA200_DOWN (abwärts).
- Zustände: RSI_LT_30, RSI_GT_70, CLOSE_GT_UPPER_BB, CLOSE_LT_LOWER_BB, VOLUME_SPIKE (Volumen
  > 2 × SMA20 des Volumens bis Tag −1).
- Signaltag = mindestens ein Ereignis.

**Rechenbeispiel (verbindlicher Testfall).** B = 10.000,00 €, P0 = 100,00, A = 2,00, g = 2 %,
z = 5 % p. a.; soweit nicht anders angegeben öffnet Tag 1 bei E = 100,00:

| Option | d | SL | TP | f | M | G |
|---|---|---|---|---|---|---|
| K10 | 3 % | 97,00 | 106,00 | 1/3 | 3.333,33 € | 66,67 € |
| K30 | 5 % | 95,00 | 110,00 | 0,20 | 2.000,00 € | 40,00 € |
| K120 | 8 % | 92,00 | 116,00 | 0,125 | 1.250,00 € | 25,00 € |

- Karte K30 Einfach: X = 2.000 €, Stückzahl ≈ 20; Verlust bei SL 140 €, Gewinn bei TP 160 €.
- Karte K30 Profi (L = 10): X = 20.000 €, Stückzahl ≈ 200; Verlust bei SL 1.040 €, Gewinn bei TP
  1.960 €; Finanzierung bei voller Haltedauer 107,14 €; KO-Abstand −10 %.
- K120 Profi: d_max = 8 %, d bleibt 8 % (Grenzfall des Clampings).
- Kurslücke: Tag 1 öffnet bei 103 → K30 mit E = 103,00, SL = 97,85, TP = 113,30; M bleibt 2.000 €.
- K30 Einfach, Tag 1 ohne Auslösung, Tag 2 mit O 99, H 111, L 98 → Exit TP 110 → P&L = 200 − 40 =
  +160 € → V = +1,6 %, B_neu = 10.160,00 €.
- K30 Einfach, Tag 1 mit O 100, L 94 → Exit SL 95 an Tag 1 (keine Lückenregel an Tag 1) → V = −1,4 %.
- K30 Einfach, Tag 2 öffnet bei 94 → Exit 94 → P&L = −120 − 40 = −160 € → V = −1,6 %.
  Dasselbe bei Profi: F = 7,14 € (n = 2) → P&L = −1.200 − 40 − 7,14 = −1.247,14 € → V = −12,4714 %.
  Öffnet Tag 2 bei 89 (≤ KO 90,00) → P&L = −2.000 € (= −M) → V = −20 %.
- K30 Einfach, Tag 2 mit O 100, H 111, L 94 → Exit SL 95 → V = −1,4 %.
- K30 Einfach ohne Auslösung, C_30 = 103 → P&L = 60 − 40 = +20 € → V = +0,2 %.
- Punkte: V(K10, K30, K120) = (+1,2 %, −1,0 %, +2,0 %), also V(W10, W30, W120) = (−1,2 %, +1,0 %,
  −2,0 %). V\* = 2,0 % → K120: 100, K10: 60, W30: 50, alle anderen: 0.

### M1 — Kursdaten und Universum
- **Deliverable:**
  - `src/app/resources/universe.csv` (Spalten `ticker,name,market`) mit den Werten aus S&P 500,
    NASDAQ-100, DAX, MDAX und SDAX in heutiger Zusammensetzung, dedupliziert (≥ 600 Ticker; deutsche
    Werte mit Yahoo-Suffix `.DE`). Quelle und Stichtag stehen in `docs/data.md`.
  - Yahoo-Adapter und Preis-Store: `data/prices/<TICKER>.parquet` mit den Spalten `date` (Datum ohne
    Zeitzone), `open`, `high`, `low`, `close` (float64), `volume` (int64); aufsteigend, Daten eindeutig.
  - Reine Bereinigungsfunktion. CLI `gt data download [--tickers …]` und `gt data update` mit
    Abschlussbericht (erfolgreich, fehlgeschlagen, Zeilen, Korrekturen).
- **Acceptance criteria:**
  - Bereinigung (synthetische Frames): Zeilen mit fehlendem OHLC oder Preis ≤ 0 werden entfernt;
    doppelte Daten → die letzte Zeile bleibt; unsortiert → sortiert; high < max(open, close) bzw.
    low > min(open, close) werden auf max bzw. min korrigiert und im Bericht gezählt.
  - `universe.csv`: keine doppelten Ticker, keine leeren Felder (Test).
  - Adapter mit gemocktem `yfinance`: Einzel- und Batch-Antwort (MultiIndex-Spalten) ergeben dieselbe
    Parquet-Struktur mit denselben dtypes.
  - Ein fehlschlagender Ticker (Exception oder leere Antwort) bricht den Lauf nicht ab und steht im
    Bericht. Exit-Code 0 bei mindestens einem Erfolg, sonst ≠ 0.
  - Rate-Limit: bis zu 3 Wiederholungen mit exponentiellem Backoff; Pause zwischen Batches per
    Umgebungsvariable einstellbar. Test mit gemockter Fehlerfolge und gefälschter Uhr, ohne echtes Warten.
  - `update` lädt nur Tage nach dem letzten gespeicherten Datum und hängt sie an. Ein abgebrochener
    `download` lässt sich neu starten und überspringt bereits vollständige Ticker.
  - Manuell (außerhalb des Gates): voller Download des Universums, ≥ 95 % der Ticker erfolgreich;
    Ergebnis in IMPLEMENTATION.md notiert.
- **Edge cases:** Ticker ohne Daten (delistet, umbenannt) → Fehlerliste. Historie < 250 Kerzen →
  gespeichert, im Pool nie geeignet (R10). Zeitzonenbehafteter Index → auf Datum normalisiert.
  Fehlendes Volumen → 0.
- **Dependencies:** keine.

### M2 — Indikatoren, Chart und App-Grundgerüst
- **Deliverable:** Indikatorfunktionen (R1), Chart-Builder (R2), NiceGUI-App mit Kopfzeile
  (Navigation nur zu umgesetzten Modi, Hell/Dunkel-Umschalter, „App beenden"), Design-Tokens für beide
  Themes, Port-Konfiguration. Die Seite „Spielen" zeigt vorerst den Chart eines zufälligen Tickers an
  einem zufälligen Tag 0 mit ≥ 250 Kerzen Historie, ohne Optionen.
- **Acceptance criteria:**
  - SMA, Bollinger, RSI und ATR stimmen mit Referenzwerten auf festen Fixtures überein (Toleranz
    1e-6). Die Referenzwerte stammen aus Handrechnung oder einer unabhängigen Quelle, im Test benannt.
  - Kausalität (Property-Test mit zufälligen Reihen): Indikatorwerte bis Tag t sind identisch, egal ob
    mit oder ohne die Kerzen nach t berechnet.
  - RSI liegt immer in [0, 100]; die Sonderfälle aus R1 (nur Gewinne → 100, konstante Kurse → 50)
    sind getestet.
  - Figure: 3 Zeilen; Traces für Kerzen, SMA50, SMA200, BB oben/Mitte/unten, Volumen, RSI und die
    Linien 30/70; Preisachse rechts; letzte x-Koordinate = 0; Anzahl Kerzen = min(1260, verfügbare).
  - Leck-Test: die als JSON serialisierte Figure enthält weder Ticker noch Namen noch ein Datum im
    Format JJJJ-MM-TT.
  - Bei einer Historie ≥ 1260 + 199 Kerzen ist SMA200 ab der ersten sichtbaren Kerze definiert.
  - Zoom-Presets setzen x- und y-Bereich gemäß R2 (Test auf die Layout-Werte).
  - Figure für Hell und Dunkel nutzt die jeweiligen Token-Farben (Test auf Hintergrund und Kerzenfarben).
  - `User`-Fixture: die Seite lädt mit einem synthetischen Preis-Store ohne Exception; ohne Preisdaten
    erscheint ein Hinweis auf `gt data download` statt eines Fehlers; der Umschalter wechselt den
    Dark-Mode-Wert; „App beenden" ruft `app.shutdown()` genau einmal auf (gemockt).
  - `gt app` startet auf Port 8537 bzw. `GT_PORT` (Test auf die an `ui.run` übergebenen Argumente).
  - Manuell: Chart und Kopfzeile in Hell und Dunkel lesbar und nah an den Referenzbildern.
- **Edge cases:** weniger als 200 Kerzen vor Fensterbeginn → SMA200 beginnt später im Fenster, leere
  Werte werden nicht gezeichnet. Konstante Kurse → Bandbreite 0 ohne Fehler. Volumen 0 → leerer Balken.
- **Dependencies:** M1 (Preis-Store; für Tests genügt ein synthetischer Store).

### M3 — Handelsvorschläge, Simulation und Bewertung
- **Deliverable:** reine Funktionen für R3–R9: Karten aus (Kerzen bis Tag 0, B, Stufe, L, g, z)
  erzeugen, K-Optionen ab Tag 1 simulieren, V aller sechs Optionen, Punkte und Buchungsbetrag.
- **Acceptance criteria:**
  - Das Rechenbeispiel aus den Fachregeln ist vollständig als Test abgebildet und grün.
  - Jede Zeile von R6 hat einen eigenen Test, inklusive: keine Lückenregeln an Tag 1, Lücke unter KO
    vor SL, SL vor TP am selben Tag, Zeit-Exit mit n = H.
  - Clamping (R4): sehr kleine ATR → d = 1 %; große ATR bei L = 10 → d = 8 %, TP folgt dem geclampten d.
  - Bei d = 1 % ist f = 1 (M = B).
  - Kosten: G auf allen Stufen, F = 0 bei L = 1, F wächst linear mit n; P&L ist nach Abzug der Kosten
    nie kleiner als −M.
  - Property-Tests mit zufälligen Kerzenfolgen: P&L ≥ −M; B_neu ≥ 0; V(W_H) = −V(K_H); genau die
    Optionen mit V ≥ V\* − ε erhalten 100 Punkte; Punkte liegen in [0, 100].
  - Neutrale Runde (alle |V| < ε) → alle Optionen 0 Punkte.
  - Weniger als H Kerzen nach Tag 0 → `ValueError`.
- **Edge cases:** Cent-Rundung verschiebt die tatsächlichen SL/TP-Abstände minimal → f bleibt der Wert
  der Karte. SL fällt durch Rundung auf KO → Zeile 1 von R6 hat Vorrang. B = 0 → alle K-Optionen
  gesperrt (R9). g = 0 und z = 0 → Ergebnis ohne Kosten.
- **Dependencies:** M2 (R1: ATR, Indikatoren).

### M4 — Snapshot-Pool (50.000)
- **Deliverable:** CLI `gt snapshots build --n 50000 --seed 42` schreibt `data/snapshots.parquet`
  und `data/snapshots.json` (Metadaten: Seed, Datenstand, g = 2 %, z = 5 %, Stufen 1/5/10, Bericht).
  Schema der Parquet-Datei:
  - `snapshot_id` (die ersten 12 Hex-Zeichen von sha1("TICKER|JJJJ-MM-TT")), `ticker`, `t0` (Datum),
    `n_hist` (Kerzen bis einschließlich Tag 0).
  - `sig_<EREIGNIS>` je Ereignis aus R11 (bool) und `is_signal_day` (bool).
  - Je L ∈ {1, 5, 10} und H ∈ {10, 30, 120}: `v_l{L}_h{H}` (float, V der K-Option mit Default-Kosten),
    `exit_l{L}_h{H}` (TP, SL, KO oder TIME), `exit_day_l{L}_h{H}` (int).
  - Je L: `label_l{L}` = die erste optimale Option in der Reihenfolge K10, K30, K120, W10, W30, W120;
    NEUTRAL bei neutraler Runde.
- **Acceptance criteria:**
  - Genau N Zeilen, keine doppelte `snapshot_id`. Zu wenige geeignete Kandidaten → Abbruch mit
    „benötigt N, verfügbar K".
  - Jede Zeile erfüllt R10. Tests mit synthetischen Reihen: Lücke > 10 Tage, Kurs < 1, zu kurze
    Historie, zu nahe Snapshots desselben Tickers.
  - Mischung: 70 % ± 1 % Signaltage, sofern genug vorhanden; sonst alle verfügbaren Signaltage und
    ein Hinweis im Bericht.
  - Determinismus: gleiche Daten und gleicher Seed → identischer Inhalts-Hash der Datei.
  - Kausalität: die Signalflags ändern sich nicht, wenn die Kerzen nach Tag 0 entfernt werden.
  - Konsistenz: für eine Stichprobe von Zeilen liefern die M3-Funktionen dieselben `v_*`, `exit_*`
    und `label_*`.
  - Bericht: Label-Verteilung je Stufe, Anteil Signaltage, Anzahl Ticker, Zeitraum.
  - Manuell: 50.000 Snapshots auf dem vollen Universum in ≤ 15 min.
- **Edge cases:** Ticker ohne geeignete Tage → 0 Snapshots, im Bericht aufgeführt. Neubau nach
  `gt data update` → neuer Pool; bereits gespielte Runden bleiben lesbar, weil sie Ticker und Tag 0
  selbst speichern (M6).
- **Dependencies:** M1, M3.

### M5 — Persistenz und Setup-Modus
- **Deliverable:** SQLite-Datenbank `data/app.db` mit Schema-Version. Seite „Setup": Nutzer anlegen,
  aktiven Nutzer wählen, Startkapital, Hebel für Mittel und Profi, Zinssatz und Gebührensatz festlegen,
  Guthaben zurücksetzen. Datenpflege (Download, Update, Pool-Neubau) bleibt ausschließlich in der CLI.
- **Acceptance criteria:**
  - Fehlende Tabellen werden beim Start angelegt; die Schema-Version wird gespeichert.
  - Nutzername: nach Trimmen 1–40 Zeichen, eindeutig ohne Beachtung der Groß-/Kleinschreibung.
    Verstoß → Fehlermeldung, keine neue Zeile.
  - Startkapital: ganze Euro 1.000–1.000.000, Default 10.000. Ein neuer Nutzer startet mit
    B = Startkapital. Eine spätere Änderung des Startkapitals wirkt ab dem nächsten Reset.
  - Beträge als Integer-Cent; CHECK-Constraint B ≥ 0 (Test: ein negativer Wert wird abgewiesen).
  - Reset nur nach Bestätigung: setzt B = Startkapital und protokolliert Zeitpunkt und B vorher.
    Punkte und Rundenhistorie bleiben erhalten; die Statistik zählt die Resets. Nutzer sind nicht löschbar.
  - Hebel: ganze Zahlen 2–20, L_mittel ≤ L_profi, Defaults 5 und 10. Einfach ist fest 1 und nicht
    editierbar.
  - Zinssatz 0,0–20,0 % p. a. (Default 5,0), Gebührensatz 0,0–10,0 % (Default 2,0), je in
    0,1-Schritten, je Nutzer gespeichert. Werte außerhalb → Fehlermeldung, keine Änderung.
  - Nach einem Neustart ist der zuletzt aktive Nutzer vorausgewählt.
  - `User`-Fixture: Anlegen → der Nutzer erscheint in der Auswahl; ungültige Eingabe → Fehlermeldung;
    Reset ohne Bestätigung ändert nichts.
- **Edge cases:** kein Nutzer vorhanden → die Spielseite zeigt einen Hinweis mit Link zum Setup.
  Änderung von Hebel, Zins- oder Gebührensatz bei offener, unbestätigter Runde → die Karten werden
  neu berechnet.
- **Dependencies:** M2 (App-Grundgerüst).

### M6 — Spielmodus
- **Deliverable:** vollständige Spielrunde nach R1–R9 auf dem Pool:
  1. Ziehung aus den Snapshots mit der geringsten Spielzahl des Nutzers, label-stratifiziert: erst ein
     Label (`label_l1`) gleichverteilt unter den vorhandenen, dann ein Snapshot gleichverteilt innerhalb
     des Labels. Die Runde wird sofort als „offen" gespeichert.
  2. Entscheidungsansicht: Kennzahl-Kacheln (Guthaben, Punkte gesamt, Runde), Chart (R2), Stufenwahl,
     sechs Optionskarten (Zeile „Kaufen", Zeile „Warten") mit den Inhalten aus R5.
  3. Die Auswahl einer Karte zeigt eine Vorschau im Chart: SL, TP (und KO) als horizontale Linien über
     H Tage auf Basis P0, bei W-Optionen eine Markierung bei Tag H. Erst „Entscheidung bestätigen" legt
     die Wahl fest.
  4. Auflösung: Chart um die nächsten 120 Kerzen erweitert (Zukunftsbereich farbig hinterlegt, Linie
     bei Tag 0), Ein- und Ausstiegsmarker mit Exit-Grund. Tabelle aller sechs Optionen mit V (% und €),
     Exit-Grund, Kosten und Punkten, markiert „Ihre Wahl" und „optimal". Aufgedeckt werden Ticker, Name,
     Datum von Tag 0 und die an Tag 0 aktiven Signal-Ereignisse (R11). Dazu B vorher/nachher und Punkte
     der Runde und gesamt.
  5. „Nächste Runde" startet bei Schritt 1.
  - Statistik: Runden, Punkte gesamt, Ø Punkte je Runde, Anteil optimaler Entscheidungen, B im
    Vergleich zum Startkapital, Anzahl Resets.
  - Layout im Stil der Referenzbilder (abgerundete Karten, Kacheln, große Aktionsflächen):
    ```
    +- Kopfzeile: Gamified Trader | Spielen  Setup | Spieler 1 | [Hell/Dunkel] [Beenden] -+
    | [Guthaben 10.000,00 EUR]  [Punkte 1.240]  [Runde 37]   Stufe: Einfach|Mittel|Profi |
    | +- Chart ---------------------------------------------------------------------+   |
    | | [3M] [6M] [1J] [5J]                                                         |   |
    | | Kerzen + SMA50/200 + Bollinger                               Preisachse ->  |   |
    | | Volumen                                                                     |   |
    | | RSI 14                                                                      |   |
    | +-----------------------------------------------------------------------------+   |
    | Kaufen:  [K10 Karte]   [K30 Karte]   [K120 Karte]                                 |
    | Warten:  [W10]         [W30]         [W120]         [Entscheidung bestätigen]     |
    +-----------------------------------------------------------------------------------+
    ```
  - Unter 768 px Breite stapelt sich das Layout (Kacheln, Chart, Karten untereinander).
- **Acceptance criteria:**
  - Leck-Test (`User`-Fixture): vor der Bestätigung enthält keine gerenderte Komponente (Text,
    Tabellen, Figure-JSON) Ticker, Namen oder Datum des Snapshots; nach der Bestätigung sind alle drei
    sichtbar.
  - Eine offene Runde übersteht Neuladen der Seite und Neustart der App: gleiche `snapshot_id`, keine
    neue Ziehung.
  - Nach der Bestätigung ist die Wahl nicht mehr änderbar. Doppeltes Bestätigen (Doppelklick, zweiter
    Tab) bucht genau einmal (Test).
  - Buchung und Punkte entsprechen R8 und R9 für die gewählte Stufe und die Hebel-, Zins- und
    Gebührenwerte des Nutzers (Test mit synthetischem Pool, gegen die M3-Funktionen geprüft).
  - Der Rundendatensatz speichert Nutzer, `snapshot_id`, Ticker, Tag 0, Stufe, L, g, z, Option, V,
    P&L (Cent), G, F, Punkte, B vorher und nachher sowie Zeitstempel.
  - Ein Stufenwechsel vor der Bestätigung berechnet die Karten neu; gespeichert wird die bestätigte Stufe.
  - Ziehung (fester Seed): bei einem Pool mit 6 Labels × 10 Snapshots liegt nach 600 Ziehungen jede
    Label-Häufigkeit zwischen 60 und 140, und kein Snapshot wiederholt sich, solange ungespielte existieren.
  - B < 1 % des Startkapitals → K-Karten deaktiviert, Hinweis mit Link zum Setup (R9).
  - Manuell mit warmem Cache: „Nächste Runde" bis zum fertigen Chart ≤ 2 s; Auflösung ≤ 1 s.
  - Manuell: je Stufe 20 Runden fehlerfrei gespielt; Bedienung im Smartphone-Browser (≤ 400 px Breite)
    möglich; Screenshots in Hell und Dunkel unter `docs/ui/`.
- **Edge cases:** Pool-Datei fehlt → Hinweis auf `gt snapshots build`. Preisdatei eines Snapshots fehlt
  → Snapshot wird übersprungen und protokolliert. Neuladen während der Auflösung → dieselbe Auflösung
  wird erneut gezeigt, ohne zweite Buchung. Pool ausgeschöpft → Wiederholung aus den am seltensten
  gespielten Snapshots.
- **Dependencies:** M2, M3, M4, M5.

### M7 — Features und ML-Modell (vorläufig)
- **Deliverable:** kausale, skalenfreie Features je Snapshot in `data/features.parquet`; Training und
  Evaluation per `gt model train`; Modellartefakt mit Metadaten (Featureliste, Trainingszeitraum,
  Metriken, Seed) unter `data/models/`; globale Feature Importance (Permutation Importance auf den
  Testdaten).
  - Startliste Features: Renditen über 5/20/60/120/250 Tage; Abstand des Kurses zu SMA50 und SMA200;
    Verhältnis SMA50/SMA200; Steigung von SMA50 und SMA200 über 20 Tage; RSI14 und seine Änderung über
    5 Tage; Bollinger %B, Bandbreite und deren Perzentil über 126 Tage; Volumen relativ zu SMA20 des
    Volumens; ATR14 in %; 20-Tage-Volatilität; Abstand zum 252-Tage-Hoch und -Tief; Signalflags (R11).
  - Modell: scikit-learn HistGradientBoosting mit den Zielen `v_l{L}_h{H}`.
- **Acceptance criteria (vorläufig):**
  - Kausalitätstest wie in M2 für alle Features.
  - Walk-forward-Validierung mit ≥ 4 Folds und einem Embargo von 120 Kerzen: kein Trainings-Snapshot,
    dessen [Tag 0, Tag 0 + 120] in den Testzeitraum reicht (Test).
  - Bericht vergleicht die Empfehlung mit den Baselines „immer K120 Einfach", „häufigstes Label" und
    „Zufall" über Ø V und Ø Punkte auf den Testfolds.
  - Reproduzierbar mit festem Seed.
- **Edge cases:** leere Featurewerte bei kurzer Historie → vom Modell direkt verarbeitet (NaN-fähig),
  dokumentiert.
- **Dependencies:** M4.

### M8 — Entdeckungsmodus (vorläufig)
- **Deliverable:** Seite „Entdecken": Ticker-Eingabe mit Suche; Chart wie R2, aber mit echtem Datum und
  Ticker, Tag 0 = letzter Handelstag. ML-Empfehlung: Option (K oder W, Horizont) und Stufe, dazu SL, TP,
  Positionsgröße und Kosten nach R4/R5 für das aktuelle B, Modell-Konfidenz und die wichtigsten
  Einflussgrößen. Dauerhaft sichtbarer Hinweis „Lern-App, keine Anlageberatung".
- **Acceptance criteria (vorläufig):**
  - Unbekannter Ticker → verständliche Meldung, kein Absturz. Weniger als 250 Kerzen → Chart ohne
    Empfehlung.
  - Kurse werden je Ticker höchstens einmal pro Tag neu geladen (Cache).
  - Die Empfehlung nutzt nur Kerzen bis Tag 0 und dieselbe Featurefunktion wie das Training (Test).
  - Schlägt das Modell im M7-Bericht die Baselines nicht, zeigt die Seite das deutlich an.
- **Edge cases:** Ticker ist keine Aktie (z. B. ETF, Krypto) → Umgang wird mit A19 festgelegt.
- **Dependencies:** M7.

### M9 — Lernmodus (vorläufig)
- **Deliverable:**
  - Signal-Bibliothek: je Indikator und Signal-Ereignis eine Erklärung (Allgemeinwissen) plus Statistik
    aus dem Pool: Häufigkeit, Verteilung der optimalen Optionen, Ø V je Option im Vergleich zur
    Grundrate, Beispielcharts.
  - Setup-Labor (interaktiv): Signalfilter, SL-Multiplikator, CRV, Risiko je Trade, Stufe, Horizont und
    Kosten wählen → Simulation über die passenden Pool-Snapshots → Trefferquote, Erwartungswert,
    Verteilung von V, Kapitalkurve.
  - Feature Importance aus M7 mit verständlicher Erklärung.
- **Acceptance criteria (vorläufig):**
  - Alle Statistiken sind reproduzierbar aus dem Pool berechnet (Test mit synthetischem Pool).
  - Das Labor nutzt die Simulationsfunktion aus M3, keine zweite Implementierung.
  - Jede Signalseite erklärt den Unterschied zwischen Einzelfall (Spielrunde) und Erwartungswert
    (Statistik).
- **Edge cases:** Signalfilter ohne Treffer → Hinweis statt leerer Grafik.
- **Dependencies:** M4, M7.

## 5. Open risks & assumptions

### Entscheidungen aus grill-me (2026-09-21)

Die Regeln in §4 setzen diese Entscheidungen um; bei Widerspruch gilt §4.

- **A1** Stufen, 50.000 Snapshots und Auflösung gehören zum Spielmodus (das Diktat sagte dort teils
  „Lernmodus").
- **A2** 10/30/120 Tage sind Handelstage.
- **A3** Das Optimum ergibt sich aus dem tatsächlichen Verlauf (ex post).
- **A4** Warten ist das Gegenstück zum Kauf: V(W_H) = −V(K_H); eine Runde = eine Entscheidung (R7).
- **A5** Punkte proportional zum Optimum, kein Stufen-Multiplikator (R8).
- **A6** Einstieg zur Eröffnung von Tag 1; SL/TP-Abstände in Prozent bleiben, die Preise werden auf den
  echten Einstieg umgerechnet (R4, R6).
- **A7** SL/TP über ATR, CRV 1 : 2 (R4).
- **A8** Positionsgröße nach der 1-%-Regel; der Hebel vervielfacht Gewinn und Verlust (R5).
- **A9** Knock-out mit Kosten: Finanzierung auf den geliehenen Teil mit einstellbarem Zinssatz
  (Default 5 % p. a.) und 2 % Gebühr (Spread und Order) auf den Einsatz pro Trade, ebenfalls
  einstellbar (R5, M5).
- **A10** Ticker, Name und Datum bis zur Auflösung verborgen; Preise echt.
- **A11** Universum S&P 500, NASDAQ-100, DAX, MDAX, SDAX (M1).
- **A12** Pool 70 % Signaltage / 30 % Zufallstage; Ziehung label-stratifiziert (M4, M6).
- **A13** Start-Zoom 1 Jahr (R2).
- **A14** NiceGUI statt Streamlit; eigener Hell/Dunkel-Umschalter; Hell im Stil `light-simplicity.jpg`,
  Dunkel im Stil `dark-broker.jpg`; Desktop zuerst, im Smartphone-Browser bedienbar (§3).
- **A15** Stufen Einfach / Mittel / Profi; Hebel 2–20 (M5).
- **A16** Reset nur für das Guthaben; Nutzer nicht löschbar (M5).
- **A17** Alle Beträge in €, ohne Umrechnung; gerechnet wird mit prozentualen Kursänderungen.
- **A18** Datenpflege nur per CLI (M5).

### Offen (vor M7 in eigener grill-me-Runde klären)

- **A19 Empfehlungslogik im Entdeckungsmodus.** Ein reines Erwartungswertmodell empfiehlt bei
  positivem Erwartungswert immer den höchsten Hebel. Vorschlag: risikoadjustierte Hebelwahl (z. B.
  halbes Kelly aus vorhergesagtem Mittel und Streuung). Offen ist auch der Umgang mit Nicht-Aktien.
- **A20 Lerninhalte** („Common Knowledge") werden bei der Umsetzung formuliert und vom Nutzer
  fachlich abgenommen; Umfang und Form sind offen.

### Risiken

- **Yahoo/yfinance instabil** (Rate-Limits, API-Änderungen, Datenfehler). Mitigation: lokaler Cache,
  fortsetzbarer Download, yfinance nur im Adapter. Trigger: > 5 % Fehlschläge → Quelle überdenken.
- **Nutzungsbedingungen Yahoo:** nur private Nutzung. Trigger: Weitergabe oder Veröffentlichung der App.
- **Hindsight-Rauschen:** das Ex-post-Optimum ist teils Zufall und kann frustrieren. Mitigation: die
  Auflösung zeigt Signale und alle sechs Werte; der Lernmodus zeigt Erwartungswerte.
- **Label-Schiefe:** Aufwärtsdrift und CRV 1 : 2 begünstigen Käufe, 2 % Gebühr begünstigt Warten.
  Mitigation: stratifizierte Ziehung (A12); der M4-Bericht zeigt die Verteilung.
- **Survivorship Bias** durch die heutige Indexzusammensetzung (A11), verstärkt bei Nebenwerten.
  Mitigation: im Lernmodus erklären; Trigger: auffällig hoher Anteil optimaler Käufe im M4-Bericht.
- **Data Leakage im ML** durch überlappende Zukunftsfenster. Mitigation: Zeitsplit mit Embargo und
  Kausalitätstests (M7).
- **Keine echte Vorhersagekraft** des Modells. Mitigation: Baseline-Vergleich und deutliche Anzeige (M8).
- **pyright strict mit pandas, plotly, yfinance** (unvollständige Typen) erzeugt Reibung für den
  Umsetzer. Mitigation: `pandas-stubs`, untypisierte Bibliotheken nur in Adaptern und im Chart-Modul,
  gezielte `# pyright: ignore[...]` mit Begründung. Trigger: > 10 Ignores in einem Modul → Regel mit
  dem Nutzer klären.
- **NiceGUI-Tests und Offline-Regel:** `tests/conftest.py` blockiert Sockets; das `User`-Fixture läuft
  im Prozess, braucht aber `pytest-asyncio`. Mitigation: in M2 als erstes einen minimalen `User`-Test
  grün bekommen. Trigger: Konflikt mit der Socket-Sperre → Lösung mit dem Nutzer klären, nicht die
  Sperre still lockern.
- **NiceGUI kleinere Community** als Streamlit. Mitigation: Doku per Context7 prüfen, UI dünn halten.
- **60-s-Grenze der Testsuite** bei pandas-lastigen Tests. Mitigation: kleine synthetische Fixtures,
  Pool-Builds in Tests mit N ≤ 200.
- **Wirkung als Anlageempfehlung** im Entdeckungsmodus. Mitigation: dauerhafter Hinweis (M8).

## 6. Definition of done

**Release 1 (Spielmodus + Setup)**
- [ ] M1–M6: alle Akzeptanzkriterien als Tests umgesetzt, Red-Green belegt, Gate grün
      (`uv run pre-commit run --all-files`).
- [ ] Echtdaten: Universum geladen (≥ 95 %), Pool mit 50.000 Snapshots gebaut, Bericht in
      IMPLEMENTATION.md.
- [ ] Manuell: 20 Runden je Stufe gespielt; Leck- und Idempotenz-Test grün.
- [ ] Screenshots in Hell und Dunkel unter `docs/ui/`, vom Nutzer mit den Referenzbildern abgeglichen.
- [ ] README beschreibt App-Start und `gt`-Befehle; [docs/architecture.md](docs/architecture.md)
      beschreibt Module und Datenfluss; die Phasen M1–M6 in IMPLEMENTATION.md stehen auf `done`.

**Gesamtprodukt**
- [ ] Release 1 erfüllt.
- [ ] A19 und A20 geklärt; M7–M9 in einer eigenen PRD-Iteration detailliert und abgenommen; ihre
      Akzeptanzkriterien grün.
- [ ] Das Modell schlägt die Baselines auf den Testfolds, oder die UI weist klar darauf hin.
