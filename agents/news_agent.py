"""
Agent 1 — News Scanner
Runs daily at 9 AM Lima time (America/Lima, UTC-5).
"""

import os
import re
import json
import traceback
import httpx
import anthropic
from datetime import date
from db.models import SessionLocal, Idea, NewsScan

VERSION = "v7-plain-text"

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
NEWS_API_KEY = os.getenv("NEWS_API_KEY", "")

BRAND_CONTEXT = """You are a marketing strategist for two fitness brands:
1. BDFit (@bdfitindahouse) - gym/fitness lifestyle, motivational tone
2. MyPacerPro (@mypacerpro) - running performance app, data-driven tone"""

NEWS_QUERIES = [
    "fitness gym workout trends",
    "running marathon training tips",
    "sports nutrition health",
    "wellness mental health exercise",
]


def _clean(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
    text = text.encode('ascii', errors='replace').decode('ascii')
    return text.strip()


def fetch_news() -> list[dict]:
    if not NEWS_API_KEY:
        print("[NewsAgent] No NEWS_API_KEY — using mock articles")
        return _mock_articles()

    articles = []
    seen = set()
    client = httpx.Client(timeout=15)

    for query in NEWS_QUERIES:
        try:
            resp = client.get(
                "https://newsapi.org/v2/everything",
                params={"q": query, "language": "en", "sortBy": "publishedAt", "pageSize": 4, "apiKey": NEWS_API_KEY},
            )
            for art in resp.json().get("articles", []):
                title = _clean(art.get("title", ""))
                if title and title not in seen:
                    seen.add(title)
                    articles.append({
                        "headline": title,
                        "description": _clean(art.get("description", "") or "")[:100],
                        "source": _clean(art.get("source", {}).get("name", "")),
                    })
        except Exception as e:
            print(f"[NewsAgent] Fetch error '{query}': {e}")

    client.close()
    return articles


def _mock_articles() -> list[dict]:
    return [
        {"headline": "High-Protein Diets Reshape Gym Culture", "description": "Protein timing matters more than total intake for muscle gains.", "source": "FitnessToday"},
        {"headline": "Elite Athletes Train Smarter with Polarized Models", "description": "Top marathon runners shift to polarized training for peak performance.", "source": "RunnerWorld"},
        {"headline": "TikTok Fitness Trends Drive Gym Memberships Up 30%", "description": "Short-form video is the top driver of new gym sign-ups.", "source": "SportsBusiness"},
        {"headline": "VO2 Max Tracking Goes Mainstream with Wearables", "description": "Consumer devices now deliver lab-quality metrics to everyday runners.", "source": "TechSport"},
        {"headline": "Exercise Reduces Anxiety by 48% New Study Shows", "description": "Regular cardio confirmed to significantly reduce anxiety levels.", "source": "HealthLine"},
        {"headline": "Functional Fitness Overtakes Traditional Weightlifting", "description": "CrossFit-style movements replacing isolated machine exercises.", "source": "GymInsider"},
        {"headline": "Marathon Participation Hits Record 2 Million Runners", "description": "Post-pandemic high in road race registrations globally.", "source": "RunnerWorld"},
        {"headline": "Sleep Quality Ranked Above Nutrition by Elite Coaches", "description": "Recovery protocols now prioritize sleep optimization.", "source": "SportsSci"},
    ]


def _extract_json(text: str) -> list:
    text = text.strip()
    # strip code fences
    m = re.search(r'```(?:json)?\s*([\s\S]*?)```', text)
    if m:
        text = m.group(1).strip()
    # find the JSON array
    start = text.find('[')
    end = text.rfind(']')
    if start != -1 and end != -1:
        return json.loads(text[start:end + 1])
    return json.loads(text)


def generate_ideas(articles: list[dict]) -> list[dict]:
    if not ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY not set")

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY, timeout=120.0)

    articles_text = "\n".join(
        f"- [{a['source']}] {a['headline']}: {a['description']}"
        for a in articles[:8]
    )

    prompt = f"""{BRAND_CONTEXT}

News headlines:
{articles_text}

Generate exactly 10 content ideas. Return ONLY a JSON array, no other text:
[
  {{
    "brand": "BDFit",
    "news_headline": "headline that inspired this",
    "news_summary": "one sentence",
    "idea_text": "concrete content idea",
    "platform": "instagram",
    "content_type": "reel",
    "rationale": "why it works"
  }}
]

Rules: brand must be BDFit or MyPacerPro, platform must be instagram/tiktok/youtube/all, content_type must be post/reel/short/story/carousel. Return ONLY the JSON array."""

    print(f"[NewsAgent] Calling Claude API ({VERSION})...")
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = message.content[0].text
    print(f"[NewsAgent] Raw response length: {len(raw)} chars")
    ideas = _extract_json(raw)
    print(f"[NewsAgent] Parsed {len(ideas)} ideas")
    return ideas


def run_news_scan():
    today = date.today().isoformat()
    db = SessionLocal()
    scan = NewsScan(scan_date=today)
    db.add(scan)
    db.commit()

    try:
        print(f"[NewsAgent] Starting scan {today} ({VERSION})")
        articles = fetch_news()
        scan.articles_fetched = len(articles)
        print(f"[NewsAgent] Fetched {len(articles)} articles")

        ideas_data = generate_ideas(articles)

        for item in ideas_data:
            db.add(Idea(
                scan_date=today,
                news_headline=item.get("news_headline", ""),
                news_summary=item.get("news_summary", ""),
                idea_text=item.get("idea_text", ""),
                platform=item.get("platform", "instagram"),
                content_type=item.get("content_type", "post"),
                rationale=item.get("rationale", ""),
                status="pending",
            ))

        scan.ideas_generated = len(ideas_data)
        scan.status = "success"
        db.commit()
        print(f"[NewsAgent] Done — {len(ideas_data)} ideas saved ({VERSION})")

    except Exception as e:
        scan.status = "failed"
        scan.error_msg = str(e)[:500]
        db.commit()
        print(f"[NewsAgent] FAILED ({type(e).__name__}): {e}")
        print(traceback.format_exc())
        raise
    finally:
        db.close()
