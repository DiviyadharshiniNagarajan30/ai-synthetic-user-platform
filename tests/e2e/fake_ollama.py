"""Minimal stand-in for Ollama's HTTP API (/api/tags, /api/chat) used ONLY for automated end-to-end tests
on machines without a model. It is NOT an LLM: answers are canned text. Create the file named by
FAIL_FLAG to make /api/chat return HTTP 500 (to test error handling)."""
import json, os, random, re, sys, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

FAIL_FLAG = os.getenv("FAKE_OLLAMA_FAIL_FLAG", "/tmp/fake_ollama_fail")
NAMES = ["Kavya Menon", "Rohan Mehta", "Lakshmi Iyer", "Imran Sheikh", "Deepa Nair", "Vikram Rao", "Sunita Patil", "Arjun Das", "Fatima Khan", "Ganesh Pillai"]
GOALS = ["Build an emergency fund", "Pay off the car loan early", "Save for a daughter's wedding", "Expand the shop next year",
         "Stop overspending on food delivery", "Plan retirement income", "Buy a laptop for work", "Track farm input costs", "Save for a trip", "Invest monthly"]
PAINS = ["Forgets subscription renewals", "Income varies every month", "Business and personal spending mixed", "No time to log expenses",
         "Confusing bank statements", "Prices keep rising", "Cash payments go untracked", "Hard to stick to a budget", "Too many apps", "Unexpected medical bills"]
counter = {"n": 0}

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, code, obj):
        body = json.dumps(obj).encode(); self.send_response(code)
        self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
    def do_GET(self):
        if self.path == "/api/tags": self._send(200, {"models": [{"name": "qwen3:1.7b"}]})
        else: self._send(404, {})
    def do_POST(self):
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if os.path.exists(FAIL_FLAG): return self._send(500, {"error": "simulated failure"})
        time.sleep(0.4)
        msgs = payload["messages"]; user = msgs[-1]["content"]; system = msgs[0]["content"] if msgs[0]["role"] == "system" else ""
        if payload.get("format") == "json" and "ONE fictional synthetic user persona" in user:
            counter["n"] += 1; i = counter["n"]
            occ = re.search(r"- Occupation: (.+)", user); age = re.search(r"- Age: (\d+)", user)
            occ = occ.group(1).strip() if occ and "choose one" not in occ.group(1) else "Shop owner"
            content = json.dumps({"name": NAMES[i % 10], "age": int(age.group(1)) if age else 30 + i, "occupation": occ, "income": 20000 + i * 7000,
                "location": "Chennai, India", "experience_level": "beginner", "personality": "Practical and cautious",
                "goals": GOALS[i % 10], "preferences": "Simple dashboards and reminders", "pain_points": PAINS[i % 10], "research_interests": "Budgeting"})
        elif payload.get("format") == "json":
            content = json.dumps({"summary": "Participants want automatic tracking and reminders.", "themes": ["automation", "reminders"],
                "needs": ["automatic categorisation"], "preferences": ["simple UI"], "pain_points": ["manual entry"], "recommendations": ["ship reminders first"]})
        else:
            name = re.search(r"Name: (.+)", system); name = name.group(1) if name else "the persona"
            q = [l for l in user.splitlines() if l.startswith("Question:")]; q = q[0][9:].strip() if q else user
            content = f"As {name}, regarding \"{q[:70]}\": I need simple tracking, automatic categories and gentle reminders. " + "I often lose track of small purchases. " * 3
        self._send(200, {"message": {"role": "assistant", "content": content}})

if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1]) if len(sys.argv) > 1 else 11555), H).serve_forever()
