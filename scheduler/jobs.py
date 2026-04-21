from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

LIMA_TZ = pytz.timezone("America/Lima")


def start_scheduler():
    scheduler = BackgroundScheduler(timezone=LIMA_TZ)

    scheduler.add_job(
        _run_news_scan,
        trigger=CronTrigger(hour=9, minute=0, timezone=LIMA_TZ),
        id="daily_news_scan",
        name="Daily News Scan — 9 AM Lima",
        replace_existing=True,
    )

    scheduler.start()
    print("[Scheduler] Started — News scan runs daily at 9:00 AM Lima time (America/Lima)")
    return scheduler


def _run_news_scan():
    from agents.news_agent import run_news_scan
    run_news_scan()
