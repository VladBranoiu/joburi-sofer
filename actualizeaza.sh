#!/usr/bin/env bash
# Actualizează anunțurile (rulat zilnic de cron / Task Scheduler sau manual).
cd "$(dirname "$0")" || exit 1
python3 colector.py > data/ultima_rulare.log 2>&1
tail -1 data/ultima_rulare.log
