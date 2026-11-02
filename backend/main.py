import sqlite3
from typing import Optional
from pydantic import BaseModel
from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="TurfClash API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_PATH = "turf.db"

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS matches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                turf_name TEXT NOT NULL,
                turf_phone TEXT DEFAULT '',
                sport TEXT NOT NULL,
                date TEXT NOT NULL,
                time TEXT NOT NULL,
                host_team TEXT NOT NULL,
                host_captain TEXT NOT NULL DEFAULT '',
                host_contact TEXT NOT NULL,
                stakes TEXT NOT NULL,
                slot_confirmed INTEGER DEFAULT 1,
                status TEXT DEFAULT 'OPEN',
                challenger_team TEXT DEFAULT NULL,
                challenger_captain TEXT DEFAULT NULL,
                challenger_contact TEXT DEFAULT NULL,
                reported_by TEXT DEFAULT ''
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS reputation (
                phone TEXT PRIMARY KEY,
                completed INTEGER DEFAULT 0,
                no_shows INTEGER DEFAULT 0,
                disputes INTEGER DEFAULT 0
            )
        """)
        conn.commit()

init_db()

class MatchCreate(BaseModel):
    turf_name: str
    sport: str
    date: str
    time: str
    host_team: str
    host_captain: str
    host_contact: str
    stakes: str
    slot_confirmed_with_owner: bool
    turf_phone: Optional[str] = ""

class MatchAccept(BaseModel):
    challenger_team: str
    challenger_captain: str
    challenger_contact: str

class ReportSubmit(BaseModel):
    verdict: str

def get_reliability_stats(phone: str) -> dict:
    clean = "".join(filter(str.isdigit, str(phone)))[-10:] if phone else ""
    if not clean:
        return {"badge": "New Squad", "score": None, "no_shows": 0, "total": 0, "banned": False}
    
    with get_db() as conn:
        row = conn.execute("SELECT * FROM reputation WHERE phone = ?", (clean,)).fetchone()
        if not row:
            return {"badge": "New Squad", "score": None, "no_shows": 0, "total": 0, "banned": False}
        
        comp = row["completed"]
        ns = row["no_shows"]
        disp = row["disputes"]
        total = comp + ns + disp

        if total == 0:
            return {"badge": "New Squad", "score": None, "no_shows": 0, "total": 0, "banned": False}

        score = int((comp / total) * 100)
        is_banned = (ns + disp) >= 2

        if is_banned:
            badge = f"⛔ Suspended ({ns} No-Shows)"
        elif ns > 0:
            badge = f"⚠️ {score}% Reliable ({ns} No-Show)"
        else:
            badge = f"🛡️ {score}% Reliable ({comp} matches)"

        return {"badge": badge, "score": score, "no_shows": ns, "total": total, "banned": is_banned}

@app.get("/api/matches")
def get_matches(x_user_phone: Optional[str] = Header(None)):
    user_phone_clean = "".join(filter(str.isdigit, str(x_user_phone)))[-10:] if x_user_phone else ""
    
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM matches ORDER BY id DESC").fetchall()
        output = []
        for r in rows:
            h_phone = r["host_contact"]
            c_phone = r["challenger_contact"] or ""
            reported_list = [p for p in (r["reported_by"] or "").split(",") if p]

            is_host = (user_phone_clean == h_phone) and bool(user_phone_clean)
            is_challenger = (user_phone_clean == c_phone) and bool(user_phone_clean)
            is_participant = is_host or is_challenger

            opponent_phone = c_phone if is_host else (h_phone if is_challenger else None)
            opponent_captain = r["challenger_captain"] if is_host else (r["host_captain"] if is_challenger else None)

            output.append({
                "id": r["id"],
                "turf_name": r["turf_name"],
                "turf_phone": r["turf_phone"],
                "sport": r["sport"],
                "date": r["date"],
                "time": r["time"],
                "host_team": r["host_team"],
                "host_captain": r["host_captain"],
                "host_stats": get_reliability_stats(h_phone),
                "stakes": r["stakes"],
                "status": r["status"],
                "challenger_team": r["challenger_team"],
                "challenger_captain": r["challenger_captain"],
                "challenger_stats": get_reliability_stats(c_phone) if c_phone else None,
                "is_host": is_host,
                "can_chat": is_participant and (r["status"] in ["CONFIRMED", "FIXED"]),
                "can_report": is_participant and (r["status"] in ["CONFIRMED", "FIXED"]),
                "has_reported": user_phone_clean in reported_list,
                "opponent_phone": opponent_phone,
                "opponent_captain": opponent_captain
            })
        return output

@app.post("/api/matches")
def create_match(match: MatchCreate):
    h_phone = "".join(filter(str.isdigit, str(match.host_contact)))[-10:]
    stats = get_reliability_stats(h_phone)
    if stats["banned"]:
        raise HTTPException(status_code=403, detail="Your number is suspended due to multiple reported no-shows.")

    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO matches (
                turf_name, turf_phone, sport, date, time, host_team, 
                host_captain, host_contact, stakes, slot_confirmed, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'OPEN')
        """, (
            match.turf_name,
            match.turf_phone or "",
            match.sport,
            match.date,
            match.time,
            match.host_team,
            match.host_captain,
            h_phone,
            match.stakes,
            1 if match.slot_confirmed_with_owner else 0
        ))
        conn.commit()
        match_id = cur.lastrowid

    return {"message": "Challenge created", "match_id": match_id}

@app.post("/api/matches/{match_id}/accept")
def accept_match(match_id: int, body: MatchAccept):
    c_phone = "".join(filter(str.isdigit, str(body.challenger_contact)))[-10:]
    stats = get_reliability_stats(c_phone)
    if stats["banned"]:
        raise HTTPException(status_code=403, detail="Your number is suspended due to multiple reported no-shows.")

    with get_db() as conn:
        row = conn.execute("SELECT status FROM matches WHERE id = ?", (match_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Match not found")
        if row["status"] != "OPEN":
            raise HTTPException(status_code=400, detail="Match already locked or expired")

        conn.execute("""
            UPDATE matches 
            SET challenger_team = ?, challenger_captain = ?, challenger_contact = ?, status = 'CONFIRMED'
            WHERE id = ?
        """, (body.challenger_team, body.challenger_captain, c_phone, match_id))
        conn.commit()

    return {"message": "Match accepted"}

@app.post("/api/matches/{match_id}/report")
def report_match(match_id: int, report: ReportSubmit, x_user_phone: Optional[str] = Header(None)):
    user_phone = "".join(filter(str.isdigit, str(x_user_phone)))[-10:] if x_user_phone else ""
    if not user_phone:
        raise HTTPException(status_code=401, detail="Phone header required")

    with get_db() as conn:
        row = conn.execute("SELECT * FROM matches WHERE id = ?", (match_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Match not found")

        h_phone = row["host_contact"]
        c_phone = row["challenger_contact"] or ""
        reported_list = [p for p in (row["reported_by"] or "").split(",") if p]

        if user_phone not in [h_phone, c_phone]:
            raise HTTPException(status_code=403, detail="Only playing captains can rate this match")

        if user_phone in reported_list:
            raise HTTPException(status_code=400, detail="Review already submitted")

        target_phone = c_phone if user_phone == h_phone else h_phone
        if not target_phone:
            raise HTTPException(status_code=400, detail="No opponent phone found to review")

        # Update or create reputation
        conn.execute("INSERT OR IGNORE INTO reputation (phone) VALUES (?)", (target_phone,))
        if report.verdict == "COMPLETED":
            conn.execute("UPDATE reputation SET completed = completed + 1 WHERE phone = ?", (target_phone,))
        elif report.verdict == "NO_SHOW":
            conn.execute("UPDATE reputation SET no_shows = no_shows + 1 WHERE phone = ?", (target_phone,))
        elif report.verdict == "DISPUTED":
            conn.execute("UPDATE reputation SET disputes = disputes + 1 WHERE phone = ?", (target_phone,))

        reported_list.append(user_phone)
        conn.execute("UPDATE matches SET reported_by = ? WHERE id = ?", (",".join(reported_list), match_id))
        conn.commit()

    return {"message": "Fair Play review logged successfully"}

@app.delete("/api/matches/{match_id}")
def delete_match(match_id: int, x_user_phone: Optional[str] = Header(None)):
    user_phone = "".join(filter(str.isdigit, str(x_user_phone)))[-10:] if x_user_phone else ""
    with get_db() as conn:
        row = conn.execute("SELECT host_contact, status FROM matches WHERE id = ?", (match_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Match not found")
        if row["host_contact"] != user_phone:
            raise HTTPException(status_code=403, detail="Only host can cancel challenge")
        conn.execute("DELETE FROM matches WHERE id = ?", (match_id,))
        conn.commit()
    return {"message": "Challenge cancelled"}