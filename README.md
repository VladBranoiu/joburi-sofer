# Joburi șofer: Prahova + București

Strânge zilnic anunțurile de șofer de pe **eJobs, BestJobs și OLX** (Prahova, Ilfov, București),
le dă un scor și le afișează într-o pagină cu filtre.

- `./actualizeaza.sh` descarcă anunțurile noi (3–6 minute; descrierile se țin în cache).
- `index.html` se deschide în browser. Din Windows: `\\wsl$\Ubuntu\home\vladb\apps\soferi-joburi\index.html`,
  sau din WSL cu `explorer.exe index.html`.
- `config.json` conține firmele preferate, localitățile apropiate, bonusurile pe zone și cursul EUR.

## Cum se calculează scorul (pornește de la 50, limitat la 0–100)
| Criteriu | Puncte |
|---|---|
| Prahova lângă Ploiești / restul Prahovei | +15 / +10 |
| Ilfov nord (Otopeni, Chitila…) / restul Ilfovului | +8 / +5 |
| București oraș (nu periferie) | −6 |
| Distribuție locală, acasă zilnic / curse prin țară | +15 / +3 |
| Camion C/CE | +3 |
| Program de zi, L–V / noapte, weekend | +8 / −12 |
| Ajutor la descărcat / descarcă singur | +3 / −4 |
| Abonament medical / tichete de masă | +4 / +2 |
| Salariu net ≥7000 / ≥6000 / ≥5000 / ≥4000 / <3500 lei | +12 / +9 / +6 / +2 / −6 |
| Firmă preferată / agenție de recrutare | +8 / −6 |
| Nota angajaților pe UndeLucram ≥4 / ≥3,5 / ≥3 / ≥2,5 / mai mică (jumătate dacă are sub 5 păreri) | +8 / +4 / 0 / −6 / −10 |
| Nota clienților pe Google (doar cu cheie API) | ±2 |
| Anunț mai vechi de 45 de zile | −4 |

Verdict: **Foarte potrivit** ≥80, **Potrivit** ≥65, **Merită verificat** ≥50, **Slab** sub 50 (ascuns).
Excluse automat: curse în străinătate, doar categoria B, transport persoane.

## Recenzii firme
- **UndeLucram.ro**: nota angajaților, numărul de păreri. Se caută automat după numele firmei și se reîmprospătează la 30 de zile.
  Comentariile de acolo se văd doar cu cont, așa că pagina dă link spre ele.
  Dacă o firmă e legată greșit, se corectează în `config.json` → `recenzii_potrivire_manuala` (id UndeLucram sau `"nu"`).
- **Google Maps** (opțional): nota clienților și ultimele 5 comentarii prin API-ul oficial Google Places.
  Pune cheia în `config.json` → `google_places_api_key`, apoi rulează `python3 colector.py recenzii --fortat`.

## Comenzi
- `python3 colector.py`: totul (anunțuri + recenzii)
- `python3 colector.py recenzii --fortat`: reface recenziile
- `python3 colector.py reclasifica`: recalculează scorurile după o schimbare de reguli, fără descărcări

Salvatele, aplicările și notițele stau în browser (localStorage); „Setări avansate” → „Salvează notițele” face o copie.
Indeed și Jooble blochează accesul automat, așa că nu sunt incluse.

## Online
- Site: https://vladbranoiu.github.io/joburi-sofer/ (GitHub Pages, din branch-ul `main`).
- **GitHub Actions** (`.github/workflows/actualizare.yml`) rulează zilnic la 04:00 UTC: eJobs, BestJobs și recenziile.
  Se poate porni și manual din tabul Actions → „Actualizare anunțuri” → Run workflow.
- **OLX blochează serverele GitHub**, așa că OLX se actualizează de pe PC: sarcina Windows „Joburi sofer - OLX”
  (zilnic la 10:00 și la logare) rulează `sincronizare-olx.sh` într-o copie separată (`~/.local/share/joburi-sofer-sync`).
  Jurnal: `~/.local/share/joburi-sofer-sync.log`. Dacă PC-ul stă oprit, anunțurile OLX dispar treptat în 14 zile, iar restul merge normal.
- Înainte să modifici ceva local: `git pull` (datele se schimbă zilnic pe GitHub).
