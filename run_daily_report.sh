#!/usr/bin/env bash
set -euo pipefail
cd /workspaces/report
python3 report_daily.py --send
