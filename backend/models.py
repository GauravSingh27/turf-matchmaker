import uuid
from datetime import datetime
from sqlalchemy import Column, String, Integer, Float, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from database import Base

class Match(Base):
    __tablename__ = "matches"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    sport = Column(String, default="Football")
    city_area = Column(String, nullable=False)
    turf_name = Column(String, nullable=False)
    match_date = Column(String, nullable=False)
    time_slot = Column(String, nullable=False)
    split_type = Column(String, nullable=False)          # '50-50' or 'LOSER_PAYS'
    format_type = Column(String, default="5v5")          # '5v5', '6v6', '7v7'
    total_cost = Column(Float, nullable=False)

    # Status: 'OPEN' (seeking opponent) or 'FIXED' (2 teams confirmed)
    status = Column(String, default="OPEN")

    # Team 1: Host Squad
    host_team_name = Column(String, nullable=False)
    host_captain_name = Column(String, nullable=False)
    host_captain_phone = Column(String, nullable=False)

    # Team 2: Challenger Squad (Filled when match is fixed)
    challenger_team_name = Column(String, nullable=True)
    challenger_captain_name = Column(String, nullable=True)
    challenger_captain_phone = Column(String, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)