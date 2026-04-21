"""
Agent 2 — Content Creator
Triggered when an idea is approved via the dashboard.
Writes full platform-native content and saves it as 'underreview'.
"""

import os
import anthropic
from db.models import SessionLocal, Idea, Content

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

BRAND_VOICES = {
    "BDFit": {
        "voice": "Energetico, motivacional, autentico, comunidad. Usa jerga de gimnasio naturalmente. Habla a personas que viven para entrenar. TODO EN ESPANOL.",
        "hashtags": "#BDFit #VidaGym #MotivaciónFitness #ComunidadFit #EntrenamientoReal #FitFam #TransformacionCorporal #GanasMuscular",
        "account": "@bdfitindahouse",
    },
    "MyPacerPro": {
        "voice": "Orientado al rendimiento, basado en datos, motivador. Habla como un coach experto que ha corrido maratones. Tecnico pero accesible. TODO EN ESPANOL.",
        "hashtags": "#MyPacerPro #ComunidadRunner #EntrenamientoMaraton #VidaRunner #DiaDeCabrera #RutaDiaria #RitmoTuyo #CorrerMas",
        "account": "@mypacerpro",
    },
}

CONTENT_TEMPLATES = {
    "post": "imagen estatica con caption",
    "reel": "video vertical de 15-60 segundos con audio/musica",
    "short": "YouTube Short menor a 60 segundos",
    "story": "historia efimera de 24 horas con elementos interactivos",
    "carousel": "serie de 5-10 diapositivas deslizables",
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

    base = f"""Eres el redactor de contenido para {brand} ({bv['account']}).
Voz de marca: {bv['voice']}
Hashtags base: {bv['hashtags']}

Idea de contenido a ejecutar:
"{idea.idea_text}"

Inspirado en: {idea.news_headline}
Plataforma: {idea.platform}
Formato: {idea.content_type} ({content_format})

Escribe contenido listo para publicar EN ESPANOL. Devuelve SOLO un objeto JSON:
{{
  "hook": "primera linea o primeros 3 segundos del video — debe detener el scroll",
  "copy_text": "caption completo con saltos de linea y emojis donde sea natural",
  "script": "guion paso a paso con tiempos (solo para reel/short/story, sino null)",
  "hashtags": "30 hashtags relevantes como una sola cadena separada por espacios",
  "cta": "llamada a la accion clara al final",
  "visual_notes": "instrucciones especificas para el equipo creativo — colores, texto en pantalla, b-roll, transiciones, mood musical"
}}

Devuelve SOLO el objeto JSON, sin texto adicional."""

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

        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY, timeout=120.0)
        message = client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )

        raw = message.content[0].text.strip()
        import re, json
        m = re.search(r'```(?:json)?\s*([\s\S]*?)```', raw)
        if m:
            raw = m.group(1).strip()
        start, end = raw.find('{'), raw.rfind('}')
        data = json.loads(raw[start:end + 1] if start != -1 else raw)

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
