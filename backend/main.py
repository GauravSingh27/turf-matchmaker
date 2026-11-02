import os
from typing import Optional, Dict
from datetime import datetime
from pydantic import BaseModel
from fastapi import FastAPI, HTTPException, Header, Query
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="TurfClash API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory storage (or SQLite if connected)
matches_db = []

# Reputation registry keyed by 10-digit phone number:
# phone -> {"completed": int, "no_shows": int, "disputes": int}
REPUTATION_DB: Dict[str, dict] = {}

class MatchCreate(BaseModel):
    turf_name: str
    sport: str
    date: str
    time: str
    host_team: str
    host_contact: str
    stakes: str
    slot_confirmed_with_owner: bool
    turf_phone: Optional[str] = ""

class MatchAccept(BaseModel):
    challenger_team: str
    challenger_contact: str

class ReportSubmit(BaseModel):
    verdict: str  # "COMPLETED", "NO_SHOW", "DISPUTED"

def get_reliability_stats(phone: str) -> dict:
    clean = "".join(filter(str.isdigit, str(phone)))[-10:] if phone else ""
    stats = REPUTATION_DB.get(clean, {"completed": 0, "no_shows": 0, "disputes": 0})
    total = stats["completed"] + stats["no_shows"] + stats["disputes"]
    
    if total == 0:
        return {"badge": "New Squad", "score": None, "no_shows": 0, "total": 0, "banned": False}
    
    score = int((stats["completed"] / total) * 100)
    is_banned = (stats["no_shows"] + stats["disputes"]) >= 2

    if is_banned:
        badge = f"⛔ Suspended ({stats['no_shows']} No-Shows)"
    elif stats["no_shows"] > 0:
        badge = f"⚠️ {score}% Reliable ({stats['no_shows']} No-Show)"
    else:
        badge = f"🛡️ {score}% Reliable ({stats['completed']} matches)"

    return {
        "badge": badge,
        "score": score,
        "no_shows": stats["no_shows"],
        "total": total,
        "banned": is_banned
    }

@app.get("/api/matches")
def get_matches(x_user_phone: Optional[str] = Header(None)):
    user_phone_clean = "".join(filter(str.isdigit, str(x_user_phone)))[-10:] if x_user_phone else ""
    output = []
    
    for m in matches_db:
        h_phone = "".join(filter(str.isdigit, str(m.get("host_contact", ""))))[-10:]
        c_phone = "".join(filter(str.isdigit, str(m.get("challenger_contact", ""))))[-10:] if m.get("challenger_contact") else ""

        is_host = (user_phone_clean == h_phone) and bool(user_phone_clean)
        is_challenger = (user_phone_clean == c_phone) and bool(user_phone_clean)
        is_participant = is_host or is_challenger

        opponent_phone = None
        if is_host:
            opponent_phone = c_phone
        elif is_challenger:
            opponent_phone = h_phone

        output.append({
            "id": m["id"],
            "turf_name": m["turf_name"],
            "turf_phone": m.get("turf_phone", ""),
            "sport": m["sport"],
            "date": m["date"],
            "time": m["time"],
            "host_team": m["host_team"],
            "host_stats": get_reliability_stats(h_phone),
            "stakes": m["stakes"],
            "status": m["status"],
            "challenger_team": m.get("challenger_team"),
            "challenger_stats": get_reliability_stats(c_phone) if c_phone else None,
            "is_host": is_host,
            "can_chat": is_participant and (m["status"] in ["CONFIRMED", "FIXED"]),
            "can_report": is_participant and (m["status"] in ["CONFIRMED", "FIXED"]),
            "has_reported": user_phone_clean in m.get("reported_by", []),
            "opponent_phone": opponent_phone
        })
    return output

@app.post("/api/matches")
def create_match(match: MatchCreate):
    h_phone = "".join(filter(str.isdigit, str(match.host_contact)))[-10:]
    stats = get_reliability_stats(h_phone)
    if stats["banned"]:
        raise HTTPException(status_code=403, detail="Your number is suspended due to multiple reported no-shows.")

    new_match = {
        "id": len(matches_db) + 1,
        "turf_name": match.turf_name,
        "turf_phone": match.turf_phone or "",
        "sport": match.sport,
        "date": match.date,
        "time": match.time,
        "host_team": match.host_team,
        "host_contact": h_phone,
        "stakes": match.stakes,
        "slot_confirmed_with_owner": match.slot_confirmed_with_owner,
        "status": "OPEN",
        "challenger_team": None,
        "challenger_contact": None,
        "reported_by": []
    }
    matches_db.append(new_match)
    return {"message": "Challenge created", "match": new_match}

@app.post("/api/matches/{match_id}/accept")
def accept_match(match_id: int, body: MatchAccept):
    c_phone = "".join(filter(str.isdigit, str(body.challenger_contact)))[-10:]
    stats = get_reliability_stats(c_phone)
    if stats["banned"]:
        raise HTTPException(status_code=403, detail="Your number is suspended due to multiple reported no-shows.")

    target = next((m for m in matches_db if m["id"] == match_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="Match not found")
    if target["status"] != "OPEN":
        raise HTTPException(status_code=400, detail="Match already locked or expired")

    target["challenger_team"] = body.challenger_team
    target["challenger_contact"] = c_phone
    target["status"] = "CONFIRMED"
    return {"message": "Match accepted", "match": target}

@app.post("/api/matches/{match_id}/report")
def report_match(match_id: int, report: ReportSubmit, x_user_phone: Optional[str] = Header(None)):
    user_phone = "".join(filter(str.isdigit, str(x_user_phone)))[-10:] if x_user_phone else ""
    if not user_phone:
        raise HTTPException(status_code=401, detail="Phone header required")

    target = next((m for m in matches_db if m["id"] == match_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="Match not found")

    h_phone = target["host_contact"]
    c_phone = target.get("challenger_contact")

    if user_phone not in [h_phone, c_phone]:
        raise HTTPException(status_code=403, detail="Only playing captains can rate this match")

    if user_phone in target.get("reported_by", []):
        raise HTTPException(status_code=400, detail="You already submitted feedback for this fixture")

    # Target being reported is the opponent
    opponent_target_phone = c_phone if user_phone == h_phone else h_phone
    if not opponent_target_phone:
        raise HTTPException(status_code=400, detail="No opponent found to rate")

    if opponent_target_phone not in REPUTATION_DB:
        REPUTATION_DB[opponent_target_phone] = {"completed": 0, "no_shows": 0, "disputes": 0}

    if report.verdict == "COMPLETED":
        REPUTATION_DB[opponent_target_phone]["completed"] += 1
    elif report.verdict == "NO_SHOW":
        REPUTATION_DB[opponent_target_phone]["no_shows"] += 1
    elif report.verdict == "DISPUTED":
        REPUTATION_DB[opponent_target_phone]["disputes"] += 1

    target.setdefault("reported_by", []).append(user_phone)
    return {"message": "Fair Play review logged successfully"}