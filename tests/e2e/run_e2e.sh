#!/bin/bash
# Full-stack browser test: MariaDB + FastAPI + stand-in Ollama + static frontend + headless Chromium.
set -u
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
bash /tmp/runmaria.sh
mysql -uroot -e "DROP DATABASE IF EXISTS synuser_e2e; CREATE DATABASE synuser_e2e CHARACTER SET utf8mb4; GRANT ALL ON synuser_e2e.* TO 'syn'@'127.0.0.1'; GRANT ALL ON synuser_e2e.* TO 'syn'@'localhost'; FLUSH PRIVILEGES;"
rm -f /tmp/fake_ollama_fail
export DATABASE_URL="mysql+pymysql://syn:synpass@127.0.0.1:3307/synuser_e2e" OLLAMA_BASE_URL="http://127.0.0.1:11555" OLLAMA_MODEL="qwen3:1.7b"
pkill -f "fake_ollama[.]py"; pkill -f "uvicorn app[.]main"; pkill -f "http[.]server 5500"; sleep 1
python3 "$ROOT/tests/e2e/fake_ollama.py" 11555 >/tmp/fake_ollama.log 2>&1 &
(cd "$ROOT/backend" && python3 -m uvicorn app.main:app --port 8000 >/tmp/uvicorn.log 2>&1 &)
(cd "$ROOT" && python3 -m http.server 5500 >/tmp/http.log 2>&1 &)
for i in $(seq 1 30); do curl -sf localhost:8000/health >/dev/null && break; sleep 1; done
curl -s localhost:8000/health; echo
python3 "$ROOT/tests/e2e/e2e.py"; RC=$?
echo "--- uvicorn log (errors only) ---"; grep -i -E "error|traceback" /tmp/uvicorn.log | head
pkill -f "fake_ollama[.]py"; pkill -f "uvicorn app[.]main"; pkill -f "http[.]server 5500"
exit $RC
