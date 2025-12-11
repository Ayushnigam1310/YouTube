from datetime import datetime
from typing import Optional, Any
from sqlalchemy import Column, Integer, String, DateTime, JSON, Text, Boolean
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

class PendingUpload(Base):
    """
    Represents an upload that couldn't be completed immediately.
    """
    __tablename__ = "pending_uploads"

    id = Column(Integer, primary_key=True, index=True)
    video_path = Column(String, nullable=False)
    thumbnail_path = Column(String, nullable=False)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    tags = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<PendingUpload(id={self.id}, title={self.title})>"