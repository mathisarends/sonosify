# CLI-Feedback: `sonosify` für autonome Agents

Perspektive: Ein Agent, der `sonosify` ausschließlich über Bash-Aufrufe steuert –
ohne den Python-Import zu nutzen. Er kann keine interaktiven Prozesse bedienen
(kein `Ctrl+C`), muss stdout/stderr und Exit-Codes parsen, und will mit möglichst
wenigen Aufrufen zum Ziel kommen. Bewertet wird der Stand auf
`feature/python-3_13_support`.

## Was heute schon gut funktioniert

- `--format json` / `--format tsv` gibt es bereits und deckt die meisten Read-
  und Action-Kommandos ab. Das ist die wichtigste Grundlage für Agents.
- `discover --format json` liefert `room`, `ip`, `uid`, `coordinator` – genau die
  Felder, die man zum späteren Targeting per `--ip` braucht.
- Fehler werfen `SonosifyError` und beenden mit Exit-Code `1` (siehe
  `runtime.async_command`). Ein Agent kann also grundsätzlich auf Erfolg/Fehler
  branchen.
- `config set --room` erlaubt einen Default-Speaker, sodass Folgeaufrufe kürzer
  werden.

Der Rest des Dokuments ist eine priorisierte Wunschliste.

---

## P0 – Blocker für zuverlässige Agent-Nutzung

### 1. Maschinenlesbare Fehler (JSON-Errors auf stderr)

Aktuell druckt `async_command` bei jedem Fehler `error: <text>` als **Plaintext**
auf stderr – auch bei `--format json`. Ein Agent, der stdout als JSON parst, bekommt
im Fehlerfall ein leeres stdout und muss einen unstrukturierten String von stderr
raten.

**Vorschlag:** Bei `--format json` einen JSON-Error-Envelope auf stderr ausgeben:

```json
{"error": "no speaker matching 'Kitcen'", "code": "speaker_not_found", "query": "Kitcen"}
```

Die Fehlerklassen dafür existieren bereits (`SpeakerNotFoundError`,
`AmbiguousSpeakerError` mit `matches`, `UPnPError` mit `code`/`description`,
`DiscoveryError`). Diese Struktur sollte 1:1 nach außen durchgereicht werden –
besonders `AmbiguousSpeakerError.matches`, damit der Agent selbst disambiguieren
kann, statt den Fehlertext zu parsen.

### 2. Differenzierte Exit-Codes

Heute ist alles `0` oder `1`. Ein Agent kann „Speaker nicht gefunden“ (→ neu
`discover`) nicht von „Netzwerk-Timeout“ (→ retry) oder „UPnP lehnt Aktion ab“
(→ nicht retrybar) unterscheiden, ohne Text zu parsen.

**Vorschlag:** Stabile Exit-Codes je Fehlerklasse, z. B.
`2` = Speaker nicht gefunden, `3` = mehrdeutig, `4` = Discovery/Timeout,
`5` = UPnP-Fehler. Einmal dokumentiert = robuste Retry-Logik ohne Text-Parsing.

### 3. Discovery-Caching / echtes Discovery-Bypass bei `--ip`

`SonosSystem.client()` löst auch mit `--ip` erst eine volle SSDP-Discovery aus
(`controller.client` ruft `discover()`, dann `find(ip=...)`). Für einen Agent, der
10 Kommandos nacheinander absetzt, bedeutet das 10× SSDP-Roundtrip inkl. Timeout-
Wartezeit. Das ist der größte Latenz-Killer.

**Vorschlag (eines oder beide):**
- Bei `--ip` die Discovery komplett überspringen und direkt mit dem Gerät sprechen
  (die meisten Kommandos brauchen nur IP/Port, nicht die ganze Topologie).
- Einen persistenten Speaker-Cache anbieten: `discover` schreibt Room→IP/UID in die
  Config; Folgekommandos lösen Namen aus dem Cache auf und fallen nur bei Miss auf
  SSDP zurück. Optional `--refresh`, um den Cache zu erzwingen.

### 4. `watch` ist für Agents unbrauchbar (nur `Ctrl+C`)

`watch` streamt endlos und endet nur per `CancelledError`. Ein Agent über Bash hat
keine saubere Möglichkeit, den Prozess zu beenden, und bekommt Rich-formatierte
Zeilen statt Daten.

**Vorschlag:** Selbst-terminierende Modi plus NDJSON:
- `--count N` – nach N Events beenden.
- `--duration 10s` / `--timeout` – nach Zeit X beenden.
- `--until playing` – beenden, sobald ein Zielzustand erreicht ist (ideal, um auf
  „Track ist wirklich gestartet“ zu warten).
- Bei `--format json` **eine JSON-Zeile pro Event** (NDJSON), damit ein Agent den
  Stream zeilenweise konsumieren kann.

---

## P1 – Fehlende Kommandos (Library kann es, CLI nicht)

Diese Fähigkeiten sind in `SonosClient` bereits implementiert, aber nicht über die
CLI erreichbar. Sie freizuschalten ist billig und schaltet viel Agent-Nutzen frei.

### 5. Ein-Aufruf-Statusabfrage (`status`)

Für „Was ist gerade los?“ muss ein Agent heute `now-playing` **und** `volume`
**und** `mute` einzeln aufrufen – jeweils mit eigener Discovery. Ein kombiniertes
`sonosify status Kitchen --format json` mit `{state, volume, muted, track, group,
position_s, duration_s}` in einem Aufruf spart Roundtrips und ist der häufigste
Read-Case überhaupt.

### 6. Gruppen-Steuerung (`join` / `unjoin` existieren schon)

`client.join()` / `client.unjoin()` sind da, aber es gibt kein CLI-Kommando.
Multiroom ist eines der attraktivsten „coole Dinge“, die ein Agent machen können
sollte:

```
sonosify group "Living Room" --with Kitchen --with Office   # Gruppe bilden
sonosify ungroup Kitchen                                    # aus Gruppe lösen
sonosify groups --format json                               # aktuelle Gruppen anzeigen
```

`SonosSystem.groups` liefert die Daten für `groups` bereits.

### 7. Queue-Management (`clear_queue`, `remove_queue_item`, `seek_queue`)

Alle drei existieren im Client, keines in der CLI:

```
sonosify queue clear Kitchen
sonosify queue remove Kitchen 4      # Item an Position 4 entfernen
sonosify queue jump Kitchen 7        # zu Queue-Position 7 springen (seek_queue)
```

Ohne `jump`/`seek_queue` kann ein Agent nicht gezielt einen Track aus der Queue
starten – ein sehr naheliegender Wunsch.

### 8. In-Track-Seek

`seek_queue` springt Tracks, aber Position innerhalb eines Tracks (REL_TIME) fehlt
ganz. `sonosify seek Kitchen 1:30` ist ein Standard-Feature, das Agents erwarten.

---

## P2 – Neue Fähigkeiten für „coole“ Agent-Szenarien

Diese SOAP-Aktionen sind noch nicht in der Library, aber niedrig hängende Früchte
mit hohem Demo-Wert:

### 9. Play-Modi: Shuffle / Repeat / Crossfade (`SetPlayMode`)

```
sonosify shuffle Kitchen on
sonosify repeat Kitchen all      # off | one | all
sonosify crossfade Kitchen on
```

Ermöglicht „Party-Modus“-Automationen.

### 10. Sleep-Timer (`ConfigureSleepTimer`)

```
sonosify sleep Kitchen 30m        # in 30 Minuten ausschalten
sonosify sleep Kitchen off
```

Klassisches „mach das autonom für mich“-Feature.

### 11. Batch-/Gruppen-Targeting

```
sonosify pause --all              # alle Coordinators pausieren
sonosify set-volume 20 --group "Living Room"
```

Erspart dem Agent, erst zu `discover`-en und dann pro Speaker zu iterieren.

### 12. `doctor` / `ping`

Ein schneller Reachability-Check pro Speaker (`sonosify ping Kitchen`, Exit-Code
+ Latenz), damit ein Agent vor einer Aktionskette weiß, ob das Gerät online ist –
statt einen ungünstigen Timeout mitten in der Sequenz zu erwischen.

---

## P3 – Ergonomie & Konsistenz (reduziert Agent-Fehler)

### 13. Einheitliches Targeting über alle Kommandos

Momentan ist die Konvention gemischt:
- `play`, `pause`, `volume`, `now-playing` nehmen den Room als **positionales**
  Argument.
- `open`, `track`, `enqueue` nehmen ihn als `--room/-r`-**Option** (positional ist
  dort die URI).

Für einen Agent, der Kommandos generativ zusammensetzt, ist diese Uneinheitlichkeit
eine Fehlerquelle. **Jedes** Kommando sollte `--room` und `--ip` als Optionen
akzeptieren (zusätzlich zum bestehenden positionalen Room, wo vorhanden). Dann gibt
es eine Form, die überall funktioniert:

```
sonosify <cmd> ... --room Kitchen
```

### 14. Überladenes `volume` entschärfen

`volume Kitchen 25` vs. `volume 25` (wobei `25` mal Room, mal Level ist) ist per
`int()`-Heuristik geraten. Ein Room, der zufällig numerisch heißt, oder ein Tippo
führt zu still falschem Verhalten. **Vorschlag:** explizite Kommandos
`get-volume` / `set-volume` (oder `volume get` / `volume set`) als eindeutige,
agent-freundliche Form – die bestehende Kurzform kann für Menschen bleiben.

### 15. Globale Optionen auch *nach* dem Subcommand erlauben

`--format`, `--timeout`, `--debug` müssen aktuell **vor** dem Subcommand stehen
(Typer-Callback). Agents setzen Flags oft ans Ende. Beides zu akzeptieren (oder die
Reihenfolge klar zu dokumentieren) vermeidet stille Parse-Fehler.

### 16. Env-Var-Konfiguration

Neben der JSON-Config wären Umgebungsvariablen für ephemere Agent-Umgebungen ideal:
`SONOSIFY_ROOM`, `SONOSIFY_IP`, `SONOSIFY_FORMAT`, `SONOSIFY_TIMEOUT`. Damit kann ein
Agent den Kontext setzen, ohne eine Datei in ein plattformspezifisches Config-
Verzeichnis zu schreiben. Präzedenz: explizites Flag > Env > Config-Datei.

### 17. Numerische Felder im JSON numerisch halten

`now-playing` gibt `position`/`duration` als Strings wie `"0:01:23"` aus. Für
Fortschritts-/Prozentrechnung sollte JSON zusätzlich `position_s`/`duration_s` als
Integer-Sekunden liefern. Generell: im JSON-Modus `coordinator`/`muted` als echte
Booleans, Zahlen als Zahlen – nicht als Strings.

### 18. Strikte stdout/stderr-Trennung zusichern

Für Scripting muss garantiert sein: **nur Nutzdaten** auf stdout, **alle**
Meldungen/Logs/Statuszeilen auf stderr. Das gilt insbesondere für `watch`
(`"watching ...; press Ctrl+C"` gehört auf stderr) und `--debug`. Dann kann ein
Agent stdout bedenkenlos in einen JSON-Parser pipen.

---

## P4 – Discoverability der CLI selbst

### 19. Maschinenlesbare Kommando-Introspektion

Ein Agent, der die CLI zum ersten Mal sieht, kennt nur `--help` (Prosa). Ein
`sonosify commands --format json`, das alle Kommandos mit Argumenten, Optionen und
Kurzbeschreibung als JSON auflistet, würde einem Agent erlauben, sein Repertoire
selbst zu ermitteln, statt Hilfetexte zu parsen.

### 20. `--version` maschinenlesbar

`sonosify --version` (und im JSON-Modus `{"version": "..."}`) hilft einem Agent,
Feature-/Schema-Verfügbarkeit zu prüfen, bevor er ein Kommando riskiert.

### 21. JSON-Ausgabe-Schema dokumentieren & stabil halten

Sobald Agents auf die JSON-Shapes bauen, ist deren Stabilität ein Vertrag. Ein
kurzer Abschnitt in der README, der pro Kommando die JSON-Felder festschreibt (und
ein `schema_version`-Feld), macht die CLI langfristig agent-tauglich.

---

## Kurz-Priorisierung

| Prio | Punkt | Nutzen |
|------|-------|--------|
| P0 | JSON-Errors + Exit-Codes (1, 2) | Robuste Fehlerbehandlung ohne Text-Parsing |
| P0 | Discovery-Cache / `--ip`-Bypass (3) | Größter Latenzgewinn bei Kommandoketten |
| P0 | `watch` mit `--count`/`--until`/NDJSON (4) | Events überhaupt agent-konsumierbar |
| P1 | `status` in einem Aufruf (5) | Häufigster Read-Case, weniger Roundtrips |
| P1 | Gruppen- & Queue-Kommandos (6, 7, 8) | Library kann es schon – nur freischalten |
| P2 | Shuffle/Repeat/Sleep/`--all` (9–11) | „Coole“ Automationen mit hohem Demo-Wert |
| P3 | Einheitliches Targeting & Env-Vars (13–16) | Weniger generierte Fehlaufrufe |

---

## Implementierungsupdate (23. Juli 2026)

Die Wunschliste wurde vollständig umgesetzt. Der aktuelle Stand umfasst:

- strukturierte JSON-Fehler auf stderr mit `schema_version`, stabilen Fehlercodes,
  Ambiguitäts-Matches und differenzierten Exit-Codes `1` bis `5`;
- direkten Zugriff ohne SSDP bei `--ip`, einen durch `discover` gepflegten
  Room→IP/UID-Cache und `discover --refresh`;
- selbstterminierendes `watch` mit `--count`, `--duration`, `--until` und NDJSON;
- `status` mit Playback, Lautstärke, Mute, Track, Gruppe sowie numerischen
  `position_s`/`duration_s`;
- `group`, `ungroup`, `groups`, `queue clear/remove/jump` und In-Track-`seek`;
- die neuen Library- und CLI-Fähigkeiten Shuffle, Repeat, Crossfade und Sleep-Timer;
- Batch-Operationen über `pause --all` und `set-volume --group`;
- `ping` und `doctor` mit Erreichbarkeit und Latenz;
- einheitliches `--room`/`--ip`-Targeting bei allen Speaker-Kommandos sowie die
  expliziten Kommandos `get-volume`/`set-volume`;
- globale Optionen vor oder nach dem Subcommand und Konfiguration über
  `SONOSIFY_ROOM`, `SONOSIFY_IP`, `SONOSIFY_FORMAT`, `SONOSIFY_TIMEOUT` und
  `SONOSIFY_DEBUG`;
- strikte stdout/stderr-Trennung, typstabile JSON-Werte und den dokumentierten
  JSON-Vertrag mit `schema_version: 1`;
- rekursive Maschinen-Introspektion über `commands --format json` sowie
  `--version` einschließlich JSON-Ausgabe.

Die README dokumentiert die geänderten CLI-Aufrufe, JSON-Envelopes, Fehler- und
Exit-Code-Verträge, Umgebungsvariablen und die hinzugekommenen Python-APIs. Die
Tests wurden auf die neuen Verträge erweitert; beim Abschlusslauf bestanden
183 Tests, Ruff-Lint und Ruff-Formatprüfung.
