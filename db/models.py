from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from datetime import datetime, timezone
import os

DB_PATH = os.getenv("DB_PATH", "marketing.db")
engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class Idea(Base):
    __tablename__ = "ideas"

    id = Column(Integer, primary_key=True, index=True)
    scan_date = Column(String, index=True)           # YYYY-MM-DD
    news_headline = Column(Text)
    news_summary = Column(Text)
    idea_text = Column(Text, nullable=False)
    platform = Column(String)                        # instagram | tiktok | youtube | all
    content_type = Column(String)                    # post | reel | short | story | carousel
    rationale = Column(Text)                         # why this idea fits the brand
    status = Column(String, default="pending")       # pending | approved | rejected
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    content = relationship("Content", back_populates="idea", uselist=False)


class Content(Base):
    __tablename__ = "content"

    id = Column(Integer, primary_key=True, index=True)
    idea_id = Column(Integer, ForeignKey("ideas.id"), nullable=False)
    platform = Column(String)
    content_type = Column(String)                    # post | reel | short | story | carousel
    hook = Column(Text)                              # opening line / first 3 seconds
    copy_text = Column(Text)                         # full caption / body text
    script = Column(Text)                            # video script (reels/shorts)
    hashtags = Column(Text)                          # comma-separated
    cta = Column(Text)                               # call to action
    visual_notes = Column(Text)                      # directions for creative/design
    status = Column(String, default="underreview")   # underreview | approved | published
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    idea = relationship("Idea", back_populates="content")


class NewsScan(Base):
    __tablename__ = "news_scans"

    id = Column(Integer, primary_key=True, index=True)
    scan_date = Column(String)
    articles_fetched = Column(Integer, default=0)
    ideas_generated = Column(Integer, default=0)
    status = Column(String, default="success")       # success | failed
    error_msg = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


def init_db():
    Base.metadata.create_all(bind=engine)
