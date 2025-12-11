from datetime import datetime
from typing import Optional, Any
from sqlalchemy import Column, Integer, String, DateTime, JSON, Text
from sqlalchemy.orm import declarative_base

Base = declarative_base()

class Job(Base):
    """
    Represents a video generation job.
    """
    __tablename__ = "jobs"

    id = Column(Integer, primary_key=True, index=True)
    status = Column(String, default="pending", index=True)
    niche = Column(String, nullable=True)
    topic_hint = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    metadata_json = Column(JSON, nullable=True, name="metadata")  # 'metadata' is reserved in Base

    def __repr__(self):
        return f"<Job(id={self.id}, status={self.status})>"
