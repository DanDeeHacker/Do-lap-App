"""A persona's findings become notes in Team Console → Inbox (owner request 2026-10-27). Staging
sends them to production, where the team triages (DOSSLAP_PERSONA_REPORT_URL + the shared
DOSSLAP_PERSONA_TOKEN); without it (locally, in tests) they are filed in the same database.
The receiving side (team.ingest_synthetic) dedupes, caps and reopens; nothing here carries real
data — the personas are made up."""
import hashlib
import os

import httpx

from .. import team as T


def fingerprint(f: dict) -> str:
    return hashlib.sha1(f"{f['check']}|{f['route']}|{f.get('key') or ''}".encode()).hexdigest()[:16]


def payload(key: str, findings: list, sim_date: str, passed=(), source: str = "synthetic") -> dict:
    items = [{"fingerprint": fingerprint(f), "check": f["check"], "route": f["route"], "title": f["title"][:200],
              "detail": (f.get("detail") or "")[:1500], "type": f.get("type") or "bug", "persona": key, "simDate": sim_date}
             for f in findings]
    return {"items": items[:20], "passed": sorted(set(passed)), "persona": key, "source": source}


def file(db, key: str, findings: list, sim_date: str, passed=(), source: str = "synthetic") -> dict:
    body = payload(key, findings, sim_date, passed, source)
    if not body["items"] and not body["passed"]:
        return {}
    url = os.environ.get("DOSSLAP_PERSONA_REPORT_URL")
    if url:
        try:
            r = httpx.post(url.rstrip("/") + "/api/team/synthetic-notes", json=body, timeout=15,
                           headers={"X-Persona-Token": os.environ.get("DOSSLAP_PERSONA_TOKEN", "")})
            return r.json() if r.status_code == 200 else {"error": f"HTTP {r.status_code}"}
        except (httpx.HTTPError, ValueError) as e:
            return {"error": type(e).__name__}
    return T.ingest_synthetic(db, body)
