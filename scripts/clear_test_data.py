"""
VYZN Safe Test Data Cleanup Script (v1.1 compliant)
- Default: Dry-run only (prints row counts and actions, does not delete).
- Real run: Requires explicit '--confirm' flag.
- Safe backup: Uses SQLite's native conn.backup() API (handles WAL mode safely).
- Backups stored outside data/ in 'c:/vyzn_backups' with 72h auto-deletion timestamp.
- NEVER deletes audit_log (preserves regulatory DPDP processing records).
"""

import sys
import os
import argparse
import sqlite3
import shutil
import time
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parent.parent
DATA_DIR = WORKSPACE / "data" / "clips"
DB_PATH = DATA_DIR / "index.db"
BACKUP_DIR = Path(r"c:\vyzn_backups")
RAW_MEDIA_DIR = DATA_DIR / "raw"

def backup_sqlite_wal(src_path: Path, dest_path: Path):
    """Uses SQLite backup API to safely copy database even during active WAL transactions."""
    src_conn = sqlite3.connect(str(src_path))
    dest_conn = sqlite3.connect(str(dest_path))
    with dest_conn:
        src_conn.backup(dest_conn, pages=100)
    dest_conn.close()
    src_conn.close()

def main():
    parser = argparse.ArgumentParser(description="Clean developer test data from VYZN edge database.")
    parser.add_argument("--confirm", action="store_true", help="Execute deletions. Without this flag, performs a dry-run.")
    args = parser.parse_args()

    if not DB_PATH.exists():
        print(f"Database not found at {DB_PATH}.")
        return

    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM events;")
    events_count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM audit_log;")
    audit_count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM telemetry_log;")
    telemetry_count = cursor.fetchone()[0]
    conn.close()

    print("\n" + "="*60)
    print("VYZN TEST DATA CLEANUP AUDIT")
    print("="*60)
    print(f"Target Database:       {DB_PATH}")
    print(f"Events rows:           {events_count}  (Candidate for purge)")
    print(f"Audit log rows:        {audit_count}  (PROTECTED: Will NEVER be deleted)")
    print(f"Telemetry log rows:    {telemetry_count}  (Telemetry history)")
    raw_files_count = len(list(RAW_MEDIA_DIR.glob("**/*.mp4"))) if RAW_MEDIA_DIR.exists() else 0
    print(f"Raw test MP4 clips:    {raw_files_count} files in {RAW_MEDIA_DIR}")
    print("="*60)

    if not args.confirm:
        print("\n[DRY RUN MODE]")
        print("No changes were made to the database or files.")
        print("To execute cleanup, pass the '--confirm' flag:")
        print("    python scripts/clear_test_data.py --confirm\n")
        return

    # Real run with --confirm
    timestamp = int(time.time())
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    db_backup = BACKUP_DIR / f"index_backup_{timestamp}.db"
    manifest_file = BACKUP_DIR / f"backup_manifest_{timestamp}.txt"

    print(f"\n[1/3] Creating safe WAL-mode SQLite backup to: {db_backup}")
    backup_sqlite_wal(DB_PATH, db_backup)

    with open(manifest_file, "w", encoding="utf-8") as f:
        f.write(f"VYZN Test Data Backup\nTimestamp: {timestamp} (UTC: {time.asctime(time.gmtime(timestamp))})\n")
        f.write(f"Delete After: {timestamp + 72*3600} (72 hours from creation)\n")
        f.write(f"Original events count: {events_count}\nOriginal audit log count: {audit_count}\n")
    print(f"Recorded 72h retention manifest at: {manifest_file}")

    print("\n[2/3] Purging test events while PRESERVING audit_log...")
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    cursor.execute("DELETE FROM events;")
    cursor.execute("DELETE FROM telemetry_log;")
    conn.commit()
    conn.isolation_level = None
    cursor.execute("VACUUM;")
    conn.close()

    print("\n[3/3] Purging test media files...")
    if RAW_MEDIA_DIR.exists():
        for item in RAW_MEDIA_DIR.iterdir():
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()
    print("Old test media directories purged.")

    print("\nCleanup completed successfully. Audit log remains 100% intact.")

if __name__ == "__main__":
    main()
