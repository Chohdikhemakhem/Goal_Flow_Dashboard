from app.db.session import SessionLocal
from app.services.imports import backfill_snapshot_batch_dates


def main() -> None:
    db = SessionLocal()
    try:
        updated, skipped = backfill_snapshot_batch_dates(db)
        print(
            f"Backfill termine: {updated} snapshots mises a jour, {skipped} snapshots ignorees."
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()

