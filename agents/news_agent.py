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

VERSION = "v9-spanish"

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
NEWS_API_KEY = os.getenv("NEWS_API_KEY", "")

BRAND_CONTEXT = """Eres estratega de marketing para dos marcas de fitness:
1. BDFit (@bdfitindahouse) - gimnasio/estilo de vida fitness, tono motivacional en espanol
2. MyPacerPro (@mypacerpro) - app de rendimiento para corredores, tono tecnico y motivador en espanol"""

NEWS_QUERIES = [
    "fitness gimnasio ejercicio tendencias",
    "running maraton entrenamiento consejos",
    "nutricion deportiva salud",
    "bienestar salud mental ejercicio",
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
                params={"q": query, "language": "es", "sortBy": "publishedAt", "pageSize": 4, "apiKey": NEWS_API_KEY},
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
    if len(articles) < 4:
        print(f"[NewsAgent] Solo {len(articles)} articulos en espanol — usando mock articles")
        return _mock_articles()
    return articles


def _mock_articles() -> list[dict]:
    return [
        {"headline": "Dietas altas en proteinas transforman la cultura del gimnasio", "description": "El momento de consumo de proteinas importa mas que la cantidad total para ganar musculo.", "source": "FitnessHoy"},
        {"headline": "Atletas de elite entrenan con modelos polarizados", "description": "Los mejores maratonistas adoptan el entrenamiento polarizado para rendir al maximo.", "source": "MundoRunner"},
        {"headline": "TikTok fitness dispara membresias en gimnasios un 30%", "description": "El video corto es el principal motor de nuevas inscripciones en gimnasios.", "source": "DeporteNegocios"},
        {"headline": "El seguimiento de VO2 Max llega a dispositivos para todos", "description": "Los wearables de consumo ahora ofrecen metricas de calidad de laboratorio.", "source": "TechDeporte"},
        {"headline": "El ejercicio reduce la ansiedad un 48% segun nuevo estudio", "description": "El cardio regular reduce significativamente los niveles de ansiedad.", "source": "SaludLine"},
        {"headline": "El fitness funcional supera al levantamiento tradicional", "description": "Los movimientos estilo CrossFit reemplazan las maquinas en los gimnasios modernos.", "source": "GimInsider"},
        {"headline": "Participacion en maratones alcanza record de 2 millones de corredores", "description": "Maximo historico en inscripciones a carreras de ruta a nivel mundial.", "source": "MundoRunner"},
        {"headline": "La calidad del sueno supera a la nutricion para entrenadores de elite", "description": "Los protocolos de recuperacion priorizan la optimizacion del sueno.", "source": "CienciaDeporte"},
    ]


def _extract_json(text: str) -> list:
    text = text.strip()
    # strip code fences
    m = re.search(r'```(?:json)?\s*([\s\S]*?)```', text)
    if m:
        text = m.group(1).strip()
    # find the JSON array boundaries
    start = text.find('[')
    end = text.rfind(']')
    candidate = text[start:end + 1] if start != -1 and end != -1 else text
    # try direct parse first
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass
    # fix literal newlines/tabs inside JSON string values
    def fix_string_values(s: str) -> str:
        result = []
        in_string = False
        escape = False
        for ch in s:
            if escape:
                result.append(ch)
                escape = False
            elif ch == '\\' and in_string:
                result.append(ch)
                escape = True
            elif ch == '"':
                result.append(ch)
                in_string = not in_string
            elif in_string and ch in ('\n', '\r', '\t'):
                result.append(' ')
            else:
                result.append(ch)
        return ''.join(result)
    return json.loads(fix_string_values(candidate))


def generate_ideas(articles: list[dict]) -> list[dict]:
    if not ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY not set")

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY, timeout=120.0)

    articles_text = "\n".join(
        f"- [{a['source']}] {a['headline']}: {a['description']}"
        for a in articles[:8]
    )

    prompt = f"""{BRAND_CONTEXT}

Noticias de hoy:
{articles_text}

Genera exactamente 10 ideas de contenido en ESPANOL para redes sociales. Devuelve SOLO un array JSON, sin texto adicional:
[
  {{
    "brand": "BDFit",
    "news_headline": "titular que inspiro esta idea",
    "news_summary": "resumen en una oracion",
    "idea_text": "idea de contenido concreta en espanol",
    "platform": "instagram",
    "content_type": "reel",
    "rationale": "por que funciona para la audiencia"
  }}
]

Reglas: brand debe ser BDFit o MyPacerPro, platform debe ser instagram/tiktok/youtube/all, content_type debe ser post/reel/short/story/carousel. Todo el contenido en ESPANOL. Devuelve SOLO el array JSON."""

    print(f"[NewsAgent] Calling Claude API ({VERSION})...")
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = message.content[0].text if message.content else ""
    print(f"[NewsAgent] Raw response length: {len(raw)} chars")
    if not raw.strip():
        raise ValueError("Claude devolvio una respuesta vacia")
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
