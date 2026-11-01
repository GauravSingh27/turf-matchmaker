from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime

class MatchCreate(BaseModel):
    sport: str = "Football"
    city_area: str
    turf_name: str
    match_date: str
    time_slot: str
    split_type: str
    format_type: str = "5v5"
    total_cost: float
    host_team_name: str
    host_captain_name: str
    host_captain_phone: str

class ChallengeAccept(BaseModel):
    challenger_team_name: str = Field(..., min_length=2)
    challenger_captain_name: str = Field(..., min_length=2)
    challenger_captain_phone: str = Field(..., min_length=10)

class MatchResponse(BaseModel):
    id: str
    sport: str
    city_area: str
    turf_name: str
    match_date: str
    time_slot: str
    split_type: str
    format_type: str
    total_cost: float
    status: str
    host_team_name: str
    host_captain_name: str
    host_captain_phone: str
    challenger_team_name: Optional[str] = None
    challenger_captain_name: Optional[str] = None
    challenger_captain_phone: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True