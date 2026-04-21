"""
Agent 1 — News Scanner
Runs daily at 9 AM Lima time (America/Lima, UTC-5).
Fetches fitness/running/wellness news, filters for brand relevance,
and generates 10 content ideas saved as 'pending' in the DB.
"""

import os
import re
import json
import traceback
import httpx
import anthropic
from datetime import date
from db.models import SessionLocal, Idea, NewsScan


def _clean(text: str) -> str:
    if not text:
        return ""
    # Remove control characters except tab/newline
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
    # Drop lone Unicode surrogates (invalid in JSON)
    text = text.encode('utf-8', errors='replace').decode('utf-8')
    return text.strip()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
NEWS_API_KEY = os.getenv("NEWS_API_KEY", "")

BRAND_CONTEXT = """
You are a marketing strategist for two fitness brands:

1. BDFit (Instagram: @bdfitindahouse)
   - Gym / fitness lifestyle brand
   - Target: people who love working out, gym culture, body transformation
   - Tone: motivational, energetic, authentic, community-driven
   - Content pillars: workouts, nutrition, transformation, gym lifestyle, motivation

2. MyPacerPro (Instagram: @mypacerpro)
   - Running performance app / brand
   - Target: runners from beginner to advanced, athletes, race participants
   - Tone: performance-focused, technical, encouraging, data-driven
   - Content pillars: running tips, race prep, pacing strategy, training plans, gear
"""

NEWS_QUERIES = [
    "fitness gym workout trends",
    "running marathon training tips",
    "sports nutrition health",
    "bodybuilding muscle growth",
    "running technology wearables",
    "wellness mental health exercise",
    "fitness influencer social media",
    "sports performance training",
]


def fetch_news() -> list[dict]:
    if not NEWS_API_KEY:
        print("[NewsAgent] No NEWS_API_KEY — using mock articles for testing")
        return _mock_articles()

    articles = []
    seen_titles = set()
    client = httpx.Client(timeout=15)

    for query in NEWS_QUERIES[:4]:  # 4 queries to stay within free tier
        try:
            resp = client.get(
                "https://newsapi.org/v2/everything",
                params={
                    "q": query,
                    "language": "en",
                    "sortBy": "publishedAt",
                    "pageSize": 5,
                    "apiKey": NEWS_API_KEY,
                },
            )
            data = resp.json()
            for art in data.get("articles", []):
                title = _clean(art.get("title", ""))
                if title and title not in seen_titles:
                    seen_titles.add(title)
                    articles.append({
                        "headline": title,
                        "description": _clean(art.get("description", "") or ""),
                        "url": art.get("url", ""),
                        "source": _clean(art.get("source", {}).get("name", "")),
                    })
        except Exception as e:
            print(f"[NewsAgent] Error fetching '{query}': {e}")

    client.close()
    return articles


def _mock_articles() -> list[dict]:
    return [
        {"headline": "High-Protein Diets Are Reshaping Gym Culture in 2025", "description": "New research shows protein timing matters more than total intake for muscle gains.", "url": "", "source": "FitnessToday"},
        {"headline": "Running Economy: How Elite Athletes Are Training Smarter", "description": "Top marathon runners shift to polarized training models for peak performance.", "url": "", "source": "RunnerWorld"},
        {"headline": "TikTok Fitness Trends Driving Gym Memberships Up 30%", "description": "Short-form video content is the #1 driver of new gym sign-ups in 2025.", "url": "", "source": "SportsBusiness"},
        {"headline": "Wearable Tech: VO2 Max Tracking Goes Mainstream", "description": "Consumer-grade devices now deliver lab-quality performance metrics to everyday runners.", "url": "", "source": "TechSport"},
        {"headline": "Mental Health and Exercise: The Science Behind the Runner's High", "description": "New studies confirm regular cardio reduces anxiety by up to 48%.", "url": "", "source": "HealthLine"},
        {"headline": "Functional Fitness Is Overtaking Traditional Weightlifting", "description": "CrossFit-style movements are replacing isolated machine exercises in modern gym culture.", "url": "", "source": "GymInsider"},
        {"headline": "Race Season 2025: Marathon Participation Hits Record Numbers", "description": "Over 2 million runners registered for road races globally — a post-pandemic high.", "url": "", "source": "RunnerWorld"},
        {"headline": "Sleep Optimization Is the New Competitive Edge for Athletes", "description": "Elite coaches now rank sleep quality above nutrition in recovery protocols.", "url": "", "source": "SportsSci"},
    ]


_IDEAS_TOOL = {
    "name": "save_ideas",
    "description": "Save the generated content ideas to the database",
    "input_schema": {
        "type": "object",
        "properties": {
            "ideas": {
                "type": "array",
                "minItems": 10,
                "maxItems": 10,
                "items": {
                    "type": "object",
                    "required": ["brand", "news_headline", "news_summary", "idea_text", "platform", "content_type", "rationale"],
                    "properties": {
                        "brand":         {"type": "string", "enum": ["BDFit", "MyPacerPro"]},
                        "news_headline": {"type": "string"},
                        "news_summary":  {"type": "string"},
                        "idea_text":     {"type": "string"},
                        "platform":      {"type": "string", "enum": ["instagram", "tiktok", "youtube", "all"]},
                        "content_type":  {"type": "string", "enum": ["post", "reel", "short", "story", "carousel"]},
                        "rationale":     {"type": "string"},
                    },
                },
            }
        },
        "required": ["ideas"],
    },
}


def generate_ideas(articles: list[dict]) -> list[dict]:
    if not ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY not set")

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    articles_text = "\n".join(
        f"- [{a['source']}] {a['headline']}: {a['description']}"
        for a in articles[:15]
    )

    prompt = f"""{BRAND_CONTEXT}

Today's fitness/running/wellness news:
{articles_text}

Based on these news stories, generate exactly 10 social media content ideas for BDFit and MyPacerPro.
Mix ideas between both brands. Each idea should be inspired by or tied to one of the news stories.
Call the save_ideas tool with your 10 ideas."""

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        tools=[_IDEAS_TOOL],
        tool_choice={"type": "tool", "name": "save_ideas"},
        messages=[{"role": "user", "content": prompt}],
    )

    print(f"[NewsAgent] stop_reason={message.stop_reason}, blocks={[b.type for b in message.content]}")

    for block in message.content:
        if block.type == "tool_use" and block.name == "save_ideas":
            ideas = block.input.get("ideas", block.input) if isinstance(block.input, dict) else []
            print(f"[NewsAgent] tool input keys={list(block.input.keys()) if isinstance(block.input, dict) else type(block.input)}, ideas count={len(ideas) if isinstance(ideas, list) else ideas}")
            if isinstance(ideas, list):
                return ideas
            raise ValueError(f"Unexpected tool input structure: {block.input}")

    raise ValueError("No tool_use block in response")


def run_news_scan():
    today = date.today().isoformat()
    db = SessionLocal()
    scan = NewsScan(scan_date=today)
    db.add(scan)
    db.commit()

    try:
        print(f"[NewsAgent] Starting scan for {today}")
        articles = fetch_news()
        scan.articles_fetched = len(articles)
        print(f"[NewsAgent] Fetched {len(articles)} articles")

        ideas_data = generate_ideas(articles)
        print(f"[NewsAgent] Generated {len(ideas_data)} ideas")

        for item in ideas_data:
            idea = Idea(
                scan_date=today,
                news_headline=item.get("news_headline", ""),
                news_summary=item.get("news_summary", ""),
                idea_text=item.get("idea_text", ""),
                platform=item.get("platform", "instagram"),
                content_type=item.get("content_type", "post"),
                rationale=item.get("rationale", ""),
                status="pending",
            )
            db.add(idea)

        scan.ideas_generated = len(ideas_data)
        scan.status = "success"
        db.commit()
        print(f"[NewsAgent] Done — {len(ideas_data)} ideas saved as pending")

    except Exception as e:
        scan.status = "failed"
        scan.error_msg = str(e)
        db.commit()
        print(f"[NewsAgent] Failed: {e}")
        print(f"[NewsAgent] Traceback:\n{traceback.format_exc()}")
        raise
    finally:
        db.close()
