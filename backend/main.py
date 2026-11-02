from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, Header, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="TurfClash Matchmaker API")

# Allow requests from your frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

LOCAL_TZ = ZoneInfo("Asia/Kolkata")

# Fixture database storage
matches_db: List[Dict[str, Any]] = []

class MatchCreate(BaseModel):
    turf_name: str
    sport: str
    date: str  # Format: "YYYY-MM-DD"
    time: str  # e.g., "19:00 - 20:00" or "19:00"
    host_team: str
    host_contact: str
    stakes: Optional[str] = "50-50"
    slot_confirmed_with_owner: bool

class AcceptMatchPayload(BaseModel):
    challenger_team: str
    challenger_contact: str

def parse_slot_cutoff_time(match_date: str, match_time: str, buffer_minutes: int = 5) -> datetime:
    """
    Parses kickoff time and applies cutoff buffer (default: 5 minutes before kickoff).
    A 19:00 slot expires at 18:55 IST.
    """
    raw = match_time.lower().strip()
    
    # Extract kickoff time (first part if range)
    if "-" in raw:
        start_part = raw.split("-")[0].strip()
    elif "to" in raw:
        start_part = raw.split("to")[0].strip()
    else:
        start_part = raw

    # Pad single digit hours
    if len(start_part.split(":")[0]) == 1:
        start_part = f"0{start_part}"

    kickoff_dt = datetime.strptime(f"{match_date} {start_part}", "%Y-%m-%d %H:%M").replace(tzinfo=LOCAL_TZ)
    return kickoff_dt - timedelta(minutes=buffer_minutes)

@app.post("/api/matches", status_code=status.HTTP_201_CREATED)
def host_match(match: MatchCreate):
    # Enforce venue verification terms
    if not match.slot_confirmed_with_owner:
        raise HTTPException(
            status_code=400, 
            detail="You must confirm you have checked slot availability with the turf owner."
        )

    # Server-side validation against expired slots (must be >= 5 mins before kickoff)
    try:
        cutoff_dt = parse_slot_cutoff_time(match.date, match.time, buffer_minutes=5)
        if cutoff_dt <= datetime.now(LOCAL_TZ):
            raise HTTPException(
                status_code=400, 
                detail="Matches must be hosted at least 5 minutes before kickoff time."
            )
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date/time format.")

    match_dict = match.model_dump()
    match_dict["id"] = len(matches_db) + 1
    match_dict["status"] = "OPEN"
    match_dict["challenger_team"] = None
    match_dict["challenger_contact"] = None

    matches_db.append(match_dict)
    return {"message": "Fixture posted successfully", "match": match_dict}

@app.get("/api/matches")
def get_matches(x_user_phone: Optional[str] = Header(None)):
    now = datetime.now(LOCAL_TZ)
    visible_matches = []
    viewer_phone = str(x_user_phone or "").strip()

    for match in matches_db:
        # Check auto-expiry (5 minutes before start time)
        try:
            cutoff_dt = parse_slot_cutoff_time(match["date"], match["time"], buffer_minutes=5)
            if match.get("status") == "OPEN" and cutoff_dt <= now:
                match["status"] = "EXPIRED"
                continue
        except Exception:
            pass

        if match.get("status") in ["EXPIRED", "CANCELLED"]:
            continue

        m = dict(match)
        host_phone = str(m.get("host_contact", "")).strip()
        challenger_phone = str(m.get("challenger_contact", "")).strip()

        # Check host ownership for cancel button display
        m["is_host"] = bool(viewer_phone and viewer_phone == host_phone)

        # Contact privacy for confirmed matches
        if m.get("status") in ["FIXED", "CONFIRMED"]:
            is_host = viewer_phone and (viewer_phone == host_phone)
            is_challenger = viewer_phone and (viewer_phone == challenger_phone)

            if is_host:
                m["opponent_phone"] = challenger_phone
                m["can_chat"] = True
            elif is_challenger:
                m["opponent_phone"] = host_phone
                m["can_chat"] = True
            else:
                m["can_chat"] = False
                m.pop("host_contact", None)
                m.pop("challenger_contact", None)
                m.pop("opponent_phone", None)
        else:
            # Hide host phone on open listing until match is accepted
            m["can_chat"] = False
            if not m["is_host"]:
                m.pop("host_contact", None)

        visible_matches.append(m)

    return visible_matches

@app.post("/api/matches/{match_id}/accept")
def accept_match(match_id: int, payload: AcceptMatchPayload):
    target_match = next((m for m in matches_db if m.get("id") == match_id), None)
    if not target_match:
        raise HTTPException(status_code=404, detail="Match not found.")

    # Guard: Cannot accept within the 5 minutes prior to kickoff or after
    now = datetime.now(LOCAL_TZ)
    cutoff_dt = parse_slot_cutoff_time(target_match["date"], target_match["time"], buffer_minutes=5)
    if cutoff_dt <= now:
        target_match["status"] = "EXPIRED"
        raise HTTPException(
            status_code=400, 
            detail="Registration closed: challenges must be accepted at least 5 minutes before kickoff."
        )

    if target_match.get("status") != "OPEN":
        raise HTTPException(status_code=400, detail="Match is no longer open for challenges.")

    target_match["status"] = "CONFIRMED"
    target_match["challenger_team"] = payload.challenger_team
    target_match["challenger_contact"] = payload.challenger_contact

    return {"message": "Challenge accepted! Match is locked.", "match": target_match}

@app.delete("/api/matches/{match_id}")
def cancel_match(match_id: int, x_user_phone: Optional[str] = Header(None)):
    viewer_phone = str(x_user_phone or "").strip()
    if not viewer_phone:
        raise HTTPException(status_code=401, detail="Phone verification required to cancel.")

    target_match = next((m for m in matches_db if m.get("id") == match_id), None)
    if not target_match:
        raise HTTPException(status_code=404, detail="Match not found.")

    if target_match.get("status") != "OPEN":
        raise HTTPException(status_code=400, detail="Only unclaimed open fixtures can be cancelled.")

    if str(target_match.get("host_contact", "")).strip() != viewer_phone:
        raise HTTPException(status_code=403, detail="Only the hosting squad can cancel this challenge.")

    target_match["status"] = "CANCELLED"
    matches_db.remove(target_match)

    return {"message": "Fixture cancelled successfully."}