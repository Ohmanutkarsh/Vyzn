"""
SQLite database engine with WAL mode and Single-Writer Queue architecture.
Eliminates database lock contention across concurrent capture and sync workers.
"""

from __future__ import annotations
import sqlite3
import threading
import queue
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any, Callable
from datetime import datetime, timezone
from vyzn.core.events import EventRecord

logger = logging.getLogger("vyzn.core.database")


class DatabaseWriterWorker(threading.Thread):
    """
    Dedicated single-thread database writer.
    Executes write transactions sequentially from a thread-safe FIFO queue.
    """

    def __init__(self, db_path: Path):
        super().__init__(name="SQLite-Writer-Worker", daemon=True)
        self.db_path = db_path
        self.queue: queue.Queue = queue.Queue()
        self.running = True
        self._ready_event = threading.Event()

    def run(self):
        conn = sqlite3.connect(
            str(self.db_path),
            timeout=10.0,
            check_same_thread=False
        )
        # Configure WAL mode and optimal write pragmas
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.execute("PRAGMA busy_timeout = 5000;")
        conn.execute("PRAGMA temp_store = MEMORY;")
        conn.commit()

        self._init_tables(conn)
        self._ready_event.set()

        while self.running or not self.queue.empty():
            try:
                task = self.queue.get(timeout=0.2)
            except queue.Empty:
                continue

            if task is None:  # Sentinel to stop
                break

            sql, params, callback = task
            try:
                cursor = conn.cursor()
                cursor.execute(sql, params)
                conn.commit()
                if callback:
                    callback(cursor.lastrowid, None)
            except Exception as e:
                logger.error(f"SQLite write error on query [{sql}]: {e}")
                if callback:
                    callback(None, e)
            finally:
                self.queue.task_done()

        conn.close()

    def wait_until_ready(self, timeout: float = 5.0) -> bool:
        return self._ready_event.wait(timeout)

    def _init_tables(self, conn: sqlite3.Connection):
        """Initializes tables matching SQLite schema contract."""
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS events (
            event_group_id TEXT PRIMARY KEY,
            camera_id TEXT NOT NULL,
            start_time TEXT NOT NULL,          -- ISO 8601 UTC
            end_time TEXT,                     -- ISO 8601 UTC
            object_type TEXT NOT NULL,         -- 'person' | 'vehicle' | 'animal' | 'unclassified'
            confidence REAL NOT NULL,          -- 0.00 to 1.00
            score INTEGER NOT NULL,            -- 0 to 100
            status TEXT DEFAULT 'raw',         -- 'raw' | 'compressed' | 'deleted'
            starred INTEGER DEFAULT 0,         -- 0 or 1
            synced INTEGER DEFAULT 0,          -- 0 or 1 (updated by Cloud Sync)
            user_triage TEXT DEFAULT 'unreviewed', -- 'unreviewed' | 'confirmed_threat' | 'false_positive'
            file_path TEXT NOT NULL,           -- Path to .mp4
            thumb_path TEXT NOT NULL,          -- Path to .jpg
            dominant_color TEXT DEFAULT 'unspecified',
            zone_name TEXT DEFAULT 'general',
            location_id TEXT DEFAULT 'loc_primary',
            duration_sec REAL DEFAULT 0.0,
            motion_points_count INTEGER DEFAULT 0,
            metadata_json TEXT DEFAULT '{}'
        );

        CREATE INDEX IF NOT EXISTS idx_events_camera_time ON events(camera_id, start_time);
        CREATE INDEX IF NOT EXISTS idx_events_synced ON events(synced, score);
        CREATE INDEX IF NOT EXISTS idx_events_forensic ON events(location_id, object_type, score, start_time);

        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp_utc TEXT NOT NULL,
            action TEXT NOT NULL,
            event_group_id TEXT,
            details TEXT
        );

        CREATE TABLE IF NOT EXISTS telemetry_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp_utc TEXT NOT NULL,
            cpu_usage REAL,
            ram_used_mb REAL,
            disk_free_pct REAL,
            active_cameras INTEGER,
            queue_depth INTEGER
        );
        """)
        try:
            conn.execute("ALTER TABLE events ADD COLUMN user_triage TEXT DEFAULT 'unreviewed';")
        except sqlite3.OperationalError:
            pass  # Already present
        try:
            conn.execute("ALTER TABLE events ADD COLUMN dominant_color TEXT DEFAULT 'unspecified';")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("ALTER TABLE events ADD COLUMN zone_name TEXT DEFAULT 'general';")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("ALTER TABLE events ADD COLUMN location_id TEXT DEFAULT 'loc_primary';")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("ALTER TABLE events ADD COLUMN duration_sec REAL DEFAULT 0.0;")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("ALTER TABLE events ADD COLUMN motion_points_count INTEGER DEFAULT 0;")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("ALTER TABLE events ADD COLUMN metadata_json TEXT DEFAULT '{}';")
        except sqlite3.OperationalError:
            pass

        try:
            conn.execute("CREATE INDEX IF NOT EXISTS idx_events_location ON events(location_id);")
        except sqlite3.OperationalError:
            pass
        conn.commit()
        conn.commit()



class EventDatabase:
    """
    Client interface for querying and modifying the event database.
    Writes are dispatched asynchronously to the DatabaseWriterWorker.
    Reads use read-only connections directly.
    """

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.writer = DatabaseWriterWorker(self.db_path)
        self.writer.start()
        if not self.writer.wait_until_ready(timeout=5.0):
            raise TimeoutError("Timed out initializing SQLite database worker")

    def _get_read_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            str(self.db_path),
            timeout=5.0,
            check_same_thread=False
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 5000;")
        return conn

    def insert_event(self, event: EventRecord, callback: Optional[Callable] = None):
        """Dispatches an event insert to the writer queue."""
        sql = """
        INSERT OR REPLACE INTO events (
            event_group_id, camera_id, start_time, end_time,
            object_type, confidence, score, status,
            starred, synced, user_triage, file_path, thumb_path,
            dominant_color, zone_name, location_id, duration_sec,
            motion_points_count, metadata_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        params = (
            event.event_group_id, event.camera_id, event.start_time, event.end_time,
            event.object_type, event.confidence, event.score, event.status,
            event.starred, event.synced, getattr(event, "user_triage", "unreviewed"),
            event.file_path, event.thumb_path,
            getattr(event, "dominant_color", "unspecified"),
            getattr(event, "zone_name", "general"),
            getattr(event, "location_id", "loc_primary"),
            getattr(event, "duration_sec", 0.0),
            getattr(event, "motion_points_count", 0),
            getattr(event, "metadata_json", "{}")
        )
        self.writer.queue.put((sql, params, callback))

    def update_event_status(self, event_group_id: str, status: str):
        sql = "UPDATE events SET status = ? WHERE event_group_id = ?"
        self.writer.queue.put((sql, (status, event_group_id), None))

    def update_event_triage(self, event_group_id: str, triage: str):
        """Updates user triage status ('confirmed_threat', 'false_positive', 'unreviewed')."""
        sql = "UPDATE events SET user_triage = ? WHERE event_group_id = ?"
        self.writer.queue.put((sql, (triage, event_group_id), None))

    def update_event_star(self, event_group_id: str, starred: int = 1):
        """Updates event starred status (0 or 1) to safeguard against reaper auto-deletion."""
        sql = "UPDATE events SET starred = ? WHERE event_group_id = ?"
        self.writer.queue.put((sql, (starred, event_group_id), None))

    def get_triage_statistics(self) -> Dict[str, Any]:
        """Returns aggregate metrics on owner triage decisions and empirical false alarm rate."""
        conn = self._get_read_conn()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT user_triage, COUNT(*) FROM events GROUP BY user_triage")
            rows = cursor.fetchall()
            stats = {"unreviewed": 0, "confirmed_threat": 0, "false_positive": 0, "total": 0}
            for status, count in rows:
                if status in stats:
                    stats[status] = count
                stats["total"] += count
            reviewed = stats["confirmed_threat"] + stats["false_positive"]
            stats["false_positive_rate"] = round((stats["false_positive"] / float(reviewed)) * 100.0, 1) if reviewed > 0 else 0.0
            return stats
        finally:
            conn.close()

    def get_camera_triage_statistics(
        self,
        camera_id: str,
        window_days: Optional[int] = 30
    ) -> Dict[str, Any]:
        """Returns triage metrics and empirical false positive rate for a camera within a rolling window."""
        from datetime import timedelta
        conn = self._get_read_conn()
        try:
            cursor = conn.cursor()
            if window_days and window_days > 0:
                cutoff = (datetime.now(timezone.utc) - timedelta(days=window_days)).isoformat()
                cursor.execute(
                    "SELECT user_triage, COUNT(*) FROM events WHERE camera_id = ? AND start_time >= ? GROUP BY user_triage",
                    (camera_id, cutoff)
                )
            else:
                cursor.execute(
                    "SELECT user_triage, COUNT(*) FROM events WHERE camera_id = ? GROUP BY user_triage",
                    (camera_id,)
                )
            rows = cursor.fetchall()
            stats = {"unreviewed": 0, "confirmed_threat": 0, "false_positive": 0, "total": 0}
            for status, count in rows:
                if status in stats:
                    stats[status] = count
                stats["total"] += count
            reviewed = stats["confirmed_threat"] + stats["false_positive"]
            stats["reviewed"] = reviewed
            stats["false_positive_rate"] = round((stats["false_positive"] / float(reviewed)) * 100.0, 1) if reviewed > 0 else 0.0
            stats["fpr_fraction"] = (stats["false_positive"] / float(reviewed)) if reviewed > 0 else 0.0
            return stats
        finally:
            conn.close()

    def get_all_camera_triage_statistics(
        self,
        window_days: Optional[int] = 30
    ) -> Dict[str, Dict[str, Any]]:
        """Returns triage metrics grouped by camera_id within a rolling window."""
        from datetime import timedelta
        conn = self._get_read_conn()
        try:
            cursor = conn.cursor()
            if window_days and window_days > 0:
                cutoff = (datetime.now(timezone.utc) - timedelta(days=window_days)).isoformat()
                cursor.execute(
                    "SELECT camera_id, user_triage, COUNT(*) FROM events WHERE start_time >= ? GROUP BY camera_id, user_triage",
                    (cutoff,)
                )
            else:
                cursor.execute(
                    "SELECT camera_id, user_triage, COUNT(*) FROM events GROUP BY camera_id, user_triage"
                )
            rows = cursor.fetchall()
            result: Dict[str, Dict[str, Any]] = {}
            for cam_id, status, count in rows:
                if cam_id not in result:
                    result[cam_id] = {"unreviewed": 0, "confirmed_threat": 0, "false_positive": 0, "total": 0}
                if status in result[cam_id]:
                    result[cam_id][status] = count
                result[cam_id]["total"] += count
            for cam_id, stats in result.items():
                reviewed = stats["confirmed_threat"] + stats["false_positive"]
                stats["reviewed"] = reviewed
                stats["false_positive_rate"] = round((stats["false_positive"] / float(reviewed)) * 100.0, 1) if reviewed > 0 else 0.0
                stats["fpr_fraction"] = (stats["false_positive"] / float(reviewed)) if reviewed > 0 else 0.0
            return result
        finally:
            conn.close()

    def mark_event_synced(self, event_group_id: str):
        sql = "UPDATE events SET synced = 1 WHERE event_group_id = ?"
        self.writer.queue.put((sql, (event_group_id,), None))


    def log_audit(self, action: str, event_group_id: Optional[str] = None, details: str = ""):
        sql = "INSERT INTO audit_log (timestamp_utc, action, event_group_id, details) VALUES (?, ?, ?, ?)"
        ts = datetime.now(timezone.utc).isoformat()
        self.writer.queue.put((sql, (ts, action, event_group_id, details), None))

    def fetch_all(self, sql: str, params: tuple = ()) -> List[Any]:
        """Executes a read query and returns all matching rows."""
        conn = self._get_read_conn()
        try:
            cursor = conn.cursor()
            cursor.execute(sql, params)
            return cursor.fetchall()
        finally:
            conn.close()

    def execute_sync(self, sql: str, params: tuple = ()):
        """Dispatches a write to the writer worker and blocks until committed."""
        done_event = threading.Event()
        err_holder = []
        def on_done(res, err):
            if err:
                err_holder.append(err)
            done_event.set()
        self.writer.queue.put((sql, params, on_done))
        done_event.wait(timeout=5.0)
        if err_holder:
            raise err_holder[0]

    def get_event(self, event_group_id: str) -> Optional[EventRecord]:
        """Reads a single event by ID."""
        conn = self._get_read_conn()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM events WHERE event_group_id = ?", (event_group_id,))
            row = cursor.fetchone()
            if not row:
                return None
            d = dict(row)
            d.setdefault("dominant_color", "unspecified")
            d.setdefault("zone_name", "general")
            d.setdefault("location_id", "loc_primary")
            d.setdefault("duration_sec", 0.0)
            d.setdefault("motion_points_count", 0)
            d.setdefault("metadata_json", "{}")
            return EventRecord(**d)
        finally:
            conn.close()


    def query_events(
        self,
        camera_id: Optional[str] = None,
        min_score: int = 0,
        color: Optional[str] = None,
        zone: Optional[str] = None,
        object_type: Optional[str] = None,
        user_triage: Optional[str] = None,
        location_id: Optional[str] = None,
        limit: int = 50
    ) -> List[EventRecord]:
        """Queries events matching criteria including appearance attributes and location."""
        query = "SELECT * FROM events WHERE score >= ?"
        params: List[Any] = [min_score]

        if camera_id and camera_id.lower() != "all":
            query += " AND camera_id = ?"
            params.append(camera_id)

        if location_id and location_id.lower() != "all":
            query += " AND (location_id = ? OR location_id IS NULL OR location_id = 'loc_primary')"
            params.append(location_id)

        if color and color.lower() != "all":
            query += " AND LOWER(dominant_color) = ?"
            params.append(color.lower())

        if zone and zone.lower() != "all":
            query += " AND LOWER(zone_name) = ?"
            params.append(zone.lower())

        if object_type and object_type.lower() != "all":
            query += " AND LOWER(object_type) = ?"
            params.append(object_type.lower())

        if user_triage and user_triage.lower() != "all":
            query += " AND user_triage = ?"
            params.append(user_triage)

        query += " ORDER BY start_time DESC LIMIT ?"
        params.append(limit)

        conn = self._get_read_conn()
        try:
            cursor = conn.cursor()
            cursor.execute(query, params)
            rows = cursor.fetchall()
            results = []
            for r in rows:
                d = dict(r)
                d.setdefault("dominant_color", "unspecified")
                d.setdefault("zone_name", "general")
                d.setdefault("location_id", "loc_primary")
                d.setdefault("duration_sec", 0.0)
                d.setdefault("motion_points_count", 0)
                d.setdefault("metadata_json", "{}")
                results.append(EventRecord(**d))
            return results
        finally:
            conn.close()

    def search_forensic_events(
        self,
        location_id: Optional[str] = None,
        camera_id: Optional[str] = None,
        object_type: Optional[str] = None,
        color: Optional[str] = None,
        zone: Optional[str] = None,
        min_score: int = 0,
        max_score: int = 100,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        free_text: Optional[str] = None,
        user_triage: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> Dict[str, Any]:
        """
        Executes multi-dimensional forensic investigation search over historical event archive.
        Supports compound filtering by location, camera, classification, date range, score, and free-text.
        """
        where_clauses = ["score >= ? AND score <= ?"]
        params: List[Any] = [min_score, max_score]

        if location_id and location_id.lower() != "all":
            where_clauses.append("(location_id = ? OR location_id IS NULL OR location_id = 'loc_primary')")
            params.append(location_id)

        if camera_id and camera_id.lower() != "all":
            where_clauses.append("camera_id = ?")
            params.append(camera_id)

        if object_type and object_type.lower() != "all":
            where_clauses.append("LOWER(object_type) = ?")
            params.append(object_type.lower())

        if color and color.lower() != "all":
            where_clauses.append("LOWER(dominant_color) = ?")
            params.append(color.lower())

        if zone and zone.lower() != "all":
            where_clauses.append("LOWER(zone_name) = ?")
            params.append(zone.lower())

        if date_from:
            where_clauses.append("start_time >= ?")
            params.append(date_from)

        if date_to:
            where_clauses.append("start_time <= ?")
            params.append(date_to)

        if user_triage and user_triage.lower() != "all":
            where_clauses.append("user_triage = ?")
            params.append(user_triage)

        if free_text and free_text.strip():
            term = f"%{free_text.strip().lower()}%"
            where_clauses.append("(LOWER(camera_id) LIKE ? OR LOWER(object_type) LIKE ? OR LOWER(zone_name) LIKE ? OR LOWER(metadata_json) LIKE ?)")
            params.extend([term, term, term, term])

        where_sql = " AND ".join(where_clauses)
        count_sql = f"SELECT COUNT(*) FROM events WHERE {where_sql}"
        data_sql = f"SELECT * FROM events WHERE {where_sql} ORDER BY start_time DESC LIMIT ? OFFSET ?"

        conn = self._get_read_conn()
        try:
            cursor = conn.cursor()
            cursor.execute(count_sql, params)
            total_matched = cursor.fetchone()[0]

            data_params = list(params) + [limit, offset]
            cursor.execute(data_sql, data_params)
            rows = cursor.fetchall()
            results = []
            for r in rows:
                d = dict(r)
                d.setdefault("dominant_color", "unspecified")
                d.setdefault("zone_name", "general")
                d.setdefault("location_id", "loc_primary")
                d.setdefault("duration_sec", 0.0)
                d.setdefault("motion_points_count", 0)
                d.setdefault("metadata_json", "{}")
                results.append(EventRecord(**d))

            return {
                "status": "success",
                "total_matched": total_matched,
                "count": len(results),
                "limit": limit,
                "offset": offset,
                "events": results
            }
        finally:
            conn.close()

    def purge_synthetic_events(self) -> int:
        """Removes all synthetic / mock camera events and unlinks associated temporary files."""
        conn = self._get_read_conn()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT file_path, thumb_path FROM events WHERE camera_id IN ('cam_corridor', 'cam_cash_counter', 'cam_shutter_night', 'cam_test_01', 'cam_test_02') OR file_path LIKE '%fake%' OR object_type = 'synthetic'"
            )
            rows = cursor.fetchall()
            import os
            for fp, tp in rows:
                if fp and os.path.exists(fp):
                    try: os.unlink(fp)
                    except Exception: pass
                if tp and os.path.exists(tp):
                    try: os.unlink(tp)
                    except Exception: pass
            sql = "DELETE FROM events WHERE camera_id IN ('cam_corridor', 'cam_cash_counter', 'cam_shutter_night', 'cam_test_01', 'cam_test_02') OR file_path LIKE '%fake%' OR object_type = 'synthetic'"
            self.writer.queue.put((sql, (), None))
            return len(rows)
        finally:
            conn.close()

    def close(self):
        """Stops writer worker and drains queue."""
        self.writer.running = False
        self.writer.queue.put(None)
        self.writer.join(timeout=3.0)
