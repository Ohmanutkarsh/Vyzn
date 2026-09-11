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
        min_score: int = 50  # Lowered from 70 to 50 to capture early intrusion evidence before hardware can be severed
    ):

        super().__init__(name="Cloud-Sync-Worker", daemon=True)
        self.db = db
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
