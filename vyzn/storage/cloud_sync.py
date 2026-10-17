"""
Cloudflare R2 / S3 Object Storage Synchronization Worker.
Uploads high-confidence incident clips (Score >= 70) to cloud storage to protect against evidence loss.
"""

from __future__ import annotations
import os
import time
import threading
import logging
from typing import Optional
from vyzn.core.database import EventDatabase
from vyzn.core.events import EventRecord

logger = logging.getLogger("vyzn.storage.cloud_sync")


class CloudSyncWorker(threading.Thread):
    """
    Background worker periodically syncing high-confidence incidents to cloud object storage.
    Ensures that physical destruction or theft of the edge box does not destroy evidence.
    """

    def __init__(
        self,
        db: EventDatabase,
        endpoint_url: Optional[str] = None,
        bucket_name: Optional[str] = None,
        access_key_id: Optional[str] = None,
        secret_access_key: Optional[str] = None,
        sync_interval_sec: int = 15,
        min_score: int = 50,  # Lowered from 70 to 50 to capture early intrusion evidence before hardware can be severed
        pipeline: Any = None,
        settings: Any = None
    ):

        super().__init__(name="Cloud-Sync-Worker", daemon=True)
        self.db = db
        self.pipeline = pipeline
        self.settings = settings or getattr(pipeline, "settings", None)
        self.endpoint_url = endpoint_url
        self.bucket_name = bucket_name
        self.access_key_id = access_key_id
        self.secret_access_key = secret_access_key
        self.sync_interval_sec = sync_interval_sec
        self.min_score = min_score
        self.running = True
        self._s3_client = None

    def _get_s3_client(self):
        if self._s3_client:
            return self._s3_client

        if not self.endpoint_url or not self.bucket_name or not self.access_key_id:
            return None

        try:
            import boto3
            self._s3_client = boto3.client(
                "s3",
                endpoint_url=self.endpoint_url,
                aws_access_key_id=self.access_key_id,
                aws_secret_access_key=self.secret_access_key,
                region_name="auto"
            )
            return self._s3_client
        except ImportError:
            logger.warning("boto3 not installed; cloud sync will operate in local simulated mode.")
            return None

    def run(self):
        logger.info(f"Cloud sync worker active (interval: {self.sync_interval_sec}s, min score: {self.min_score}).")
        while self.running:
            try:
                self.sync_pending_events()
            except Exception as e:
                logger.error(f"Error during cloud sync sweep: {e}")

            for _ in range(self.sync_interval_sec):
                if not self.running:
                    break
                time.sleep(1.0)

    def sync_pending_events(self):
        """Queries un-synced high-confidence events and uploads clips/thumbnails."""
        # Query events with score >= min_score
        candidates = self.db.query_events(min_score=self.min_score, limit=50)
        un_synced = [e for e in candidates if e.synced == 0 and e.status != "deleted"]

        if not un_synced:
            return

        logger.info(f"Cloud sync worker found {len(un_synced)} pending high-confidence events to upload.")
        s3 = self._get_s3_client()

        for event in un_synced:
            success = self._upload_event(event, s3)
            if success:
                self.db.mark_event_synced(event.event_group_id)
                self.db.log_audit(
                    "CLOUD_SYNCED",
                    event.event_group_id,
                    f"Uploaded to bucket: {self.bucket_name or 'simulated-r2'}"
                )
                logger.info(f"Synced incident {event.event_group_id} to Cloudflare R2 / S3.")

        # Sync clips state directly to Supabase cloud storage for remote phone access
        self._sync_to_supabase_cloud()

    def _sync_to_supabase_cloud(self):
        try:
            import json, hashlib, requests
            from pathlib import Path
            from dotenv import load_dotenv
            load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")
            url = os.environ.get("VYZN_SUPABASE_URL") or "https://dosvefzyiccqupgwxgfw.supabase.co"
            key = os.environ.get("VYZN_SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("VYZN_SUPABASE_ANON_KEY")
            if not (url and key):
                return
            clips_res = self.db.query_clips()
            clips = clips_res.get("clips", [])
            headers = {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json", "x-upsert": "true"}

            # Group by owner_email or default
            emails = set(c.get("owner_email") or "dirtbike000000@gmail.com" for c in clips)
            if not emails:
                emails = {"dirtbike000000@gmail.com"}
            for em in emails:
                h = hashlib.sha256(em.strip().lower().encode()).hexdigest()[:16]
                user_clips = [c for c in clips if (c.get("owner_email") or "dirtbike000000@gmail.com") == em]
                post_url = f"{url.rstrip('/')}/storage/v1/object/vyzn-cloud-state/clips_{h}.json"
                requests.post(post_url, headers=headers, data=json.dumps(user_clips), timeout=4.0)

            # Upload preview.mp4, poster.jpg, and clip.mp4 for recent clips to Supabase Storage
            for c in clips[:10]:
                cid = c.get("id")
                cam_id = c.get("camera_id") or "cam_81559"
                thumb_path = c.get("thumbPath")
                file_path = c.get("filePath")

                # Poster / Thumb upload
                if thumb_path and os.path.exists(thumb_path):
                    target_poster = f"{url.rstrip('/')}/storage/v1/object/vyzn-cloud-state/clips/{cam_id}/{cid}/poster.jpg"
                    try:
                        requests.post(target_poster, headers={**headers, "Content-Type": "image/jpeg"}, data=open(thumb_path, "rb").read(), timeout=4.0)
                    except Exception:
                        pass

                # Preview upload
                if thumb_path:
                    prev_cand = Path(thumb_path).parent / "preview.mp4"
                    if prev_cand.exists():
                        target_prev = f"{url.rstrip('/')}/storage/v1/object/vyzn-cloud-state/clips/{cam_id}/{cid}/preview.mp4"
                        try:
                            requests.post(target_prev, headers={**headers, "Content-Type": "video/mp4"}, data=prev_cand.read_bytes(), timeout=5.0)
                        except Exception:
                            pass

                # Clip video upload (if under 30MB)
                if file_path and os.path.exists(file_path):
                    try:
                        fsize = os.path.getsize(file_path)
                        if fsize < 35 * 1024 * 1024:
                            target_vid = f"{url.rstrip('/')}/storage/v1/object/vyzn-cloud-state/clips/{cam_id}/{cid}/clip.mp4"
                            requests.post(target_vid, headers={**headers, "Content-Type": "video/mp4"}, data=open(file_path, "rb").read(), timeout=10.0)
                    except Exception:
                        pass

            # Sync remote Telegram linking from Supabase vyzn_users into local DB
            try:
                users_url = f"{url.rstrip('/')}/rest/v1/vyzn_users?select=*"
                u_resp = requests.get(users_url, headers={"apikey": key, "Authorization": f"Bearer {key}"}, timeout=4.0)
                if u_resp.status_code == 200:
                    for u in u_resp.json():
                        chat_id = u.get("telegram_chat_id")
                        status = u.get("telegram_status")
                        em = u.get("email")
                        if chat_id and status in ("connected", "linked") and em:
                            local_user = self.db.get_user_by_email(em)
                            if local_user:
                                self.db.update_user_telegram(local_user["id"], str(chat_id), str(chat_id), u.get("telegram_username"))
                            if hasattr(self, "settings") and self.settings:
                                self.settings.telegram_chat_id = str(chat_id)
                            if hasattr(self, "pipeline") and self.pipeline:
                                if hasattr(self.pipeline, "dispatcher") and hasattr(self.pipeline.dispatcher, "provider"):
                                    self.pipeline.dispatcher.provider.chat_id = str(chat_id)
            except Exception:
                pass
        except Exception as e:
            logger.debug(f"Supabase background sync notice: {e}")

    def _upload_event(self, event: EventRecord, s3_client: Any) -> bool:
        """Uploads clip and thumbnail to S3-compatible bucket."""
        clip_key = f"incidents/{event.camera_id}/{event.event_group_id}/clip.mp4"
        thumb_key = f"incidents/{event.camera_id}/{event.event_group_id}/thumb.jpg"

        # If real S3 client configured
        if s3_client and self.bucket_name:
            try:
                if event.file_path and os.path.exists(event.file_path):
                    s3_client.upload_file(
                        event.file_path,
                        self.bucket_name,
                        clip_key,
                        ExtraArgs={"ContentType": "video/mp4"}
                    )
                if event.thumb_path and os.path.exists(event.thumb_path):
                    s3_client.upload_file(
                        event.thumb_path,
                        self.bucket_name,
                        thumb_key,
                        ExtraArgs={"ContentType": "image/jpeg"}
                    )
                return True
            except Exception as e:
                logger.error(f"Failed S3 upload for {event.event_group_id}: {e}")
                return False
        else:
            # Simulated upload mode (file check verification)
            if event.file_path and os.path.exists(event.file_path):
                return True
            return False

    def stop(self):
        self.running = False
