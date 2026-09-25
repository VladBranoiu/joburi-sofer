#!/usr/bin/env bash
# OLX blochează serverele GitHub, așa că anunțurile OLX se iau de pe PC-ul ăsta și se urcă pe site.
# Rulat de Task Scheduler din Windows (zilnic + la pornire). Lucrează într-o copie separată a proiectului.
set -u
REPO_URL="https://github.com/VladBranoiu/joburi-sofer.git"
DIR="$HOME/.local/share/joburi-sofer-sync"
LOG="$HOME/.local/share/joburi-sofer-sync.log"
exec >>"$LOG" 2>&1
echo "=== $(date '+%F %T')"

# o singură rulare pe zi e destul
if [ -f "$DIR/.ultima" ] && [ "$(cat "$DIR/.ultima")" = "$(date +%F)" ]; then echo "deja rulat azi"; exit 0; fi

[ -d "$DIR/.git" ] || git clone -q "$REPO_URL" "$DIR" || exit 1
cd "$DIR" || exit 1
git config user.name "VladBranoiu"
git config user.email "147258209+VladBranoiu@users.noreply.github.com"

for incercare in 1 2 3; do
  git fetch -q origin && git reset -q --hard origin/main || exit 1
  python3 colector.py olx || exit 1
  python3 -c 'import json,sys; s=json.load(open("data/joburi.json"))["rulari"][-1]["surse"]; sys.exit(0 if isinstance(s.get("olx"), int) else 1)' \
    || { echo "OLX a eșuat, nu urc nimic"; exit 1; }
  git add data
  git diff --cached --quiet && { echo "nimic nou"; break; }
  git commit -q -m "Anunțuri OLX actualizate $(date +%F)"
  # dacă între timp a urcat și GitHub ceva, luăm de la capăt pe versiunea nouă
  git push -q origin main && { echo "urcat"; break; }
  echo "push respins, reîncerc ($incercare)"
  sleep 20
done
date +%F > "$DIR/.ultima"
