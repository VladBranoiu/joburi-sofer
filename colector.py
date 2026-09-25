#!/usr/bin/env python3
"""Strânge anunțuri de șofer din eJobs, BestJobs și OLX pentru Prahova + București/Ilfov,
caută reputația firmelor (UndeLucram, opțional Google), dă fiecărui anunț un scor și
salvează totul în data/joburi.json + data/joburi.js (citit de index.html).

Rulare: python3 colector.py              (toate sursele + recenzii)
        python3 colector.py ejobs olx    (doar unele surse)
        python3 colector.py recenzii     (doar reîmprospătează recenziile)
Doar biblioteca standard Python + curl.
"""
import html
import json
import re
import subprocess
import sys
import time
import unicodedata
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
CACHE = DATA / "cache"
CFG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")
EUR = CFG["curs_eur_ron"]
NOW_DT = datetime.now(timezone.utc)
NOW = NOW_DT.isoformat(timespec="seconds")


# ---------------------------------------------------------------- utilitare

def fetch(url, as_json=True, retries=2, data=None, headers=(), cookies=None):
    """GET/POST prin curl (OLX blochează clientul HTTP din Python, dar acceptă curl)."""
    cmd = ["curl", "-sS", "-L", "--compressed", "--max-time", "30", "-A", UA,
           "-H", "Accept-Language: ro-RO,ro;q=0.9", "-w", "\n%{http_code}"]
    for h in headers:
        cmd += ["-H", h]
    if cookies:
        cmd += ["-b", str(cookies), "-c", str(cookies)]
    if data is not None:
        cmd += ["-H", "Content-Type: application/json", "--data-binary", json.dumps(data)]
    for incercare in range(retries + 1):
        r = subprocess.run(cmd + [url], capture_output=True, text=True, encoding="utf-8", errors="replace")
        body, _, code = r.stdout.rpartition("\n")
        time.sleep(CFG["pauza_intre_cereri_sec"])
        if r.returncode == 0 and code.startswith("2"):
            return json.loads(body) if as_json else body
        err = f"HTTP {code}" if r.returncode == 0 else r.stderr.strip()
        if incercare == retries:
            raise RuntimeError(f"{err} la {url[:90]}")
        print(f"   ! reîncerc ({err})")
        time.sleep(3)


def fara_diacritice(s, lower=True):
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.lower() if lower else s


def text_din_html(s):
    s = re.sub(r"<(br|/p|/li|/div|li|/h\d)[^>]*>", "\n", s or "", flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    s = re.sub(r"[ \t\xa0]+", " ", s)
    return re.sub(r"\n\s*\n+", "\n", s).strip()


def cache_get(key, loader, max_zile=None):
    f = CACHE / (re.sub(r"[^a-zA-Z0-9_-]", "_", key) + ".json")
    if f.exists() and (max_zile is None or time.time() - f.stat().st_mtime < max_zile * 86400):
        return json.loads(f.read_text(encoding="utf-8"))
    val = loader()
    f.write_text(json.dumps(val, ensure_ascii=False), encoding="utf-8")
    return val


def zile_de_la(iso):
    try:
        return (NOW_DT - datetime.fromisoformat(iso.replace("Z", "+00:00"))).days
    except (ValueError, AttributeError):
        return None


# ------------------------------------------------------------------ salariu

NET_DIN_BRUT = 0.585  # aproximativ, pentru salarii mici/medii în 2026


def parse_salariu(text):
    """'4000 - 4500 RON' / '750 - 1200 EUR' / '2800 - 3000 €/luna' -> (min, max) în lei net, sau (None, None)."""
    if not text:
        return None, None
    t = text.replace(".", "").replace("\xa0", " ")
    if re.search(r"/\s*(ora|h\b|zi\b)|pe (ora|zi)\b", fara_diacritice(t)):
        return None, None  # plată pe oră / pe zi: nu o putem compara corect
    nums = [int(n.replace(" ", "")) for n in re.findall(r"\d{1,2} \d{3}|\d{3,6}", t)]
    if not nums:
        return None, None
    lo, hi = min(nums[:2]), max(nums[:2])
    eur = bool(re.search(r"eur|€", t, re.I))
    if not eur and not re.search(r"ron|lei", t, re.I) and hi < 1800:
        eur = True  # fără monedă și sumă mică: aproape sigur EUR
    k = EUR if eur else 1
    if re.search(r"brut", t, re.I):
        k *= NET_DIN_BRUT
    lo, hi = round(lo * k), round(hi * k)
    if hi < 2000 or lo > 40000:  # sub salariul minim net sau absurd -> probabil altceva (bonus, diurnă)
        return None, None
    return lo, hi


RE_SAL_DESC = re.compile(
    r"(salari\w*|venit\w*|castig\w*|remunera\w*|oferim|pachet salarial)[^\n]{0,50}?"
    r"(\d{1,2}[. ]?\d{3})(\s*(-|–|pana la|si)\s*(\d{1,2}[. ]?\d{3}))?\s*(lei|ron|euro|eur|€)[^\n]{0,12}")


def salariu_din_descriere(desc):
    m = RE_SAL_DESC.search(fara_diacritice(desc))
    if not m:
        return None, None, ""
    return (*parse_salariu(m.group(0)), m.group(0).strip()[:80])


# ----------------------------------------------------------- clasificare
# Toate regulile lucrează pe text fără diacritice, cu litere mici (în afară de RE_CE).

RE_SOFER = re.compile(r"sofer|conducator auto|driver|camion|\btir\b|autotren|basculant|autospecial|"
                      r"cisterna|agabaritic|trailer|\bc\s*\+\s*e\b")
RE_EXCLUS_TITLU = re.compile(r"dispecer|mecanic|instructor|agent (de )?vanzari|reprezentant|"
                             r"manager|coordonator|consilier|operator call|vulcaniz|electrician|"
                             r"tinichigiu|vopsitor|spalator|ajutor de sofer|insotitor|screwdriver")

TARI = (r"(germania|olanda|belgia|franta|italia|spania|austria|danemarca|suedia|norvegia|elvetia|"
        r"polonia|cehia|anglia|marea britanie|irlanda|luxemburg|finlanda|scandinavia|grecia|ungaria)")
RE_INTERNATIONAL_TITLU = re.compile(r"international|strainatate|comunitate|comunitar|\b(ue|uk)\b|europa|" + TARI)
# în descriere cerem context de transport; altfel prindem „companie elvețiană”, „limbă de circulație internațională”
RE_INTERNATIONAL_DESC = re.compile(
    r"(transport|curse|cursa|trafic|rute?|ruta|sofer)\s+(de marfa\s+|marfa\s+|rutier\s+)?"
    r"(intern\s*(si|/|&)\s*)?(international|comunitar|european|in comunitate|pe comunitate)|"
    r"\bin (ue|uniunea europeana|europa)\b|drumurile (din )?europei?|toata europa|"
    r"\bcomunitate\b|comunitar|sejur|\d+\s*(saptamani|sapt\.?)\s*(pe drum|plecat|in cursa|acasa)|"
    r"dormit in cabina|in cabina|diurna.{0,25}(eur|€)|\d+\s*(eur|euro|€)\s*/\s*zi|"
    r"(locul de munca|munca|lucru|job|angajare|proiecte)\s+(\w+\s+){0,3}in " + TARI + "|"
    r"(curse|rute?|ruta|tranzit\w*|incarcari|descarcari)\s*[:\-]?\s*([\w()]+\s*[-–,/]\s*){0,4}" + TARI)
RE_NEG_INTERNATIONAL = re.compile(r"\b(fara|nu|nici)\s+(\w+\s+){0,3}(comunitate|comunitar\w*|international\w*|"
                                  r"strainatate|tranzit\w*|europa|" + TARI[1:-1] + r")")

RE_LOCAL = re.compile(
    r"acasa (in )?fiecare (zi|seara)|zilnic acasa|in fiecare (zi|seara) acasa|seara acasa|"
    r"(ajunge|ajungi|ajungeti|vii|esti) (\w+ )?(in fiecare zi|zilnic|seara)( \w+)? acasa|"
    r"curse (locale|zilnice|scurte)|distributie|\blocal[ae]?\b|livrari?\b|"
    r"retur in aceeasi zi|fara deplasari|fara (dormit|nopti)|nu (se )?doarme|"
    r"transport(ul)? marfii la domiciliu|la domiciliul clientului|intre depozit|catre magazine")
RE_NATIONAL = re.compile(
    r"curse (lungi|nationale|pe tara|prin tara|in toata tara|interne lungi)|transport national|toata tara|"
    r"\bnational\b|\d+\s*(zile|nopti) (pe drum|plecat|in cursa)|plecari de \d+|\blocal\s*/\s*tara|"
    r"tur[ae]? de \d+ zile|dormit\w* (in|la) cabina|noapte dormita|(transport|curse|rute) pe tara|"
    r"(bucuresti|ilfov|prahova|local\w*) si (in )?tara\b")
RE_INTERN = re.compile(r"curse interne|transport intern|\bintern\b|in tara|regional|prin tara")

RE_PROGRAM_BUN = re.compile(
    r"(de )?luni\s*(-|–|pana)\s*(vineri|vi)|\bl\s*[-–]\s*v\b|lu\s*[-–]\s*vi|weekend(ul|uri)? libere?|"
    r"sambata si duminica liber\w*|\b8 ore\b|program fix|program normal|ture? de zi|program de zi|"
    r"fara ture de noapte|nu (se )?lucreaza (noaptea|in weekend)|"
    r"\b0?[5-8][:.]?[03]0\s*[-–]\s*1[4-8][:.]?[03]0\b")
RE_PROGRAM_RAU = re.compile(
    r"(tura|ture|program) de noapte|\bnoaptea\b|12\s*/\s*24|24\s*/\s*48|12\s*/\s*12|"
    r"weekend(ul)? lucr|lucru (si )?in weekend|sambata (lucr|inclus)|program prelungit|"
    r"disponibilitate.{0,30}(weekend|noapte|ore suplimentare)|ture de 12")
RE_NEG_PROGRAM = re.compile(r"\b(fara|nu (se )?(lucreaza|lucram|lucrezi|lucra)|nu|exclus)\s+(\w+\s+){0,3}"
                            r"(noapte|noaptea|weekend\w*|sambata|duminica)")

RE_GREU = re.compile(r"descarcare manuala|manipulare manuala|incarcare manuala|hamal|efort fizic|"
                     r"\bcarat\b|manipularea marfii|descarcarea marfii|incarcarea si descarcarea")
RE_HELPER = re.compile(r"\bhelper\b|cu ajutor\b|insotit de (un )?ajutor|echipaj de 2|descarcarea se face de|"
                       r"fara (descarcare|manipulare)|nu (se )?descarc|descarcare cu (liza|motostivuitor|lopata)")
RE_ABONAMENT = re.compile(r"abonament (medical|la clinica|de sanatate)|asigurare (medicala|de sanatate)|"
                          r"servicii medicale|clinica privata")
RE_TICHETE = re.compile(r"tichete|bonuri de masa|card de masa|tichet de masa")
RE_AGENTIE = re.compile(r"recru|work ?force|work agency|\bagency\b|\bagentie\b|staff|resources|"
                        r"human|\bhr\b|\bpersonal\b|consult|\bjobs?\b|plasare|outsourc|interim")

RE_CAT_C = re.compile(
    r"\bc\s*\+\s*e\b|\bbce\b|\bb\s*[,+/]\s*c\b|\bc\s*[,/]\s*(c\s*\+\s*)?e\b|\bc\s*si\s*(c\s*\+\s*)?e\b|"
    r"categ(ori(a|ile|e))?\.?\s*:?\s*(b\s*[,+/]?\s*(si\s*)?)?c\d?\b|\bcat\.?\s*(b\s*[,+/]\s*)?c\d?\b|"
    r"permis(ul)?\s*(de conducere\s*)?(categoria\s*)?(b\s*[,+/]\s*)?c\d?\b|"
    r"camion|\btir\b|autotren|semiremorc|basculant|autospecial|cisterna|cap tractor|autocamion|"
    r"\b(7[.,]5|12|16|18|19|24|26|40)\s*(t|to|tone)\b|\bc1\b|(categori\w*|cat\.?|permis)\s*c\s*e\b")
# pe textul cu majuscule: „CE”/„C+E” e categoria, „ce” e cuvânt; „CE OFERIM” din titlurile scrise cu majuscule nu e
RE_CE = re.compile(r"\bC\s*\+\s*E\b|\bCE\b(?!\s+(OFERIM|ASTEPTAM|ITI|TREBUIE|CAUTAM|VEI|FACI|AVEM|NE|"
                   r"PRESUPUNE|IMPLICA|OFERA|PRIMESTI|CASTIGI|CERINTE|INSEAMNA|DOCUMENTE|FACEM))")
RE_CAT_B = re.compile(r"categ(ori[ae])?\.?\s*b\b|cat\.?\s*b\b|permis\s*(de conducere\s*)?(categoria\s*)?b\b|"
                      r"\bduba\b|furgon|autoutilitar|\b3[.,]5\s*t|curier|\bvan\b")
RE_CAT_D = re.compile(r"autobuz|autocar|microbuz|categori[ae]\s*d\b|cat\.?\s*d\b|transport (de )?persoane|"
                      r"transport pasageri|\btaxi\b|ride.?sharing|\buber\b|\bbolt\b|transport (de )?(copii|elevi)|"
                      r"sofer (de )?protocol|transport(ul)? de protocol|sofer personal|office driver|sofer privat")


def plus(motive, puncte, text):
    motive.append({"p": puncte, "t": text})
    return puncte


def clasifica(job, firme):
    """Adaugă tip, permis, etichete, motive (cu puncte), scor și `exclus`.
    Folosește titlul + descrierea anunțului (nu și descrierea firmei) + reputația firmei."""
    titlu = fara_diacritice(job["titlu"])
    desc = fara_diacritice(job.get("descriere", ""))
    txt = titlu + "\n" + desc
    txt_mare = fara_diacritice(job["titlu"] + "\n" + job.get("descriere", ""), lower=False)
    orase = set().union(set(), *(_bucati(o) for o in job.get("orase", [])))

    etichete, motive = [], []
    scor = 50

    # --- zona
    apropiat = bool(orase & APROPIATE)
    z = {("prahova", True): (15, "Prahova, aproape de Ploiești"), ("prahova", False): (10, "Prahova"),
         ("ilfov", True): (8, "Ilfov, pe partea dinspre Prahova"), ("ilfov", False): (5, "Ilfov (lângă București)"),
         ("bucuresti", True): (-6, "În București, nu la periferie"), ("bucuresti", False): (-6, "În București, nu la periferie")}[
        (job["zona"], apropiat)]
    scor += plus(motive, *z)

    # --- tipul cursei
    desc_fara_negatii = RE_NEG_INTERNATIONAL.sub(" ", desc)
    m_int = RE_INTERNATIONAL_TITLU.search(titlu) or RE_INTERNATIONAL_DESC.search(desc_fara_negatii)
    exclus = None
    if m_int or "strainatate" in orase:
        tip = "international"
        exclus = "curse în străinătate"
        scor += plus(motive, -40, f"Curse în străinătate („{m_int.group(0)[:40] if m_int else 'străinătate'}”)")
    elif RE_LOCAL.search(txt) and not RE_NATIONAL.search(txt):
        tip = "local"
        scor += plus(motive, 15, "Distribuție locală, acasă în fiecare seară")
    elif RE_NATIONAL.search(txt) or RE_INTERN.search(txt):
        tip = "intern"
        scor += plus(motive, 3, "Curse prin țară (poate dormi și pe drum)")
    else:
        tip = "necunoscut"
        plus(motive, 0, "Anunțul nu spune clar dacă e local sau prin țară")

    # --- permis
    are_c = bool(RE_CAT_C.search(txt) or RE_CE.search(txt_mare))
    if RE_CAT_D.search(titlu) or (RE_CAT_D.search(desc) and not are_c):
        permis = "D"
        exclus = exclus or "transport persoane"
        scor += plus(motive, -30, "E pentru transport de persoane (autobuz, taxi, protocol)")
    elif are_c:
        permis = "C/CE"
        scor += plus(motive, 3, "Camion (C / C+E), cum are el permis")
    elif RE_CAT_B.search(txt):
        permis = "B"
        exclus = exclus or "doar categoria B (dubă)"
        scor += plus(motive, -10, "Doar dubă (categoria B), plătit de obicei mai slab")
    else:
        permis = "?"

    # --- program
    bune = {m.group(0) for m in RE_PROGRAM_BUN.finditer(txt)}
    rele = {m.group(0) for m in RE_PROGRAM_RAU.finditer(RE_NEG_PROGRAM.sub(" ", txt))}
    if bune:
        etichete.append("program bun")
        scor += plus(motive, 8, "Program de zi / L–V („" + ", ".join(sorted(bune))[:60] + "”)")
    if rele:
        etichete.append("noapte/weekend")
        scor += plus(motive, -12, "Se lucrează și noaptea sau în weekend („" + ", ".join(sorted(rele))[:60] + "”)")

    # --- efort, beneficii
    if RE_HELPER.search(txt):
        etichete.append("are ajutor la descărcat")
        scor += plus(motive, 3, "Are ajutor la încărcat/descărcat")
    elif RE_GREU.search(txt):
        etichete.append("efort fizic")
        scor += plus(motive, -4, "Încarcă/descarcă marfa singur (efort fizic)")
    if RE_ABONAMENT.search(txt):
        etichete.append("abonament medical")
        scor += plus(motive, 4, "Abonament medical / asigurare de sănătate")
    if RE_TICHETE.search(txt):
        etichete.append("tichete de masă")
        scor += plus(motive, 2, "Tichete de masă")

    # --- salariu (lei net pe lună)
    lo, hi = job.get("sal_min"), job.get("sal_max")
    if hi:
        pct = 12 if hi >= 7000 else 9 if hi >= 6000 else 6 if hi >= 5000 else 2 if hi >= 4000 else \
            0 if hi >= 3500 else -6
        sursa = " (scris în descriere)" if job.get("sal_din_descriere") else ""
        scor += plus(motive, pct, f"Salariu {lo}–{hi} lei net{sursa}" if lo != hi else f"Salariu {hi} lei net{sursa}")
    else:
        plus(motive, 0, "Salariul nu e scris în anunț")

    # --- firma
    firma_n = fara_diacritice(job.get("firma", ""))
    preferat = next((f for f in CFG["firme_preferate"]
                     if re.search(r"\b" + re.escape(fara_diacritice(f)) + r"\b", firma_n + " " + titlu)), None)
    if preferat:
        etichete.append("firmă preferată")
        scor += plus(motive, 8, f"Firmă din lista preferată ({preferat.title()})")
    elif job.get("firma_confirmata") and RE_AGENTIE.search(firma_n):
        etichete.append("agenție")
        scor += plus(motive, -6, "Agenție de recrutare, nu angajatorul direct")

    rep = firme.get(cheie_firma(job.get("firma", ""))) if job.get("firma_confirmata") else None
    ul = (rep or {}).get("undelucram") or {}
    if ul.get("nota") and ul.get("evaluari"):
        n, e = ul["nota"], ul["evaluari"]
        pct = 8 if n >= 4.0 else 4 if n >= 3.5 else 0 if n >= 3.0 else -6 if n >= 2.5 else -10
        if e < 5:
            pct = round(pct / 2)
        scor += plus(motive, pct, f"Angajații dau firmei nota {n:.1f} din 5 ({e} păreri pe UndeLucram)".replace(".", ",", 1))
    g = (rep or {}).get("google") or {}
    if g.get("nota") and g.get("evaluari", 0) >= 10:
        pct = 2 if g["nota"] >= 4.5 else -2 if g["nota"] < 3.5 else 0
        scor += plus(motive, pct, f"Clienții dau nota {g['nota']:.1f} pe Google ({g['evaluari']} recenzii)".replace(".", ",", 1))

    # --- vechimea anunțului
    zile = zile_de_la(job.get("reimprospatat") or job.get("publicat") or job.get("prima_data") or NOW)
    if zile is not None and zile > 45:
        scor += plus(motive, -4, f"Anunț vechi ({zile} zile), poate e deja ocupat")

    scor = max(0, min(100, scor))
    verdict = "Foarte potrivit" if scor >= 80 else "Potrivit" if scor >= 65 else \
        "Merită verificat" if scor >= 50 else "Slab"
    job.update(tip=tip, permis=permis, etichete=etichete, motive=motive, scor=scor,
               verdict=verdict, exclus=exclus)
    return job


# ------------------------------------------------------------ localități

PRAHOVA = {fara_diacritice(x) for x in CFG["localitati_prahova"]}
ILFOV = {fara_diacritice(x) for x in CFG["localitati_ilfov"]}
APROPIATE = {fara_diacritice(x) for x in CFG["localitati_apropiate"]}


def _bucati(o):
    # „Strada Aurel Vlaicu 9, Otopeni, România” -> toate bucățile, ca să prindem și adresele complete
    return {p.strip() for p in fara_diacritice(o).split(",")}


def zona_din_orase(orase):
    nume = set().union(set(), *(_bucati(o) for o in orase))
    if nume & PRAHOVA or any("prahova" in n for n in nume):
        return "prahova"
    if nume & ILFOV or any("ilfov" in n for n in nume):
        return "ilfov"
    if any(n.startswith(("bucuresti", "sector")) for n in nume):
        return "bucuresti"
    return None


def marcheaza_dubluri(joburi):
    """Același anunț postat de mai multe ori (alt oraș / altă sursă): păstrăm unul, restul primesc `dublura_lui`."""
    grupe = {}
    for j in joburi:
        j.pop("dublura_lui", None)
        if not j["activ"]:
            continue
        cheie = re.sub(r"[^a-z0-9]", "", fara_diacritice(j["titlu"]))[:60] + "|" + cheie_firma(j["firma"])[:12]
        grupe.setdefault(cheie, []).append(j)
    for grup in grupe.values():
        grup.sort(key=lambda j: (-j["scor"], j["id"]))
        grup[0]["si_in"] = sorted({o for j in grup[1:] for o in j["orase"]} - set(grup[0]["orase"]))[:10]
        grup[0]["alte_surse"] = sorted({j["sursa"] for j in grup[1:]} - {grup[0]["sursa"]})
        for j in grup[1:]:
            j["dublura_lui"] = grup[0]["id"]


def e_job_de_sofer(titlu):
    t = fara_diacritice(titlu)
    return bool(RE_SOFER.search(t)) and not RE_EXCLUS_TITLU.search(t)


def completeaza_salariu(job):
    """Dacă anunțul nu are salariu în câmpul dedicat, îl căutăm în descriere."""
    job["sal_din_descriere"] = False
    if not job.get("sal_max"):
        lo, hi, txt = salariu_din_descriere(job.get("descriere", ""))
        if hi:
            job.update(sal_min=lo, sal_max=hi, salariu_text=txt, sal_din_descriere=True)
    return job


# ----------------------------------------------------------------- surse

def sursa_ejobs():
    api = "https://api.ejobs.ro"
    statics = cache_get("ejobs_statics", lambda: fetch(f"{api}/all-statics"), max_zile=30)["ro"]
    orase = {c["id"]: c for c in statics["cities"]}
    zona_judet = {38: "prahova", 17: "ilfov", 10: "bucuresti"}
    # API-ul dă puține rezultate pe căutare, așa că împărțim pe județ × cuvânt cheie
    cautari = ["q=sofer", "q=conducator%20auto", "q=camion", "q=sofer%20profesionist",
               "q=sofer%20distributie", "q=sofer%20tir", "q=driver", "filters.departments=40"]

    vazute, rezultate = set(), []
    for judet in zona_judet:
        for extra in cautari:
            page = 1
            while page <= 10:
                try:
                    d = fetch(f"{api}/jobs?page={page}&pageSize=50&{extra}&filters.counties={judet}",
                              retries=0 if page > 1 else 2)
                except Exception:  # noqa: BLE001 - API-ul dă 404 după ultima pagină
                    if page == 1:
                        raise
                    break
                for j in d.get("jobs", []):
                    if j["id"] in vazute:
                        continue
                    vazute.add(j["id"])
                    if not e_job_de_sofer(j["title"]):
                        continue
                    locs = [orase.get(l["cityId"], {}) for l in j.get("locations", [])]
                    zone = [zona_judet[l["countyId"]] for l in locs if l.get("countyId") in zona_judet]
                    if not zone:
                        continue
                    zona = "prahova" if "prahova" in zone else "ilfov" if "ilfov" in zone else "bucuresti"
                    rezultate.append((j, [l.get("name", "?") for l in locs], zona))
                if not d.get("morePagesFollow"):
                    break
                page += 1
        print(f"   eJobs județ {judet}: total {len(rezultate)} relevante")

    joburi = []
    for j, nume_orase, zona in rezultate:
        det = cache_get(f"ejobs_{j['id']}", lambda: fetch(f"{api}/jobs/{j['id']}?viewedFromMobile=false"))
        dd = det.get("details", {}) or {}
        # descrierea firmei rămâne pe dinafară: pomenește des „transport internațional” generic
        desc = text_din_html("\n".join(v for k, v in dd.items()
                                       if isinstance(v, str) and k != "companyDescription"))
        lo, hi = parse_salariu(j.get("salary"))  # eJobs afișează salariul net
        joburi.append({
            "id": f"ejobs:{j['id']}", "sursa": "eJobs", "titlu": j["title"].strip(),
            "firma": (j.get("company") or {}).get("name", ""), "firma_confirmata": True,
            "orase": nume_orase, "zona": zona,
            "url": f"https://www.ejobs.ro/user/locuri-de-munca/{j['slug']}/{j['id']}",
            "salariu_text": j.get("salary") or "", "sal_min": lo, "sal_max": hi,
            "publicat": j.get("creationDate"), "expira": j.get("expirationDate"),
            "descriere": desc[:4000],
        })
    return joburi


def sursa_bestjobs():
    api = "https://api.bestjobs.eu/v2/jobs"
    gasite = {}
    for loc in CFG["cuvinte_cautare"]["bestjobs_locatii"]:
        for kw in CFG["cuvinte_cautare"]["bestjobs"]:
            cursor, pagini = None, 0
            while pagini < 10:
                q = {"limit": 24, "locale": "ro", "keyword": kw, "location[]": loc}
                if cursor:
                    q["cursor"] = cursor
                d = fetch(api + "?" + urllib.parse.urlencode(q))
                items = d.get("items", [])
                for it in items:
                    if it["id"] not in gasite and e_job_de_sofer(it["title"]):
                        gasite[it["id"]] = it
                pagini += 1
                cursor = d.get("nextCursor")
                if not items or not cursor:
                    break
        print(f"   BestJobs {loc}: total {len(gasite)} relevante")

    joburi = []
    for jid, it in gasite.items():
        orase = [l["name"].replace(", România", "") for l in it.get("locations", [])]
        zona = zona_din_orase(orase)
        if not zona:
            continue  # căutarea BestJobs întoarce și joburi din alte județe / remote
        def incarca():
            s = fetch(f"https://www.bestjobs.eu/ro/loc-de-munca/{it['slug']}", as_json=False)
            m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', s, re.S)
            j = json.loads(m.group(1))["props"]["pageProps"].get("job", {}) if m else {}
            return {"description": j.get("description", ""), "salary": j.get("salary", "")}
        try:
            det = cache_get(f"bestjobs_{jid}", incarca)
        except Exception as e:  # noqa: BLE001
            print(f"   ! detalii BestJobs {jid}: {e}")
            det = {"description": "", "salary": ""}
        sal_text = det.get("salary") or it.get("salary") or ""
        lo, hi = parse_salariu(sal_text)
        joburi.append({
            "id": f"bestjobs:{jid}", "sursa": "BestJobs", "titlu": it["title"].strip(),
            "firma": it.get("companyName", ""), "firma_confirmata": True,
            "orase": orase[:8], "zona": zona,
            "url": f"https://www.bestjobs.eu/ro/loc-de-munca/{it['slug']}",
            "salariu_text": sal_text, "sal_min": lo, "sal_max": hi,
            "publicat": None, "expira": None,
            "descriere": text_din_html(det.get("description", ""))[:4000],
        })
    return joburi


RE_FIRMA_IN_NUME = re.compile(r"\b(srl|s\.r\.l|sa|s\.a|srl-d|pfa|ii|company|group|grup|logistic\w*|"
                              r"transport\w*|trans|distribution|distributie|expres\w*|impex|com)\b")


def sursa_olx():
    api = "https://www.olx.ro/api/v1/offers/"
    regiuni = {6: "prahova", 46: "bucuresti"}
    joburi, vazute = [], set()
    for rid, zona in regiuni.items():
        for query in ["", "sofer", "conducator auto"]:
            offset = 0
            while offset < 1000:
                q = {"offset": offset, "limit": 50, "category_id": 1500, "region_id": rid}
                if query:
                    q["query"] = query
                d = fetch(api + "?" + urllib.parse.urlencode(q))
                data = d.get("data", [])
                for o in data:
                    if o["id"] in vazute or not e_job_de_sofer(o["title"]):
                        continue
                    vazute.add(o["id"])
                    params = {p["key"]: p.get("value") for p in o.get("params", [])}
                    sal = params.get("salary") or {}
                    lo = hi = None
                    sal_text = ""
                    if sal and not sal.get("arranged") and sal.get("type") not in ("hourly", "daily"):
                        k = NET_DIN_BRUT if sal.get("gross") else 1
                        lo = round((sal.get("converted_from") or sal.get("from") or 0) * k) or None
                        hi = round((sal.get("converted_to") or sal.get("to") or 0) * k) or lo
                        lo = lo or hi
                        sal_text = f"{sal.get('from')} - {sal.get('to')} {sal.get('currency')}" + \
                                   (" brut" if sal.get("gross") else " net")
                        if not hi or hi < 2000:
                            lo = hi = None
                    permis = (params.get("permis_de_conducere") or {}).get("label") or ""
                    program = (params.get("program_demunca") or {}).get("label") or ""
                    city = o["location"].get("city", {}).get("name", "")
                    z = zona if rid == 6 else (zona_din_orase([city]) or "ilfov")
                    desc = text_din_html(o.get("description", ""))
                    if permis:
                        desc = f"Permis cerut: {permis}\n" + desc
                    if program:
                        desc = f"Program: {program}\n" + desc
                    user = o.get("user") or {}
                    firma = user.get("company_name") or user.get("name") or ""
                    confirmata = bool(user.get("company_name")) or bool(RE_FIRMA_IN_NUME.search(fara_diacritice(firma)))
                    joburi.append({
                        "id": f"olx:{o['id']}", "sursa": "OLX", "titlu": o["title"].strip(),
                        "firma": firma, "firma_confirmata": confirmata,
                        "orase": [city], "zona": z, "url": o["url"],
                        "salariu_text": sal_text, "sal_min": lo, "sal_max": hi,
                        "publicat": o.get("created_time"), "reimprospatat": o.get("last_refresh_time"),
                        "expira": o.get("valid_to_time"), "descriere": desc[:4000],
                    })
                if len(data) < 50:
                    break
                offset += 50
        print(f"   OLX {zona}: total {len(joburi)} relevante")
    return joburi


SURSE = {"ejobs": sursa_ejobs, "bestjobs": sursa_bestjobs, "olx": sursa_olx}


# --------------------------------------------------------------- recenzii

CUVINTE_JURIDICE = {"sc", "srl", "sa", "srld", "pfa", "com", "impex", "group", "grup", "romania",
                    "holding", "the", "si", "and", "co", "company", "international", "distribution",
                    "distributie", "rom", "prod", "ro", "ltd", "gmbh"}
# cuvinte care pot lipsi dintr-un nume fără să fie altă firmă
CUVINTE_EXTRA_OK = {"romania", "express", "expres", "trading", "retail", "logistic", "logistics", "services",
                    "service", "prodcom", "2", "exclusive", "global", "europe", "eu", "import", "export",
                    "corporation", "corp", "systems", "solutions", "industries", "industrial"}

def cheie_firma(nume):
    t = re.sub(r"\(.*?\)", " ", fara_diacritice(nume))
    for _ in range(3):  # „L.E.D”, „S.R.L.” -> „led”, „srl”
        t = re.sub(r"\b([a-z])\.(?=[a-z]\b)", r"\1", t)
    cuv = [w for w in re.findall(r"[a-z0-9]+", t) if w not in CUVINTE_JURIDICE]
    return " ".join(cuv)


class UndeLucram:
    BASE = "https://www.undelucram.ro/ro"

    def __init__(self):
        self.cookies = CACHE / "undelucram_cookies.txt"
        self.token = None

    def _token(self):
        if not self.token:
            s = fetch(self.BASE, as_json=False, cookies=self.cookies)
            m = re.search(r'name="csrf-token" content="([^"]+)"', s)
            if not m:
                raise RuntimeError("UndeLucram: nu găsesc tokenul de sesiune")
            self.token = m.group(1)
        return self.token

    def cauta(self, text):
        return fetch(f"{self.BASE}/autocomplete/organisations",
                     data={"value": text, "with_link": True, "with_id": True},
                     headers=[f"X-CSRF-TOKEN: {self._token()}", "X-Requested-With: XMLHttpRequest"],
                     cookies=self.cookies) or []

    def pagina(self, url, nume):
        """Nota, numărul de evaluări și % recomandări de pe pagina publică a firmei."""
        s = fetch(url, as_json=False)
        t = re.sub(r"<script.*?</script>|<style.*?</style>", "", s, flags=re.S)
        t = re.sub(r"\s*\n\s*", "\n", html.unescape(re.sub(r"<[^>]+>", "\n", t)))
        # pagina are și o listă laterală „Rating mai bun în industrie” cu notele ALTOR firme:
        # tăiem tot ce e după ea și cerem ca nota să vină imediat după numele firmei
        t = t.split("Rating mai bun")[0]
        # două formate: „Nume\n4,06\n786 evaluări” sau „Nume\n4,06\n80% recomandă…\n786\nEvaluări”
        m = re.search(r"\n" + re.escape(nume.strip()) + r"\n(\d,\d{1,2})\n(?:(\d+)% recomand[^\n]*\n)?(\d+)(?: evalu|\nEvalu)", t)
        return {"nota": float(m.group(1).replace(",", ".")) if m else None,
                "evaluari": int(m.group(3)) if m else 0,
                "recomanda_pct": int(m.group(2)) if m and m.group(2) else None,
                "url": re.sub(r"/prezentare-", "/evaluari-", url)}

    def potriveste(self, nume_firma, id_manual=None):
        cheie = cheie_firma(nume_firma)
        cuv = cheie.split()
        if not cuv:
            return None
        rezultate = self.cauta(" ".join(cuv[:2]))
        if len(cuv) > 1 and not rezultate:
            rezultate = self.cauta(cuv[0])
        candidati = []
        for r in rezultate:
            if id_manual and r.get("id") != id_manual:
                continue
            ck = cheie_firma(r["name"]).split()
            if not ck:
                continue
            comune = set(cuv) & set(ck)
            jac = len(comune) / len(set(cuv) | set(ck))
            # cuvintele în plus (de o parte sau alta) trebuie să fie generice: „Altex” ~ „Altex Romania”,
            # dar nu „Continental Fast Line” ~ „Continental Romania” sau „Profit Impex” ~ „Profit Point”
            extra_generice = (set(cuv) ^ set(ck)) <= CUVINTE_EXTRA_OK
            ok = bool(id_manual) or (len(cheie) >= 4 and (
                cheie == " ".join(ck) or jac >= 0.75 or (comune and extra_generice)))
            if ok:
                candidati.append((jac, r))
        if not candidati:
            return None
        # între candidații cu același prim cuvânt (ex. „Aquila Part Prod Com” vs „Aquila Spa”)
        # alegem pe cel mai asemănător, apoi pe cel cu cele mai multe păreri
        candidati.sort(key=lambda x: -x[0])
        detalii = []
        for jac, r in candidati[:3]:
            info = self.pagina(r["link"], r["name"])
            detalii.append((jac, info["evaluari"], r, info))
        detalii.sort(key=lambda x: (-round(x[0], 1), -x[1]))
        jac, _, r, info = detalii[0]
        return {"id": r["id"], "nume": r["name"], **info, "sigur": True}


def google_places(nume, oras):
    """Opțional: nota și ultimele recenzii de pe Google Maps, prin API-ul oficial Places (cheie în config)."""
    cheie = CFG.get("google_places_api_key")
    if not cheie:
        return None
    d = fetch("https://places.googleapis.com/v1/places:searchText",
              data={"textQuery": f"{nume} {oras}", "languageCode": "ro", "regionCode": "RO", "pageSize": 1},
              headers=[f"X-Goog-Api-Key: {cheie}",
                       "X-Goog-FieldMask: places.displayName,places.formattedAddress,places.rating,"
                       "places.userRatingCount,places.googleMapsUri,places.reviews"])
    p = (d.get("places") or [None])[0]
    if not p or not p.get("rating"):
        return None
    return {
        "nume": p.get("displayName", {}).get("text"), "adresa": p.get("formattedAddress"),
        "nota": p["rating"], "evaluari": p.get("userRatingCount", 0), "url": p.get("googleMapsUri"),
        "comentarii": [{"nota": r.get("rating"), "text": (r.get("text") or {}).get("text", "")[:600],
                        "cand": r.get("relativePublishTimeDescription", ""),
                        "autor": (r.get("authorAttribution") or {}).get("displayName", "")}
                       for r in p.get("reviews", [])[:5] if (r.get("text") or {}).get("text")],
    }


def actualizeaza_recenzii(db, fortat=False):
    """Caută reputația fiecărei firme cu anunțuri active. Rezultatele se păstrează 30 de zile."""
    firme = db.setdefault("firme", {})
    manual = {cheie_firma(k): v for k, v in CFG.get("recenzii_potrivire_manuala", {}).items()}
    de_cautat = {}
    for j in db["joburi"].values():
        if j["activ"] and j.get("firma_confirmata") and j.get("firma"):
            de_cautat.setdefault(cheie_firma(j["firma"]), j)
    ul = UndeLucram()
    noi = 0
    for cheie, j in de_cautat.items():
        f = firme.get(cheie) or {}
        vechime = zile_de_la(f.get("verificat_la", "2000-01-01T00:00:00+00:00"))
        if f and vechime < 30 and not fortat:
            continue
        m = manual.get(cheie)
        f = {"nume": j["firma"], "verificat_la": NOW, "undelucram": None, "google": None}
        try:
            if m != "nu":
                f["undelucram"] = ul.potriveste(j["firma"], id_manual=m if isinstance(m, int) else None)
        except Exception as e:  # noqa: BLE001
            print(f"   ! UndeLucram {j['firma']}: {e}")
            f["verificat_la"] = "2000-01-01T00:00:00+00:00"  # reîncercăm data viitoare
        try:
            f["google"] = google_places(j["firma"], (j.get("orase") or [""])[0])
        except Exception as e:  # noqa: BLE001
            print(f"   ! Google {j['firma']}: {e}")
        firme[cheie] = f
        noi += 1
        if noi % 20 == 0:
            print(f"   recenzii: {noi} firme verificate…")
    cu_nota = sum(1 for k in de_cautat if (firme.get(k) or {}).get("undelucram"))
    print(f"   Recenzii: {len(de_cautat)} firme, {cu_nota} găsite pe UndeLucram ({noi} verificate acum)")
    return len(de_cautat)


# ------------------------------------------------------------------ main

def main():
    DATA.mkdir(exist_ok=True)
    CACHE.mkdir(exist_ok=True)
    f_db = DATA / "joburi.json"
    db = json.loads(f_db.read_text(encoding="utf-8")) if f_db.exists() else {"joburi": {}, "rulari": []}

    # „reclasifica” = doar recalculează scorurile pe datele existente, fără descărcări
    alese = [a.lower() for a in sys.argv[1:] if not a.startswith("--")] or list(SURSE) + ["recenzii"]
    stare_surse = {}
    for nume in [a for a in alese if a in SURSE]:
        print(f"→ {nume}")
        try:
            gasite = SURSE[nume]()
        except Exception as e:  # noqa: BLE001
            print(f"   ✗ {nume} a eșuat: {e}")
            stare_surse[nume] = f"eroare: {e}"
            continue
        stare_surse[nume] = len(gasite)
        ids_acum = set()
        for j in gasite:
            vechi = db["joburi"].get(j["id"])
            j["prima_data"] = vechi["prima_data"] if vechi else NOW
            j["ultima_data"] = NOW
            j["activ"] = True
            db["joburi"][j["id"]] = completeaza_salariu(j)
            ids_acum.add(j["id"])
        # ce nu mai apare la o sursă care a mers: expirat dacă i-a trecut data sau nu l-am mai văzut de 14 zile
        # (site-urile nu dau mereu toate rezultatele, deci o singură lipsă nu înseamnă că s-a închis)
        for jid, j in db["joburi"].items():
            if jid.startswith(nume + ":") and jid not in ids_acum:
                expira = (j.get("expira") or "9999")[:10]
                j["activ"] = expira >= NOW[:10] and (zile_de_la(j["ultima_data"]) or 0) < 14

    if "recenzii" in alese:
        print("→ recenzii firme")
        try:
            stare_surse["recenzii"] = actualizeaza_recenzii(db, fortat="--fortat" in sys.argv)
        except Exception as e:  # noqa: BLE001
            print(f"   ✗ recenzii a eșuat: {e}")
            stare_surse["recenzii"] = f"eroare: {e}"

    firme = db.get("firme", {})
    for j in db["joburi"].values():  # reclasificăm tot, ca schimbările de reguli să se aplice și la cele vechi
        clasifica(j, firme)
        j["firma_cheie"] = cheie_firma(j.get("firma", "")) if j.get("firma_confirmata") else None
    marcheaza_dubluri(list(db["joburi"].values()))
    db["rulari"] = (db.get("rulari", []) + [{"data": NOW, "surse": stare_surse}])[-60:]
    db["actualizat"] = NOW
    f_db.write_text(json.dumps(db, ensure_ascii=False, indent=1), encoding="utf-8")
    (DATA / "joburi.js").write_text("window.JOBURI = " + json.dumps(db, ensure_ascii=False) + ";\n",
                                    encoding="utf-8")
    active = [j for j in db["joburi"].values() if j["activ"] and not j.get("dublura_lui") and not j["exclus"]]
    bune = [j for j in active if j["verdict"] == "Foarte potrivit"]
    print(f"\n✓ Gata. {len(active)} anunțuri potrivite, {len(bune)} „foarte potrivite”. Deschide index.html.")


if __name__ == "__main__":
    main()
