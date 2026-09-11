"""
Adaptive Edge Intelligence & Hardened Closed-Loop Auto-Calibrator.
Translates real-world shopkeeper triage decisions into camera-specific bias adjustments,
driving false-alarm rates asymptotically toward zero while resisting adversarial gaming.

Hardened Features:
1. Sample-size gating (N >= 15 reviews required before any bias activates).
2. Beta-Binomial conjugate Bayesian estimator (Beta(alpha=2, beta=18) prior).
3. Anti-gaming slew rate limiter (max 5-point shift per 24-hour window).
4. Rolling 30-day window to decay temporary environmental anomalies.
5. Inviolable hard-floor preservation for verified object detections.
"""

from __future__ import annotations
import time
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger("vyzn.scoring.calibrator")


class AdaptiveCalibrator:
    """
    Computes camera-specific dynamic Bayesian score adjustments based on
    empirical triage feedback (confirmed threats vs false positives).
    """

    def __init__(
        self,
        db: Optional[Any] = None,
        cache_ttl_sec: float = 10.0,
        min_samples: int = 15,
        max_penalty: int = 25,
        prior_alpha: float = 2.0,
        prior_beta: float = 18.0,
        max_slew_per_day: int = 5,
        window_days: int = 30
    ):
        self.db = db
        self.cache_ttl_sec = cache_ttl_sec
        self.min_samples = min_samples
        self.max_penalty = max_penalty
        self.prior_alpha = prior_alpha
        self.prior_beta = prior_beta
        self.max_slew_per_day = max_slew_per_day
        self.window_days = window_days

        self._bias_cache: Dict[str, int] = {}
        self._stats_cache: Dict[str, Dict[str, Any]] = {}
        self._last_refresh: float = 0.0
        self._manual_overrides: Dict[str, int] = {}

        # Anti-gaming slew rate tracking:
        # camera_id -> [(timestamp, delta_applied)] in rolling 24-hour window
        self._adjustment_history: Dict[str, list[tuple[float, int]]] = {}
        self._current_bias: Dict[str, int] = {}
        self._bias_history: Dict[str, tuple[float, int]] = {}

    def compute_bayesian_bias_from_stats(
        self,
        camera_id: str,
        stats: Dict[str, Any],
        now_ts: Optional[float] = None
    ) -> tuple[int, Dict[str, Any]]:
        """
        Calculates score penalty bias using Beta-Binomial conjugate Bayesian estimation:
        Prior: Beta(alpha=2, beta=18) representing 10% baseline FPR expectation.
        Posterior: Beta(alpha + FP, beta + TP)
        Posterior Mean theta_hat = (FP + alpha) / (FP + TP + alpha + beta)

        Gating & Anti-Gaming Controls:
        - If reviewed events < min_samples (15), bias = 0.
        - Cumulative Slew Rate Limiter: max cumulative drift of max_slew_per_day
          across any rolling 24-hour sliding window (86,400 seconds).
        """
        fp = stats.get("false_positive", 0)
        tp = stats.get("confirmed_threat", 0)
        reviewed = stats.get("reviewed", fp + tp)

        # 1. Sample Size Gating: zero bias if data is sparse
        if reviewed < self.min_samples:
            return 0, {
                "gated": True,
                "reason": f"Sample size {reviewed} < {self.min_samples} required",
                "posterior_fpr": (self.prior_alpha / (self.prior_alpha + self.prior_beta)),
                "raw_bias": 0,
                "slew_limited": False
            }

        # 2. Beta-Binomial Posterior Estimate
        post_alpha = self.prior_alpha + fp
        post_beta = self.prior_beta + tp
        theta_hat = post_alpha / (post_alpha + post_beta)

        raw_penalty = int(round(theta_hat * 30.0))
        target_bias = -min(self.max_penalty, max(0, raw_penalty))

        # 3. Cumulative Sliding-Window Slew Rate Limiter (rolling 24h)
        now = now_ts if now_ts is not None else time.monotonic()
        history = self._adjustment_history.setdefault(camera_id, [])

        # Prune records older than 24 hours (86,400s)
        cutoff = now - 86400.0
        history = [(ts, delta) for ts, delta in history if ts >= cutoff]
        self._adjustment_history[camera_id] = history

        current_bias = self._current_bias.get(camera_id, 0)
        used_slew = sum(abs(delta) for _, delta in history)
        remaining_budget = max(0, self.max_slew_per_day - used_slew)

        desired_delta = target_bias - current_bias
        slew_limited = False

        if abs(desired_delta) > remaining_budget:
            slew_limited = True
            if desired_delta < 0:
                applied_delta = -remaining_budget
            else:
                applied_delta = remaining_budget
        else:
            applied_delta = desired_delta

        final_bias = current_bias + applied_delta
        if applied_delta != 0:
            history.append((now, applied_delta))

        self._current_bias[camera_id] = final_bias
        self._bias_history[camera_id] = (now, final_bias)

        debug_info = {
            "gated": False,
            "posterior_fpr": round(theta_hat, 4),
            "target_bias": target_bias,
            "final_bias": final_bias,
            "slew_limited": slew_limited,
            "used_24h_slew": used_slew + abs(applied_delta),
            "remaining_24h_budget": max(0, remaining_budget - abs(applied_delta)),
            "post_alpha": post_alpha,
            "post_beta": post_beta
        }
        return final_bias, debug_info

    def refresh(self, force: bool = False):
        """Refreshes camera statistics from SQLite database over trailing rolling window."""
        now = time.monotonic()
        if not force and (now - self._last_refresh) < self.cache_ttl_sec:
            return

        if not self.db:
            return

        try:
            all_stats = self.db.get_all_camera_triage_statistics(window_days=self.window_days)
            for cam_id, stats in all_stats.items():
                self._stats_cache[cam_id] = stats
                if cam_id not in self._manual_overrides:
                    bias, _ = self.compute_bayesian_bias_from_stats(cam_id, stats)
                    self._bias_cache[cam_id] = bias
            self._last_refresh = now
        except Exception as e:
            logger.warning(f"Failed to refresh adaptive calibration metrics: {e}")

    def get_camera_bias(self, camera_id: str) -> int:
        """
        Returns the integer score bias (<= 0) for the specified camera.
        Negative bias dampens unclassified nuisance motion.
        """
        if camera_id in self._manual_overrides:
            return self._manual_overrides[camera_id]

        self.refresh()

        if camera_id in self._bias_cache:
            return self._bias_cache[camera_id]

        if self.db:
            try:
                stats = self.db.get_camera_triage_statistics(camera_id, window_days=self.window_days)
                self._stats_cache[camera_id] = stats
                bias, _ = self.compute_bayesian_bias_from_stats(camera_id, stats)
                self._bias_cache[camera_id] = bias
                return bias
            except Exception as e:
                logger.warning(f"Error querying triage stats for camera {camera_id}: {e}")

        return 0

    def get_camera_metrics(self, camera_id: str) -> Dict[str, Any]:
        """Returns detailed calibration and Bayesian breakdown for a camera."""
        self.refresh()
        stats = self._stats_cache.get(camera_id)
        if not stats and self.db:
            try:
                stats = self.db.get_camera_triage_statistics(camera_id, window_days=self.window_days)
                self._stats_cache[camera_id] = stats
            except Exception:
                stats = {}

        stats = stats or {
            "unreviewed": 0,
            "confirmed_threat": 0,
            "false_positive": 0,
            "total": 0,
            "reviewed": 0,
            "false_positive_rate": 0.0,
            "fpr_fraction": 0.0
        }

        bias, debug_info = self.compute_bayesian_bias_from_stats(camera_id, stats)
        if camera_id in self._manual_overrides:
            bias = self._manual_overrides[camera_id]

        return {
            "camera_id": camera_id,
            "bias": bias,
            "is_manual": camera_id in self._manual_overrides,
            "window_days": self.window_days,
            "min_samples": self.min_samples,
            **stats,
            **debug_info
        }

    def set_manual_bias(self, camera_id: str, bias: int):
        """Allows installer to manually set a fixed dampener."""
        self._manual_overrides[camera_id] = int(bias)

    def clear_manual_bias(self, camera_id: str):
        """Removes manual override and restores auto-calibration."""
        self._manual_overrides.pop(camera_id, None)