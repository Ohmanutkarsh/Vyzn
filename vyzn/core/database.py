"""
SQLite database engine with WAL mode and Single-Writer Queue architecture.
Eliminates database lock contention across concurrent capture and sync workers.
"""

from __future__ import annotations
import os
import sqlite3
import time
import threading
import queue
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any, Callable, Union, Tuple
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
            metadata_json TEXT DEFAULT '{}',
            clip_number INTEGER,
            expires_at_ms INTEGER,
            sha256 TEXT,
            tier TEXT DEFAULT 'review'
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

        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            phone_e164 TEXT,
            telegram_chat_id TEXT,
            telegram_user_id TEXT,
            telegram_username TEXT,
            telegram_linked_at_ms INTEGER,
            telegram_status TEXT DEFAULT 'not_linked',
            created_at_ms INTEGER NOT NULL,
            updated_at_ms INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            created_at_ms INTEGER NOT NULL,
            expires_at_ms INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS auth_codes (
            email TEXT PRIMARY KEY,
            code TEXT NOT NULL,
            attempts INTEGER DEFAULT 0,
            locked_until_ms INTEGER DEFAULT 0,
            created_at_ms INTEGER NOT NULL,
            expires_at_ms INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS telegram_links (
            token TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            phone_e164 TEXT NOT NULL,
            created_at_ms INTEGER NOT NULL,
            expires_at_ms INTEGER NOT NULL,
            status TEXT DEFAULT 'pending'
        );

        CREATE TABLE IF NOT EXISTS phone_auth_codes (
            phone_e164 TEXT PRIMARY KEY,
            email TEXT,
            code TEXT NOT NULL,
            attempts INTEGER DEFAULT 0,
            locked_until_ms INTEGER DEFAULT 0,
            created_at_ms INTEGER NOT NULL,
            expires_at_ms INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS clip_sequence (
            id INTEGER PRIMARY KEY,
            next_clip_number INTEGER NOT NULL
        );
        INSERT OR IGNORE INTO clip_sequence (id, next_clip_number) VALUES (1, 1);

        CREATE TABLE IF NOT EXISTS deletion_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            clip_number INTEGER,
            camera_id TEXT NOT NULL,
            moment_at_ms INTEGER NOT NULL,
            tier TEXT,
            status TEXT,
            deleted_at_ms INTEGER NOT NULL,
            reason TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS camera_area_stats (
            camera_id TEXT PRIMARY KEY,
            ignored_moments_count INTEGER DEFAULT 0,
            updated_at_ms INTEGER NOT NULL
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
            conn.execute("ALTER TABLE events ADD COLUMN clip_number INTEGER;")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("ALTER TABLE events ADD COLUMN expires_at_ms INTEGER;")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("ALTER TABLE events ADD COLUMN sha256 TEXT;")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("ALTER TABLE events ADD COLUMN tier TEXT DEFAULT 'review';")
        except sqlite3.OperationalError:
            pass

        try:
            conn.execute("ALTER TABLE events ADD COLUMN owner_email TEXT;")
        except sqlite3.OperationalError:
            pass

        try:
            conn.execute("ALTER TABLE telegram_links ADD COLUMN chat_id TEXT;")
        except sqlite3.OperationalError:
            pass

        try:
            conn.execute("ALTER TABLE users ADD COLUMN phone_verified INTEGER DEFAULT 0;")
        except sqlite3.OperationalError:
            pass

        try:
            conn.execute("ALTER TABLE users ADD COLUMN security_pin TEXT DEFAULT '202600';")
        except sqlite3.OperationalError:
            pass

        try:
            conn.execute("ALTER TABLE users ADD COLUMN full_name TEXT;")
        except sqlite3.OperationalError:
            pass

        try:
            conn.execute("ALTER TABLE users ADD COLUMN role TEXT DEFAULT 'shopkeeper';")
        except sqlite3.OperationalError:
            pass

        try:
            conn.execute("CREATE INDEX IF NOT EXISTS idx_events_owner ON events(owner_email);")
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

    def __init__(self, db_path: Union[Path, str]):
        self.db_path = Path(db_path)
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
        """Dispatches an event insert to the writer queue with a pre-2020 timestamp write guard."""
        # DB Write Guard: reject invalid/1970 timestamps
        try:
            st = event.start_time
            if isinstance(st, str):
                dt = datetime.fromisoformat(st.replace("Z", "+00:00"))
            elif isinstance(st, (int, float)):
                dt = datetime.fromtimestamp(st, timezone.utc)
            else:
                dt = st
            if dt.year < 2020:
                err_msg = f"DB Write Guard rejected event {event.event_group_id}: timestamp {event.start_time} is before year 2020."
                logger.error(err_msg)
                if callback:
                    callback(None, ValueError(err_msg))
                return False
        except Exception as e:
            logger.error(f"Timestamp parse error on event {event.event_group_id}: {e}")
            if callback:
                callback(None, e)
            return False

        sql = """
        INSERT OR REPLACE INTO events (
            event_group_id, camera_id, start_time, end_time,
            object_type, confidence, score, status,
            starred, synced, user_triage, file_path, thumb_path,
            dominant_color, zone_name, location_id, duration_sec,
            motion_points_count, metadata_json,
            clip_number, expires_at_ms, sha256, tier, owner_email
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            getattr(event, "metadata_json", "{}"),
            getattr(event, "clip_number", None),
            getattr(event, "expires_at_ms", None),
            getattr(event, "sha256", None),
            getattr(event, "tier", "review"),
            getattr(event, "owner_email", None)
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

    def get_audit_logs(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Retrieves latest audit log entries."""
        conn = self._get_read_conn()
        try:
            cursor = conn.execute(
                "SELECT id, timestamp_utc, action, event_group_id, details FROM audit_log ORDER BY id DESC LIMIT ?",
                (limit,)
            )
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

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

    @staticmethod
    def _row_to_event(d: Dict[str, Any]) -> EventRecord:
        import dataclasses
        valid_fields = {f.name for f in dataclasses.fields(EventRecord)}
        filtered = {k: v for k, v in d.items() if k in valid_fields}
        filtered.setdefault("dominant_color", "unspecified")
        filtered.setdefault("zone_name", "general")
        filtered.setdefault("location_id", "loc_primary")
        filtered.setdefault("duration_sec", 0.0)
        filtered.setdefault("motion_points_count", 0)
        filtered.setdefault("metadata_json", "{}")
        filtered.setdefault("tier", "review")
        return EventRecord(**filtered)

    def get_event(self, event_group_id: str) -> Optional[EventRecord]:
        """Reads a single event by ID."""
        conn = self._get_read_conn()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM events WHERE event_group_id = ?", (event_group_id,))
            row = cursor.fetchone()
            if not row:
                return None
            return self._row_to_event(dict(row))
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
            results = [self._row_to_event(dict(r)) for r in rows]
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
            results = [self._row_to_event(dict(r)) for r in rows]

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

    # -------------------------------------------------------------------------
    # v1.1 User, Authentication, and Telegram Link Methods
    # -------------------------------------------------------------------------

    def get_or_create_user(self, email: str) -> Dict[str, Any]:
        """Retrieves user by normalized email or creates a new user profile."""
        norm_email = email.strip().lower()
        now_ms = int(time.time() * 1000)
        conn = self._get_read_conn()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE email = ?", (norm_email,))
            row = cursor.fetchone()
            if row:
                return dict(row)
        finally:
            conn.close()

        import uuid
        user_id = f"usr_{uuid.uuid4().hex[:12]}"
        sql = """
        INSERT INTO users (id, email, phone_e164, telegram_chat_id, telegram_user_id,
                           telegram_username, telegram_linked_at_ms, telegram_status,
                           created_at_ms, updated_at_ms)
        VALUES (?, ?, NULL, NULL, NULL, NULL, NULL, 'not_linked', ?, ?)
        """
        self.writer.queue.put((sql, (user_id, norm_email, now_ms, now_ms), None))
        self.flush()
        return {
            "id": user_id,
            "email": norm_email,
            "phone_e164": None,
            "telegram_chat_id": None,
            "telegram_user_id": None,
            "telegram_username": None,
            "telegram_linked_at_ms": None,
            "telegram_status": "not_linked",
            "created_at_ms": now_ms,
            "updated_at_ms": now_ms
        }

    def get_user_by_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        conn = self._get_read_conn()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def update_user_phone(self, user_id: str, phone_e164: str, verified: bool = False):
        now_ms = int(time.time() * 1000)
        sql = "UPDATE users SET phone_e164 = ?, phone_verified = ?, updated_at_ms = ? WHERE id = ?"
        self.writer.queue.put((sql, (phone_e164, 1 if verified else 0, now_ms, user_id), None))
        self.flush()

    def update_user_phone_verified(self, user_id: str, phone_e164: str):
        self.update_user_phone(user_id, phone_e164, verified=True)

    def update_user_telegram(self, user_id: str, chat_id: str, telegram_user_id: str, username: Optional[str] = None):
        now_ms = int(time.time() * 1000)
        sql = """
        UPDATE users
        SET telegram_chat_id = ?, telegram_user_id = ?, telegram_username = ?,
            telegram_linked_at_ms = ?, telegram_status = 'linked', updated_at_ms = ?
        WHERE id = ?
        """
        self.writer.queue.put((sql, (str(chat_id), str(telegram_user_id), username, now_ms, now_ms, user_id), None))
        self.flush()

    def store_auth_code(self, email: str, code: str, ttl_sec: int = 600):
        norm_email = email.strip().lower()
        now_ms = int(time.time() * 1000)
        expires_at_ms = now_ms + ttl_sec * 1000
        sql = """
        INSERT INTO auth_codes (email, code, attempts, locked_until_ms, created_at_ms, expires_at_ms)
        VALUES (?, ?, 0, 0, ?, ?)
        ON CONFLICT(email) DO UPDATE SET
            code = excluded.code,
            attempts = 0,
            locked_until_ms = 0,
            created_at_ms = excluded.created_at_ms,
            expires_at_ms = excluded.expires_at_ms
        """
        self.writer.queue.put((sql, (norm_email, code, now_ms, expires_at_ms), None))
        self.flush()

    def verify_auth_code(self, email: str, code: str) -> Tuple[bool, str]:
        norm_email = email.strip().lower()
        now_ms = int(time.time() * 1000)
        conn = self._get_read_conn()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT code, attempts, locked_until_ms, expires_at_ms FROM auth_codes WHERE email = ?", (norm_email,))
            row = cursor.fetchone()
            if not row:
                return False, "expired"

            stored_code, attempts, locked_until, expires_at = row["code"], row["attempts"], row["locked_until_ms"], row["expires_at_ms"]

            if locked_until and now_ms < locked_until:
                return False, "locked"

            if now_ms > expires_at:
                return False, "expired"

            if str(code).strip() != str(stored_code):
                new_attempts = attempts + 1
                lock_time = (now_ms + 15 * 60 * 1000) if new_attempts >= 5 else 0
                sql = "UPDATE auth_codes SET attempts = ?, locked_until_ms = ? WHERE email = ?"
                self.writer.queue.put((sql, (new_attempts, lock_time, norm_email), None))
                self.flush()
                if new_attempts >= 5:
                    return False, "locked"
                return False, "wrong_code"

            # Code verified -> delete code record
            self.writer.queue.put(("DELETE FROM auth_codes WHERE email = ?", (norm_email,), None))
            self.flush()
            return True, "ok"
        finally:
            conn.close()

    def store_phone_auth_code(self, phone_e164: str, code: str, email: Optional[str] = None, ttl_sec: int = 300):
        norm_phone = phone_e164.strip()
        now_ms = int(time.time() * 1000)
        expires_at_ms = now_ms + ttl_sec * 1000
        sql = """
        INSERT INTO phone_auth_codes (phone_e164, email, code, attempts, locked_until_ms, created_at_ms, expires_at_ms)
        VALUES (?, ?, ?, 0, 0, ?, ?)
        ON CONFLICT(phone_e164) DO UPDATE SET
            email = excluded.email,
            code = excluded.code,
            attempts = 0,
            locked_until_ms = 0,
            created_at_ms = excluded.created_at_ms,
            expires_at_ms = excluded.expires_at_ms
        """
        self.writer.queue.put((sql, (norm_phone, email, code, now_ms, expires_at_ms), None))
        self.flush()

    def verify_phone_auth_code(self, phone_e164: str, code: str) -> Tuple[bool, str]:
        norm_phone = phone_e164.strip()
        now_ms = int(time.time() * 1000)
        conn = self._get_read_conn()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT code, attempts, locked_until_ms, expires_at_ms FROM phone_auth_codes WHERE phone_e164 = ?", (norm_phone,))
            row = cursor.fetchone()
            if not row:
                return False, "expired"

            stored_code, attempts, locked_until, expires_at = row["code"], row["attempts"], row["locked_until_ms"], row["expires_at_ms"]

            if locked_until and now_ms < locked_until:
                return False, "locked"

            if now_ms > expires_at:
                return False, "expired"

            if str(code).strip() != str(stored_code):
                new_attempts = attempts + 1
                lock_time = (now_ms + 15 * 60 * 1000) if new_attempts >= 5 else 0
                sql = "UPDATE phone_auth_codes SET attempts = ?, locked_until_ms = ? WHERE phone_e164 = ?"
                self.writer.queue.put((sql, (new_attempts, lock_time, norm_phone), None))
                self.flush()
                if new_attempts >= 5:
                    return False, "locked"
                return False, "wrong_code"

            # Code verified -> delete code record
            self.writer.queue.put(("DELETE FROM phone_auth_codes WHERE phone_e164 = ?", (norm_phone,), None))
            self.flush()
            return True, "ok"
        finally:
            conn.close()

    def create_session(self, user_id: str, ttl_sec: int = 30 * 86400) -> str:
        import secrets
        token = secrets.token_hex(32)
        now_ms = int(time.time() * 1000)
        expires_at_ms = now_ms + ttl_sec * 1000
        sql = "INSERT INTO sessions (token, user_id, created_at_ms, expires_at_ms) VALUES (?, ?, ?, ?)"
        self.writer.queue.put((sql, (token, user_id, now_ms, expires_at_ms), None))
        self.flush()
        return token

    def get_session_user(self, token: str) -> Optional[Dict[str, Any]]:
        if not token:
            return None
        now_ms = int(time.time() * 1000)
        conn = self._get_read_conn()
        try:
            cursor = conn.cursor()
            cursor.execute("""
            SELECT u.* FROM users u
            JOIN sessions s ON u.id = s.user_id
            WHERE s.token = ? AND s.expires_at_ms > ?
            """, (token, now_ms))
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def delete_session(self, token: str):
        if token:
            self.writer.queue.put(("DELETE FROM sessions WHERE token = ?", (token,), None))
            self.flush()

    def create_telegram_link(self, user_id: str, phone_e164: str, ttl_sec: int = 600) -> str:
        import secrets
        token = secrets.token_urlsafe(16)
        now_ms = int(time.time() * 1000)
        expires_at_ms = now_ms + ttl_sec * 1000
        sql = "INSERT OR REPLACE INTO telegram_links (token, user_id, phone_e164, created_at_ms, expires_at_ms, status, chat_id) VALUES (?, ?, ?, ?, ?, 'pending', NULL)"
        self.writer.queue.put((sql, (token, user_id, phone_e164, now_ms, expires_at_ms), None))
        self.flush()
        return token

    def get_telegram_link(self, token: str) -> Optional[Dict[str, Any]]:
        conn = self._get_read_conn()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM telegram_links WHERE token = ?", (token,))
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def get_latest_telegram_link_for_user(self, user_id: str) -> Optional[Dict[str, Any]]:
        conn = self._get_read_conn()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM telegram_links WHERE user_id = ? ORDER BY created_at_ms DESC LIMIT 1", (user_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def update_telegram_link_status(self, token: str, status: str):
        sql = "UPDATE telegram_links SET status = ? WHERE token = ?"
        self.writer.queue.put((sql, (status, token), None))
        self.flush()

    def update_telegram_link_chat(self, token: str, chat_id: str):
        sql = "UPDATE telegram_links SET chat_id = ? WHERE token = ?"
        self.writer.queue.put((sql, (str(chat_id), token), None))
        self.flush()

    def get_telegram_link_by_chat_id(self, chat_id: str) -> Optional[Dict[str, Any]]:
        conn = self._get_read_conn()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM telegram_links WHERE chat_id = ? AND status = 'pending' ORDER BY created_at_ms DESC LIMIT 1", (str(chat_id),))
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def get_next_clip_number(self) -> int:
        """Returns monotonically increasing clip sequence number that is never reused."""
        conn = self._get_read_conn()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT next_clip_number FROM clip_sequence WHERE id = 1")
            row = cursor.fetchone()
            current_num = row[0] if row else 1
            sql = "UPDATE clip_sequence SET next_clip_number = next_clip_number + 1 WHERE id = 1"
            self.writer.queue.put((sql, (), None))
            self.flush()
            return current_num
        finally:
            conn.close()

    def log_deletion(self, clip_number: Optional[int], camera_id: str, moment_at_ms: int, tier: Optional[str], status: Optional[str], reason: str):
        now_ms = int(time.time() * 1000)
        sql = "INSERT INTO deletion_log (clip_number, camera_id, moment_at_ms, tier, status, deleted_at_ms, reason) VALUES (?, ?, ?, ?, ?, ?, ?)"
        self.writer.queue.put((sql, (clip_number, camera_id, moment_at_ms, tier, status, now_ms, reason), None))

    def get_deletion_logs(self, camera_id: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        """Retrieves recent deletion records for verification."""
        conn = self._get_read_conn()
        try:
            if camera_id:
                cursor = conn.execute(
                    "SELECT id, clip_number, camera_id, moment_at_ms, tier, status, deleted_at_ms, reason FROM deletion_log WHERE camera_id = ? ORDER BY id DESC LIMIT ?",
                    (camera_id, limit)
                )
            else:
                cursor = conn.execute(
                    "SELECT id, clip_number, camera_id, moment_at_ms, tier, status, deleted_at_ms, reason FROM deletion_log ORDER BY id DESC LIMIT ?",
                    (limit,)
                )
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def increment_ignored_moments(self, camera_id: str, count: int = 1):
        """Increments count of moments dropped because they were outside every watch area."""
        now_ms = int(time.time() * 1000)
        sql = """
        INSERT INTO camera_area_stats (camera_id, ignored_moments_count, updated_at_ms)
        VALUES (?, ?, ?)
        ON CONFLICT(camera_id) DO UPDATE SET
            ignored_moments_count = ignored_moments_count + excluded.ignored_moments_count,
            updated_at_ms = excluded.updated_at_ms;
        """
        self.writer.queue.put((sql, (camera_id, count, now_ms), None))

    def get_ignored_moments_count(self, camera_id: str) -> int:
        """Retrieves count of moments outside watch areas that were ignored."""
        conn = self._get_read_conn()
        try:
            cursor = conn.execute(
                "SELECT ignored_moments_count FROM camera_area_stats WHERE camera_id = ?",
                (camera_id,)
            )
            row = cursor.fetchone()
            return int(row[0]) if row and row[0] is not None else 0
        finally:
            conn.close()

    def reset_ignored_moments(self, camera_id: str):
        """Resets ignored moments counter for a camera (e.g. on new area creation)."""
        now_ms = int(time.time() * 1000)
        sql = """
        INSERT INTO camera_area_stats (camera_id, ignored_moments_count, updated_at_ms)
        VALUES (?, 0, ?)
        ON CONFLICT(camera_id) DO UPDATE SET
            ignored_moments_count = 0,
            updated_at_ms = excluded.updated_at_ms;
        """
        self.writer.queue.put((sql, (camera_id, now_ms), None))

    @staticmethod
    def _row_to_clip_dict(row: Dict[str, Any]) -> Dict[str, Any]:
        """Maps an events table row to the canonical Section 7.2 Clip data contract."""
        meta = {}
        raw_meta = row.get("metadata_json") or "{}"
        if isinstance(raw_meta, str):
            try:
                import json
                meta = json.loads(raw_meta)
            except Exception:
                meta = {}
        elif isinstance(raw_meta, dict):
            meta = raw_meta

        st_str = row.get("start_time") or ""
        try:
            st_dt = datetime.fromisoformat(st_str.replace("Z", "+00:00"))
            start_ms = int(st_dt.timestamp() * 1000)
        except Exception:
            start_ms = int(time.time() * 1000)

        et_str = row.get("end_time")
        if et_str:
            try:
                et_dt = datetime.fromisoformat(et_str.replace("Z", "+00:00"))
                end_ms = int(et_dt.timestamp() * 1000)
            except Exception:
                end_ms = start_ms + int((row.get("duration_sec") or 15.0) * 1000)
        else:
            end_ms = start_ms + int((row.get("duration_sec") or 15.0) * 1000)

        trigger_ms = meta.get("trigger_ms")
        if not trigger_ms:
            trigger_offset_sec = meta.get("trigger_offset_sec", 3.0)
            trigger_ms = start_ms + int(trigger_offset_sec * 1000)

        raw_triage = row.get("user_triage") or "unreviewed"
        if raw_triage in ("unreviewed", "reviewed", "not_an_issue"):
            status = raw_triage
        elif raw_triage == "confirmed_threat":
            status = "reviewed"
        elif raw_triage == "false_positive":
            status = "not_an_issue"
        else:
            status = "unreviewed"

        tier = row.get("tier")
        if tier not in ("alert", "review"):
            tier = "alert" if (row.get("score") or 0) >= 70 else "review"

        area_name = row.get("zone_name")
        if area_name in ("general", "unspecified", "", None):
            area_name = None

        camera_id = row.get("camera_id") or "camera"
        cam_name = meta.get("camera_name") or camera_id

        # Parse or synthesize reasons
        reasons = meta.get("reasons")
        if not reasons or not isinstance(reasons, list) or len(reasons) == 0:
            obj_type = row.get("object_type") or "person"
            conf = row.get("confidence") or 0.85
            dur = row.get("duration_sec") or 0.0
            reasons = []
            if obj_type == "person":
                reasons.append({
                    "code": "person_detected",
                    "params": {"confidence": round(conf, 2), "area": area_name or "Camera view"}
                })
                if dur >= 10.0:
                    reasons.insert(0, {
                        "code": "stayed_in_area",
                        "params": {"seconds": int(dur), "duration": f"{int(dur)} seconds", "area": area_name or "Camera view"}
                    })
            else:
                reasons.append({
                    "code": "movement",
                    "params": {"area": area_name or "Camera view"}
                })

        # Monotonically increasing / unique clip sequence number
        clip_num = row.get("clip_number")
        if not clip_num:
            try:
                clip_num = int("".join(c for c in str(row.get("event_group_id")) if c.isdigit())[:4]) or 1
            except Exception:
                clip_num = 1

        ev_id = str(row.get("event_group_id") or "")
        expires_at_ms = row.get("expires_at_ms") or (start_ms + 72 * 3600 * 1000)

        d_sec = row.get("duration_sec") or round((end_ms - start_ms) / 1000.0, 1)
        thumb_url = f"/api/clips/{ev_id}/thumb"
        video_url = f"/api/clips/{ev_id}/video"

        return {
            "id": ev_id,
            "number": clip_num,
            "clip_number": clip_num,
            "cameraId": camera_id,
            "camera_id": camera_id,
            "cameraName": cam_name,
            "camera_name": cam_name,
            "areaId": meta.get("area_id"),
            "areaName": area_name,
            "watch_area_name": area_name,
            "startMs": start_ms,
            "started_at_ms": start_ms,
            "endMs": end_ms,
            "ended_at_ms": end_ms,
            "triggerMs": trigger_ms,
            "trigger_ms": trigger_ms,
            "tier": tier,
            "status": status,
            "reasons": reasons,
            "objects": meta.get("objects", [{"cls": row.get("object_type") or "person", "confidence": round(row.get("confidence") or 0.85, 2)}]),
            "thumbnailUrl": thumb_url,
            "previewUrl": video_url,
            "videoUrl": video_url,
            "urls": {
                "video": video_url,
                "thumb": thumb_url
            },
            "boxes": meta.get("boxes", []),
            "sha256": row.get("sha256") or meta.get("sha256", ""),
            "detector": meta.get("detector", {"name": "YOLOv8n-VYZN", "version": "8.0.196"}),
            "expiresAtMs": expires_at_ms,
            "expires_at_ms": expires_at_ms,
            "reviewedAtMs": meta.get("reviewed_at_ms"),
            "reviewed_at_ms": meta.get("reviewed_at_ms"),
            "feedback": meta.get("feedback"),
            "score": row.get("score") or 0,
            "durationSec": d_sec,
            "duration_seconds": d_sec,
            "filePath": row.get("file_path") or "",
            "thumbPath": row.get("thumb_path") or "",
            "ownerEmail": row.get("owner_email"),
            "owner_email": row.get("owner_email")
        }

    def query_clips(
        self,
        camera_id: Optional[str] = None,
        camera_ids: Optional[List[str]] = None,
        owner_email: Optional[str] = None,
        tier: Optional[str] = None,
        status: Optional[str] = None,
        object_type: Optional[str] = None,
        from_ms: Optional[int] = None,
        to_ms: Optional[int] = None,
        limit: int = 50,
        offset: int = 0,
        page: Optional[int] = None,
        per_page: Optional[int] = None
    ) -> Dict[str, Any]:
        """Queries clips matching compound filters with exact counts and pagination."""
        if page is not None and per_page is not None:
            limit = per_page
            offset = max(0, (page - 1) * per_page)

        where_clauses = ["status != 'deleted'"]
        params: List[Any] = []

        if camera_ids is not None:
            if not camera_ids:
                # User owns no cameras: return empty set immediately
                where_clauses.append("1=0")
            else:
                placeholders = ",".join("?" for _ in camera_ids)
                where_clauses.append(f"camera_id IN ({placeholders})")
                params.extend(camera_ids)

        if camera_id and camera_id.lower() != "all":
            where_clauses.append("camera_id = ?")
            params.append(camera_id)

        if owner_email:
            where_clauses.append("owner_email = ?")
            params.append(owner_email)

        if tier and tier.lower() != "all":
            where_clauses.append("tier = ?")
            params.append(tier.lower())

        if status and status.lower() != "all":
            if status.lower() == "unreviewed":
                where_clauses.append("(user_triage = 'unreviewed' OR user_triage IS NULL)")
            elif status.lower() == "reviewed":
                where_clauses.append("(user_triage = 'reviewed' OR user_triage = 'confirmed_threat')")
            elif status.lower() == "not_an_issue":
                where_clauses.append("(user_triage = 'not_an_issue' OR user_triage = 'false_positive')")
            else:
                where_clauses.append("user_triage = ?")
                params.append(status.lower())

        if object_type and object_type.lower() != "all":
            where_clauses.append("LOWER(object_type) = ?")
            params.append(object_type.lower())

        if from_ms:
            from_iso = datetime.fromtimestamp(from_ms / 1000.0, timezone.utc).isoformat()
            where_clauses.append("start_time >= ?")
            params.append(from_iso)

        if to_ms:
            to_iso = datetime.fromtimestamp(to_ms / 1000.0, timezone.utc).isoformat()
            where_clauses.append("start_time <= ?")
            params.append(to_iso)

        where_sql = " AND ".join(where_clauses)
        count_sql = f"SELECT COUNT(*) FROM events WHERE {where_sql}"
        data_sql = f"SELECT * FROM events WHERE {where_sql} ORDER BY start_time DESC LIMIT ? OFFSET ?"

        conn = self._get_read_conn()
        try:
            cursor = conn.cursor()
            cursor.execute(count_sql, params)
            total = cursor.fetchone()[0]

            cursor.execute(data_sql, params + [limit, offset])
            rows = cursor.fetchall()
            clips = [self._row_to_clip_dict(dict(r)) for r in rows]

            cur_page = (offset // limit) + 1 if limit > 0 else 1
            tot_pages = (total + limit - 1) // limit if limit > 0 else 1

            return {
                "total": total,
                "clips": clips,
                "limit": limit,
                "offset": offset,
                "page": cur_page,
                "per_page": limit,
                "total_pages": tot_pages
            }
        finally:
            conn.close()

    def get_clip_by_id(self, clip_id_or_number: Union[str, int]) -> Optional[Dict[str, Any]]:
        """Retrieves a single clip by its string ID or sequential number."""
        conn = self._get_read_conn()
        try:
            cursor = conn.cursor()
            if isinstance(clip_id_or_number, int) or (isinstance(clip_id_or_number, str) and clip_id_or_number.isdigit()):
                cursor.execute("SELECT * FROM events WHERE clip_number = ? OR event_group_id = ?", (int(clip_id_or_number), str(clip_id_or_number)))
            elif isinstance(clip_id_or_number, str) and clip_id_or_number.lower().startswith("clip-"):
                num_str = clip_id_or_number.lower().replace("clip-", "").lstrip("0") or "0"
                if num_str.isdigit():
                    cursor.execute("SELECT * FROM events WHERE clip_number = ? OR event_group_id = ?", (int(num_str), str(clip_id_or_number)))
                else:
                    cursor.execute("SELECT * FROM events WHERE event_group_id = ?", (str(clip_id_or_number),))
            else:
                cursor.execute("SELECT * FROM events WHERE event_group_id = ?", (str(clip_id_or_number),))
            row = cursor.fetchone()
            if not row:
                return None
            return self._row_to_clip_dict(dict(row))
        finally:
            conn.close()

    def get_unreviewed_flags(
        self,
        limit: int = 10,
        camera_ids: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Retrieves unreviewed flags for Overview.
        Order: Alert first, then Review, newest first within each.
        Also calculates total unreviewed waiting count and flags expiring within 12h.
        """
        now_ms = int(time.time() * 1000)
        twelve_hours_ms = 12 * 3600 * 1000

        cam_clause = ""
        cam_params: List[Any] = []
        if camera_ids is not None:
            if not camera_ids:
                return {"flags": [], "total": 0, "totalWaiting": 0, "expires_soon_count": 0, "expiringSoonCount": 0}
            placeholders = ",".join("?" for _ in camera_ids)
            cam_clause = f" AND camera_id IN ({placeholders})"
            cam_params = list(camera_ids)

        conn = self._get_read_conn()
        try:
            cursor = conn.cursor()
            # Total waiting
            cursor.execute(f"SELECT COUNT(*) FROM events WHERE status != 'deleted' AND (user_triage = 'unreviewed' OR user_triage IS NULL){cam_clause}", cam_params)
            total_waiting = cursor.fetchone()[0]

            # Expiring within 12h: expires_at_ms <= now_ms + twelve_hours_ms
            sixty_hours_ago_iso = datetime.fromtimestamp((now_ms - 60 * 3600 * 1000) / 1000.0, timezone.utc).isoformat()
            cursor.execute(f"""
                SELECT COUNT(*) FROM events
                WHERE status != 'deleted' AND (user_triage = 'unreviewed' OR user_triage IS NULL){cam_clause}
                AND (
                    (expires_at_ms IS NOT NULL AND expires_at_ms <= ?)
                    OR (expires_at_ms IS NULL AND start_time <= ?)
                )
            """, cam_params + [now_ms + twelve_hours_ms, sixty_hours_ago_iso])
            expiring_soon = cursor.fetchone()[0]

            # Flags ordered by alert then review, newest first within each
            cursor.execute(f"""
                SELECT * FROM events
                WHERE status != 'deleted' AND (user_triage = 'unreviewed' OR user_triage IS NULL){cam_clause}
                ORDER BY (CASE WHEN tier = 'alert' THEN 0 ELSE 1 END), start_time DESC
                LIMIT ?
            """, cam_params + [limit])
            rows = cursor.fetchall()
            flags = [self._row_to_clip_dict(dict(r)) for r in rows]

            return {
                "flags": flags,
                "total": total_waiting,
                "totalWaiting": total_waiting,
                "expires_soon_count": expiring_soon,
                "expiringSoonCount": expiring_soon
            }
        finally:
            conn.close()

    def delete_clip(self, clip_id_or_number: Union[str, int]) -> bool:
        """Permanently deletes a clip from SQLite index and local disk storage."""
        conn = self._get_read_conn()
        row = None
        try:
            cursor = conn.cursor()
            if isinstance(clip_id_or_number, int) or (isinstance(clip_id_or_number, str) and clip_id_or_number.isdigit()):
                cursor.execute("SELECT * FROM events WHERE clip_number = ? OR event_group_id = ?", (int(clip_id_or_number), str(clip_id_or_number)))
            else:
                cursor.execute("SELECT * FROM events WHERE event_group_id = ?", (str(clip_id_or_number),))
            r = cursor.fetchone()
            if r:
                row = dict(r)
        finally:
            conn.close()

        if not row:
            return False

        ev_id = row["event_group_id"]
        file_path = row.get("file_path")
        thumb_path = row.get("thumb_path")

        # Delete physical files from disk
        for p in (file_path, thumb_path):
            if p and os.path.exists(p):
                try:
                    os.remove(p)
                except Exception as e:
                    logger.warning(f"Could not remove physical media file {p}: {e}")

        # Mark deleted in SQLite and remove record
        now_ms = int(time.time() * 1000)
        sql_del = "DELETE FROM events WHERE event_group_id = ?"
        self.writer.queue.put((sql_del, (ev_id,), None))

        # Log to deletion_log table
        self.log_deletion(
            clip_number=row.get("clip_number") or 0,
            camera_id=row.get("camera_id") or "unknown",
            moment_at_ms=now_ms,
            tier=row.get("tier") or "review",
            status="user_deleted",
            reason="User deleted evidence clip with security verification"
        )
        self.log_audit("CLIP_DELETED", ev_id, f"clip_number={row.get('clip_number')}")
        self.flush()
        return True

    def update_user_security_pin(self, user_id: str, new_pin: str):
        """Updates user 6-digit security PIN for critical action gates."""
        now_ms = int(time.time() * 1000)
        sql = "UPDATE users SET security_pin = ?, updated_at_ms = ? WHERE id = ?"
        self.writer.queue.put((sql, (str(new_pin).strip(), now_ms, user_id), None))
        self.flush()

    def update_clip_status(
        self,
        clip_id: str,
        status: str,
        feedback: Optional[Dict[str, Any]] = None,
        feedback_reason: Optional[str] = None,
        feedback_other: Optional[str] = None
    ) -> bool:
        """
        Updates clip triage status ('reviewed', 'not_an_issue', 'unreviewed')
        and writes review metadata and feedback.
        """
        if feedback_reason and not feedback:
            feedback = {"reason": feedback_reason, "other": feedback_other or ""}
        import json
        conn = self._get_read_conn()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT metadata_json FROM events WHERE event_group_id = ?", (clip_id,))
            row = cursor.fetchone()
            if not row:
                return False
            raw_meta = row[0] or "{}"
            try:
                meta = json.loads(raw_meta) if isinstance(raw_meta, str) else dict(raw_meta)
            except Exception:
                meta = {}
        finally:
            conn.close()

        now_ms = int(time.time() * 1000)
        norm_status = status.lower().strip()
        if norm_status in ("reviewed", "not_an_issue"):
            meta["reviewed_at_ms"] = now_ms
            if feedback:
                meta["feedback"] = feedback
        elif norm_status == "unreviewed":
            meta.pop("reviewed_at_ms", None)
            meta.pop("feedback", None)

        meta_str = json.dumps(meta)
        sql = "UPDATE events SET user_triage = ?, metadata_json = ? WHERE event_group_id = ?"
        self.writer.queue.put((sql, (norm_status, meta_str, clip_id), None))
        self.log_audit("CLIP_STATUS_UPDATED", clip_id, f"Status: {norm_status}, Feedback: {feedback or 'none'}")
        self.flush()
        return True

    def flush(self):
        """Flushes all queued write operations synchronously."""
        self.writer.queue.join()

    def close(self):
        """Stops writer worker and drains queue."""
        self.writer.running = False
        self.writer.queue.put(None)
        self.writer.join(timeout=3.0)
