/**
 * VYZN UI Utility Functions — Formatting, Time Calculations & DOM Security
 */

const PRE_2020_MS = new Date('2020-01-01T00:00:00Z').getTime();

/**
 * Formats a moment timestamp into shopkeeper plain-language time (IST by default).
 * @param {number|string|null} epochMs - Timestamp in milliseconds or ISO string.
 * @param {number} [nowMs=Date.now()] - Current epoch timestamp.
 * @param {string} [timeZone='Asia/Kolkata'] - IANA timezone.
 * @returns {string} Formatted string, e.g. "12 min ago", "Today, 9:34 pm".
 */
export function formatWhen(epochMs, nowMs = Date.now(), timeZone = 'Asia/Kolkata') {
  if (epochMs === null || epochMs === undefined) {
    console.error('[VYZN Time] Encountered null/undefined timestamp');
    return 'Time unknown';
  }

  let ts = typeof epochMs === 'string' ? new Date(epochMs).getTime() : Number(epochMs);

  if (isNaN(ts) || ts <= 0 || ts < PRE_2020_MS) {
    console.error(`[VYZN Time] Invalid or pre-2020 timestamp rejected: ${epochMs}`);
    return 'Time unknown';
  }

  const diffMs = nowMs - ts;
  const diffSec = Math.floor(diffMs / 1000);
  const diffMin = Math.floor(diffSec / 60);

  // Under 1 minute
  if (diffSec < 60 && diffSec >= 0) {
    return 'Just now';
  }

  // Under 1 hour
  if (diffMin < 60 && diffMin >= 0) {
    return `${diffMin} min ago`;
  }

  // Formatting date in target timezone
  const dateObj = new Date(ts);
  const nowDateObj = new Date(nowMs);

  const timeFormatter = new Intl.DateTimeFormat('en-IN', {
    timeZone,
    hour: 'numeric',
    minute: '2-digit',
    hour12: true
  });
  const timeStr = timeFormatter.format(dateObj).toLowerCase();

  const dayFormatter = new Intl.DateTimeFormat('en-IN', {
    timeZone,
    year: 'numeric',
    month: 'numeric',
    day: 'numeric'
  });

  const eventDay = dayFormatter.format(dateObj);
  const todayDay = dayFormatter.format(nowDateObj);

  // Yesterday comparison
  const yesterdayObj = new Date(nowMs - 24 * 3600 * 1000);
  const yesterdayDay = dayFormatter.format(yesterdayObj);

  if (eventDay === todayDay) {
    return `Today, ${timeStr}`;
  }

  if (eventDay === yesterdayDay) {
    return `Yesterday, ${timeStr}`;
  }

  // Older: "Sun 27 Sep, 9:57 pm"
  const fullFormatter = new Intl.DateTimeFormat('en-IN', {
    timeZone,
    weekday: 'short',
    day: 'numeric',
    month: 'short'
  });
  return `${fullFormatter.format(dateObj)}, ${timeStr}`;
}

/**
 * Formats time remaining before 72-hour automated deletion.
 * @param {number} expiresAtMs - Epoch ms when the clip will be deleted.
 * @param {number} [nowMs=Date.now()] - Current epoch timestamp.
 * @returns {string} e.g. "41 h", "5 h 20 min", "12 min".
 */
export function formatLeft(expiresAtMs, nowMs = Date.now()) {
  if (!expiresAtMs || expiresAtMs < PRE_2020_MS) {
    return '';
  }

  const remainingMs = expiresAtMs - nowMs;
  if (remainingMs <= 0) {
    return 'Deleting now';
  }

  const remainingMin = Math.floor(remainingMs / (60 * 1000));
  const remainingHours = Math.floor(remainingMin / 60);
  const leftoverMin = remainingMin % 60;

  if (remainingHours >= 24) {
    return `${remainingHours} h`;
  }

  if (remainingHours > 0) {
    if (leftoverMin === 0) return `${remainingHours} h`;
    return `${remainingHours} h ${leftoverMin} min`;
  }

  return `${remainingMin} min`;
}

/**
 * Escapes dynamic text for safe insertion into innerHTML.
 * @param {string} str - Unsanitized string.
 * @returns {string} HTML-escaped string.
 */
export function escapeHtml(str) {
  if (str === null || str === undefined) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}
