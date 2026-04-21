import os
from pathlib import Path
from dotenv import load_dotenv

_env = Path(__file__).parent / ".env"
if _env.exists():
    load_dotenv(_env)

import uvicorn

PORT = int(os.getenv("PORT", 8000))

if __name__ == "__main__":
    print(f"""
╔══════════════════════════════════════════╗
║       Marketing Hub                      ║
║       BDFit & MyPacerPro                 ║
╠══════════════════════════════════════════╣
║  Dashboard  → http://localhost:{PORT:<12}║
║  News scan  → daily 9:00 AM Lima         ║
╚══════════════════════════════════════════╝
""")
    uvicorn.run(
        "api.server:app",
        host="0.0.0.0",
        port=PORT,
        reload=False,
        log_level="info",
    )
