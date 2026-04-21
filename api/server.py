import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import pytz
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from db.models import init_db, SessionLocal, Idea, Content, NewsScan
from scheduler.jobs import start_scheduler

LIMA_TZ = pytz.timezone("America/Lima")
_scheduler = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _scheduler
    init_db()
    _scheduler = start_scheduler()
    yield
    if _scheduler:
        _scheduler.shutdown(wait=False)


app = FastAPI(title="Marketing Hub", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DASHBOARD = os.path.join(os.path.dirname(__file__), "..", "dashboard")


@app.get("/", response_class=HTMLResponse)
def dashboard():
    path = os.path.join(DASHBOARD, "index.html")
    with open(path, "r") as f:
        return f.read()


# ── Stats ─────────────────────────────────────────────────────────────────────

@app.get("/api/stats")
def get_stats():
    db = SessionLocal()
    try:
        now_lima = datetime.now(LIMA_TZ)
        next_scan = _scheduler.get_job("daily_news_scan").next_run_time if _scheduler else None
        return {
            "pending_ideas": db.query(Idea).filter(Idea.status == "pending").count(),
            "approved_ideas": db.query(Idea).filter(Idea.status == "approved").count(),
            "rejected_ideas": db.query(Idea).filter(Idea.status == "rejected").count(),
            "content_underreview": db.query(Content).filter(Content.status == "underreview").count(),
            "content_approved": db.query(Content).filter(Content.status == "approved").count(),
            "total_scans": db.query(NewsScan).count(),
            "next_scan": next_scan.isoformat() if next_scan else None,
            "lima_time": now_lima.strftime("%Y-%m-%d %H:%M:%S"),
        }
    finally:
        db.close()


# ── Ideas ─────────────────────────────────────────────────────────────────────

@app.get("/api/ideas")
def get_ideas(status: str = "pending", limit: int = 50):
    db = SessionLocal()
    try:
        q = db.query(Idea)
        if status != "all":
            q = q.filter(Idea.status == status)
        ideas = q.order_by(Idea.created_at.desc()).limit(limit).all()
        return [_idea_dict(i) for i in ideas]
    finally:
        db.close()


@app.post("/api/ideas/{idea_id}/approve")
def approve_idea(idea_id: int):
    db = SessionLocal()
    try:
        idea = db.query(Idea).filter(Idea.id == idea_id).first()
        if not idea:
            raise HTTPException(status_code=404, detail="Idea not found")
        idea.status = "approved"
        db.commit()

        # Trigger content generation in background
        import threading
        threading.Thread(target=_generate_content_bg, args=(idea_id,), daemon=True).start()

        return {"ok": True, "message": f"Idea {idea_id} approved — content generation started"}
    finally:
        db.close()


@app.post("/api/ideas/{idea_id}/reject")
def reject_idea(idea_id: int):
    db = SessionLocal()
    try:
        idea = db.query(Idea).filter(Idea.id == idea_id).first()
        if not idea:
            raise HTTPException(status_code=404, detail="Idea not found")
        idea.status = "rejected"
        db.commit()
        return {"ok": True}
    finally:
        db.close()


# ── Content ───────────────────────────────────────────────────────────────────

@app.get("/api/content")
def get_content(status: str = "underreview", limit: int = 50):
    db = SessionLocal()
    try:
        q = db.query(Content)
        if status != "all":
            q = q.filter(Content.status == status)
        items = q.order_by(Content.created_at.desc()).limit(limit).all()
        return [_content_dict(c, db) for c in items]
    finally:
        db.close()


@app.post("/api/content/{content_id}/approve")
def approve_content(content_id: int):
    db = SessionLocal()
    try:
        c = db.query(Content).filter(Content.id == content_id).first()
        if not c:
            raise HTTPException(status_code=404, detail="Content not found")
        c.status = "approved"
        db.commit()
        return {"ok": True}
    finally:
        db.close()


# ── Manual Triggers ───────────────────────────────────────────────────────────

@app.post("/api/trigger/news-scan")
def trigger_news_scan():
    import threading
    threading.Thread(target=_run_scan_bg, daemon=True).start()
    return {"ok": True, "message": "News scan triggered — check back in ~30 seconds"}


@app.get("/api/scans")
def get_scans(limit: int = 10):
    db = SessionLocal()
    try:
        scans = db.query(NewsScan).order_by(NewsScan.created_at.desc()).limit(limit).all()
        return [
            {
                "id": s.id,
                "scan_date": s.scan_date,
                "articles_fetched": s.articles_fetched,
                "ideas_generated": s.ideas_generated,
                "status": s.status,
                "error_msg": s.error_msg,
                "created_at": s.created_at.isoformat(),
            }
            for s in scans
        ]
    finally:
        db.close()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _idea_dict(i: Idea) -> dict:
    return {
        "id": i.id,
        "scan_date": i.scan_date,
        "news_headline": i.news_headline,
        "news_summary": i.news_summary,
        "idea_text": i.idea_text,
        "platform": i.platform,
        "content_type": i.content_type,
        "rationale": i.rationale,
        "status": i.status,
        "created_at": i.created_at.isoformat(),
        "has_content": i.content is not None,
    }


def _content_dict(c: Content, db) -> dict:
    idea = db.query(Idea).filter(Idea.id == c.idea_id).first()
    return {
        "id": c.id,
        "idea_id": c.idea_id,
        "idea_text": idea.idea_text if idea else "",
        "platform": c.platform,
        "content_type": c.content_type,
        "hook": c.hook,
        "copy_text": c.copy_text,
        "script": c.script,
        "hashtags": c.hashtags,
        "cta": c.cta,
        "visual_notes": c.visual_notes,
        "status": c.status,
        "created_at": c.created_at.isoformat(),
    }


def _generate_content_bg(idea_id: int):
    try:
        from agents.content_agent import generate_content
        generate_content(idea_id)
    except Exception as e:
        print(f"[ContentAgent] Background generation failed for idea {idea_id}: {e}")


def _run_scan_bg():
    try:
        from agents.news_agent import run_news_scan
        run_news_scan()
    except Exception as e:
        print(f"[NewsAgent] Background scan failed: {e}")
