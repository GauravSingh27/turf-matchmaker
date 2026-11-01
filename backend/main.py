from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from typing import List, Optional

import models
import schemas
from database import engine, get_db

models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="Turf Clash Squad Matchmaking API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/matches", response_model=List[schemas.MatchResponse])
def get_matches(
    status: Optional[str] = Query("OPEN"),
    area: Optional[str] = None,
    sport: Optional[str] = None,
    db: Session = Depends(get_db)
):
    query = db.query(models.Match)
    if status and status != "All":
        query = query.filter(models.Match.status == status)
    if area and area != "All":
        query = query.filter(models.Match.city_area == area)
    if sport and sport != "All":
        query = query.filter(models.Match.sport == sport)
    return query.order_by(models.Match.created_at.desc()).all()

@app.post("/api/matches", response_model=schemas.MatchResponse)
def host_open_challenge(data: schemas.MatchCreate, db: Session = Depends(get_db)):
    match = models.Match(
        sport=data.sport,
        city_area=data.city_area,
        turf_name=data.turf_name,
        match_date=data.match_date,
        time_slot=data.time_slot,
        split_type=data.split_type,
        format_type=data.format_type,
        total_cost=data.total_cost,
        status="OPEN",
        host_team_name=data.host_team_name,
        host_captain_name=data.host_captain_name,
        host_captain_phone=data.host_captain_phone
    )
    db.add(match)
    db.commit()
    db.refresh(match)
    return match

# When Team 2 accepts the challenge, the match becomes FIXED
@app.post("/api/matches/{match_id}/accept", response_model=schemas.MatchResponse)
def accept_challenge(match_id: str, challenge: schemas.ChallengeAccept, db: Session = Depends(get_db)):
    match = db.query(models.Match).filter(models.Match.id == match_id).first()
    if not match:
        raise HTTPException(status_code=404, detail="Fixture not found")
    if match.status == "FIXED":
        raise HTTPException(status_code=400, detail="Match is already fixed with another opponent")

    # Lock in Team 2
    match.challenger_team_name = challenge.challenger_team_name
    match.challenger_captain_name = challenge.challenger_captain_name
    match.challenger_captain_phone = challenge.challenger_captain_phone
    match.status = "FIXED"

    db.commit()
    db.refresh(match)
    return match