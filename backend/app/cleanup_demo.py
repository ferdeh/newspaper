from __future__ import annotations

import argparse
import json

from sqlalchemy import delete, func, or_, select

from app.database import SessionLocal
from app.models import (
    AlertHistory,
    Article,
    Event,
    Incident,
    IncidentSignal,
    MasterSpbu,
    NewsSource,
    RawArticle,
    RiskScoreHistory,
    Signal,
    TikTokPost,
)
from app.services.analytics import refresh_analytics
from app.services.pipeline import recompute_incident


def cleanup_demo_data(*, apply: bool = False) -> dict[str, object]:
    with SessionLocal() as db:
        demo_news_ids = list(
            db.scalars(select(RawArticle.id).where(RawArticle.canonical_url.like("https://demo.%")))
        )
        demo_tiktok_ids = list(
            db.scalars(
                select(TikTokPost.id).where(
                    or_(TikTokPost.video_id.like("demo-%"), TikTokPost.url.like("%/@demo.%"))
                )
            )
        )
        demo_signal_ids = list(
            db.scalars(
                select(Signal.id).where(
                    or_(
                        (Signal.source_type == "NEWS") & Signal.source_record_id.in_(demo_news_ids),
                        (Signal.source_type == "TIKTOK") & Signal.source_record_id.in_(demo_tiktok_ids),
                    )
                )
            )
        )
        affected_incident_ids = list(
            db.scalars(
                select(IncidentSignal.incident_id)
                .where(IncidentSignal.signal_id.in_(demo_signal_ids))
                .distinct()
            )
        )
        demo_source_ids = list(
            db.scalars(
                select(NewsSource.id).where(
                    or_(NewsSource.domain.like("%.demo"), NewsSource.name.ilike("Demo %"))
                )
            )
        )
        demo_spbu_ids = list(
            db.scalars(select(MasterSpbu.id).where(MasterSpbu.spbu_name.ilike("%DEMO%")))
        )

        report: dict[str, object] = {
            "status": "preview" if not apply else "removed",
            "demo_news": len(demo_news_ids),
            "demo_tiktok": len(demo_tiktok_ids),
            "demo_signals": len(demo_signal_ids),
            "affected_incidents": len(affected_incident_ids),
            "demo_sources": len(demo_source_ids),
            "demo_spbu": len(demo_spbu_ids),
        }
        if not apply:
            return report

        db.execute(delete(IncidentSignal).where(IncidentSignal.signal_id.in_(demo_signal_ids)))
        db.flush()

        still_linked_incident_ids = set(
            db.scalars(
                select(IncidentSignal.incident_id)
                .where(IncidentSignal.incident_id.in_(affected_incident_ids))
                .distinct()
            )
        )
        empty_incident_ids = sorted(set(affected_incident_ids) - still_linked_incident_ids)

        db.execute(delete(AlertHistory).where(AlertHistory.incident_id.in_(affected_incident_ids)))
        db.execute(delete(RiskScoreHistory).where(RiskScoreHistory.incident_id.in_(affected_incident_ids)))
        db.execute(delete(Incident).where(Incident.id.in_(empty_incident_ids)))
        db.execute(delete(Event).where(Event.signal_id.in_(demo_signal_ids)))
        db.execute(delete(Article).where(Article.raw_article_id.in_(demo_news_ids)))
        db.execute(delete(Signal).where(Signal.id.in_(demo_signal_ids)))
        db.execute(delete(RawArticle).where(RawArticle.id.in_(demo_news_ids)))
        db.execute(delete(TikTokPost).where(TikTokPost.id.in_(demo_tiktok_ids)))

        removable_source_ids = [
            source_id
            for source_id in demo_source_ids
            if not db.scalar(
                select(func.count(RawArticle.id)).where(RawArticle.source_id == source_id)
            )
        ]
        db.execute(delete(NewsSource).where(NewsSource.id.in_(removable_source_ids)))

        incidents_using_demo_spbu = list(
            db.scalars(select(Incident).where(Incident.spbu_id.in_(demo_spbu_ids)))
        )
        for incident in incidents_using_demo_spbu:
            incident.spbu_id = None
            incident.legacy_serving_terminal_id = None
            incident.serving_tbbm_id = None
        db.flush()
        db.execute(delete(MasterSpbu).where(MasterSpbu.id.in_(demo_spbu_ids)))
        db.flush()

        for incident_id in sorted(still_linked_incident_ids):
            incident = db.get(Incident, incident_id)
            if incident:
                recompute_incident(db, incident)

        analytics_rows = refresh_analytics(db)
        report.update(
            {
                "incidents_removed": len(empty_incident_ids),
                "incidents_recomputed": len(still_linked_incident_ids),
                "spbu_links_cleared": len(incidents_using_demo_spbu),
                "analytics_rows": analytics_rows,
            }
        )
        return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Preview or remove synthetic demo records")
    parser.add_argument("--apply", action="store_true", help="Permanently remove detected demo records")
    args = parser.parse_args()
    print(json.dumps(cleanup_demo_data(apply=args.apply), indent=2, sort_keys=True))
