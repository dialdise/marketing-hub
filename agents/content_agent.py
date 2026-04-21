"""
Agent 2 — Content Creator
Triggered when an idea is approved via the dashboard.
Writes full platform-native content and saves it as 'underreview'.
"""

import os
import json
import anthropic
from db.models import SessionLocal, Idea, Content

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

BRAND_VOICES = {
    "BDFit": {
        "voice": "Energetic, motivational, raw, community-driven. Uses gym slang naturally. Speaks to people who live for the grind.",
        "hashtags": "#BDFit #GymLife #FitnessMotivation #GymCommunity #WorkoutLife #FitFam #BodyTransformation #GainsGang",
        "account": "@bdfitindahouse",
    },
    "MyPacerPro": {
        "voice": "Performance-focused, data-driven, encouraging. Speaks like a knowledgeable coach who ran marathons. Technical but accessible.",
        "hashtags": "#MyPacerPro #RunningCommunity #MarathonTraining #RunnerLife #RaceDay #TrainingRun #PaceYourself #RunMore",
        "account": "@mypacerpro",
    },
}

CONTENT_TEMPLATES = {
    "post": "static image with caption",
    "reel": "15-60 second vertical video with audio/music",
    "short": "YouTube Short under 60 seconds",
    "story": "24-hour ephemeral story with interactive elements",
    "carousel": "swipe-through series of 5-10 slides",
}


def detect_brand(idea_text: str, rationale: str) -> str:
    text = (idea_text + " " + rationale).lower()
    running_keywords = ["run", "pace", "marathon", "race", "stride", "vo2", "cadence", "km", "mile"]
    if any(kw in text for kw in running_keywords):
        return "MyPacerPro"
    return "BDFit"


def build_content_prompt(idea: Idea, brand: str) -> str:
    bv = BRAND_VOICES[brand]
    content_format = CONTENT_TEMPLATES.get(idea.content_type, "post")

    base = f"""You are the content writer for {brand} ({bv['account']}).
Brand voice: {bv['voice']}
Default hashtags: {bv['hashtags']}

Content idea to execute:
"{idea.idea_text}"

Inspired by: {idea.news_headline}
Platform: {idea.platform}
Format: {idea.content_type} ({content_format})

Write production-ready content. Return a JSON object with:
{{
  "hook": "the opening line or first 3 seconds of video — must stop the scroll",
  "copy_text": "full caption / body text with line breaks and emojis where natural",
  "script": "step-by-step video script with timestamps (only for reel/short/story, else null)",
  "hashtags": "30 relevant hashtags as a single string separated by spaces",
  "cta": "clear call to action at the end",
  "visual_notes": "specific directions for the creative team — colors, on-screen text, b-roll, transitions, music mood"
}}

Only return the JSON object, no other text."""

    return base


def generate_content(idea_id: int) -> Content:
    if not ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY not set")

    db = SessionLocal()
    try:
        idea = db.query(Idea).filter(Idea.id == idea_id).first()
        if not idea:
            raise ValueError(f"Idea {idea_id} not found")
        if idea.status != "approved":
            raise ValueError(f"Idea {idea_id} is not approved (status: {idea.status})")
        if idea.content:
            raise ValueError(f"Content already exists for idea {idea_id}")

        brand = detect_brand(idea.idea_text, idea.rationale or "")
        prompt = build_content_prompt(idea, brand)

        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        message = client.messages.create(
            model="claude-opus-4-7",
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )

        raw = message.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        data = json.loads(raw.strip())

        content = Content(
            idea_id=idea_id,
            platform=idea.platform,
            content_type=idea.content_type,
            hook=data.get("hook", ""),
            copy_text=data.get("copy_text", ""),
            script=data.get("script"),
            hashtags=data.get("hashtags", ""),
            cta=data.get("cta", ""),
            visual_notes=data.get("visual_notes", ""),
            status="underreview",
        )
        db.add(content)
        db.commit()
        db.refresh(content)

        print(f"[ContentAgent] Content created for idea {idea_id} (brand: {brand}, type: {idea.content_type})")
        return content

    finally:
        db.close()
