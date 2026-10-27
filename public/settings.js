import { initShell, promptSecurityPin } from './components/shell.js';
import { escapeHtml } from './utils.js';

document.addEventListener('DOMContentLoaded', async () => {
  initShell({ activePage: 'settings' });

  const titleEl = document.getElementById('page-title-text');
  if (titleEl) titleEl.textContent = 'Settings';

  await loadProfile();
  initThemeControls();
  initPhoneControls();
  initSecurityPinControls();
  await initTelegramControls();
  await initBusinessHoursControls();
  await initStorageControls();
  await initCameraPlanControls();
});

function showToast(message, isError = false) {
  const toast = document.getElementById('toast-notification');
  if (!toast) return;
  toast.textContent = message;
  toast.style.borderColor = isError ? '#ef4444' : 'var(--action)';
  toast.style.color = isError ? '#ef4444' : 'var(--text-1)';
  toast.style.display = 'block';
  setTimeout(() => {
    toast.style.display = 'none';
  }, 3500);
}

async function loadProfile() {
  try {
    const res = await fetch('/api/settings/profile', { credentials: 'include' });
    if (!res.ok) throw new Error('Could not load profile');
    const data = await res.json();

    const emailEl = document.getElementById('val-user-email');
    if (emailEl) emailEl.textContent = data.email || 'vyzntechnologies@gmail.com';

    const businessEl = document.getElementById('val-user-business');
    if (businessEl) businessEl.textContent = data.business_name || 'Society / Premises';

    const businessTypeEl = document.getElementById('val-user-business-type');
    if (businessTypeEl) {
      const typeMap = {
        'society': '🏢 Housing Society / CHS',
        'gated_community': '🏡 Gated Community',
        'commercial_complex': '🏬 Commercial Complex',
        'retail': '🛍️ Retail Shop',
        'supermarket': '🛒 Grocery / Supermarket',
        'jewellery': '💎 Jewellery & Gold',
        'godown': '📦 Warehouse / Godown',
        'restaurant': '🍽️ Restaurant / Cafe',
        'other': '🏢 Premises'
      };
      businessTypeEl.textContent = typeMap[data.business_type] || data.business_type || 'Housing Society';
    }

    const roleEl = document.getElementById('val-user-role');
    if (roleEl) {
      if (data.role === 'admin') {
        roleEl.textContent = 'Administrator';
      } else if (data.business_type === 'society' || !data.business_type) {
        roleEl.textContent = 'Society Admin / Premises Manager';
      } else {
        roleEl.textContent = 'Premises / Property Owner';
      }
    }

    const idEl = document.getElementById('val-user-id');
    if (idEl) idEl.textContent = data.id || 'usr_primary';

    const phoneInput = document.getElementById('input-phone-number');
    const phoneBadge = document.getElementById('phone-status-badge');
    if (data.phone_e164) {
      if (phoneInput) phoneInput.value = data.phone_e164;
      if (phoneBadge) {
        phoneBadge.textContent = 'Verified (+91)';
        phoneBadge.className = 'settings-badge success';
      }
    } else {
      if (phoneBadge) {
        phoneBadge.textContent = 'Not Set';
        phoneBadge.className = 'settings-badge info';
      }
    }

    const diskEl = document.getElementById('val-disk-free');
    if (diskEl) diskEl.textContent = `${data.disk_free_pct || 85}% free`;
  } catch (err) {
    console.warn('Failed to load profile details:', err);
  }
}

function initThemeControls() {
  const currentTheme = localStorage.getItem('vyzn_theme') || 'dark';
  const group = document.getElementById('theme-segmented-group');
  if (!group) return;

  const updateActive = (t) => {
    group.querySelectorAll('.theme-toggle-btn').forEach(btn => {
      btn.classList.toggle('is-active', btn.getAttribute('data-theme-val') === t);
    });
  };

  updateActive(currentTheme);

  group.querySelectorAll('.theme-toggle-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const theme = btn.getAttribute('data-theme-val');
      if (theme === 'system') {
        const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
        document.documentElement.setAttribute('data-theme', prefersDark ? 'dark' : 'light');
      } else {
        document.documentElement.setAttribute('data-theme', theme);
      }
      localStorage.setItem('vyzn_theme', theme);
      updateActive(theme);
      showToast(`Theme updated to ${theme}`);
    });
  });
}

function initPhoneControls() {
  const btnSave = document.getElementById('btn-save-phone');
  const input = document.getElementById('input-phone-number');
  const feedback = document.getElementById('phone-feedback');

  if (!btnSave || !input) return;

  btnSave.addEventListener('click', async () => {
    const raw = input.value.trim();
    if (!raw) {
      if (feedback) {
        feedback.textContent = 'Please enter a valid phone number.';
        feedback.style.color = '#ef4444';
        feedback.style.display = 'block';
      }
      return;
    }

    btnSave.disabled = true;
    btnSave.textContent = 'Saving…';
    if (feedback) feedback.style.display = 'none';

    try {
      const res = await fetch('/api/settings/phone', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ phone: raw })
      });

      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Failed to update phone number');

      input.value = data.phone_e164;
      const phoneBadge = document.getElementById('phone-status-badge');
      if (phoneBadge) {
        phoneBadge.textContent = 'Verified (+91)';
        phoneBadge.className = 'settings-badge success';
      }

      if (feedback) {
        feedback.textContent = `Phone number saved: ${data.phone_e164}`;
        feedback.style.color = '#10b981';
        feedback.style.display = 'block';
      }
      showToast('Phone number updated successfully.');
    } catch (err) {
      if (feedback) {
        feedback.textContent = err.message;
        feedback.style.color = '#ef4444';
        feedback.style.display = 'block';
      }
      showToast(err.message, true);
    } finally {
      btnSave.disabled = false;
      btnSave.textContent = 'Save Number';
    }
  });

  const btnPhoneConnectTg = document.getElementById('btn-phone-card-connect-tg');
  if (btnPhoneConnectTg) {
    btnPhoneConnectTg.addEventListener('click', () => {
      const tgCard = document.getElementById('card-telegram-title');
      if (tgCard) tgCard.scrollIntoView({ behavior: 'smooth', block: 'center' });
      const tgBtn = document.getElementById('btn-connect-telegram');
      if (tgBtn && tgBtn.offsetParent !== null) {
        tgBtn.click();
      }
    });
  }
}

function initSecurityPinControls() {
  const btnUpdate = document.getElementById('btn-update-pin');
  const inputCurrent = document.getElementById('input-current-pin');
  const inputNew = document.getElementById('input-new-pin');
  const feedback = document.getElementById('pin-feedback');

  if (!btnUpdate || !inputNew) return;

  btnUpdate.addEventListener('click', async () => {
    const currentPin = inputCurrent ? inputCurrent.value.trim() : '';
    const newPin = inputNew.value.trim();

    if (!newPin || newPin.length < 4 || newPin.length > 8) {
      if (feedback) {
        feedback.textContent = 'New PIN must be 4 to 8 digits (6 digits recommended).';
        feedback.style.color = '#ef4444';
        feedback.style.display = 'block';
      }
      return;
    }

    btnUpdate.disabled = true;
    btnUpdate.textContent = 'Updating…';
    if (feedback) feedback.style.display = 'none';

    try {
      const res = await fetch('/api/settings/security-pin', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          current_pin: currentPin || undefined,
          new_pin: newPin
        })
      });

      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Failed to update Security PIN');

      if (feedback) {
        feedback.textContent = 'Security PIN successfully updated.';
        feedback.style.color = '#10b981';
        feedback.style.display = 'block';
      }
      if (inputCurrent) inputCurrent.value = '';
      inputNew.value = '';
      showToast('Security PIN successfully updated.');
    } catch (err) {
      if (feedback) {
        feedback.textContent = err.message;
        feedback.style.color = '#ef4444';
        feedback.style.display = 'block';
      }
      showToast(err.message, true);
    } finally {
      btnUpdate.disabled = false;
      btnUpdate.textContent = 'Update Security PIN';
    }
  });
}

let tgPollInterval = null;
let currentTgToken = null;

// ==============================================================================
// CONNECT TELEGRAM ACTION (FOR NON-PROGRAMMERS)
// ------------------------------------------------------------------------------
// When you click 'Connect VYZN Telegram':
// 1. We ask the server to create a secure 10-minute linking code.
// 2. We open the official Telegram Bot (@Vyzn_security_bot) in a new browser tab.
// 3. When you tap 'Start' on Telegram, your account is instantly linked!
// 4. All camera alerts and threat photos will automatically go to your Telegram.
// ==============================================================================
async function triggerConnectTelegram(btnElement) {
  if (btnElement) {
    btnElement.disabled = true;
    btnElement.textContent = 'Opening Telegram…';
  }
  const feedback = document.getElementById('tg-feedback');
  if (feedback) feedback.style.display = 'none';

  try {
    const res = await fetch('/api/telegram/link', {
      method: 'POST',
      credentials: 'include'
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Failed to generate connection link');

    currentTgToken = data.token;
    const drawer = document.getElementById('tg-connect-drawer');
    const openLink = document.getElementById('tg-open-deep-link');
    if (openLink) openLink.href = data.deepLink;
    if (drawer) drawer.style.display = 'block';

    // Scroll to drawer so user sees instructions
    const tgCard = document.getElementById('card-telegram-title');
    if (tgCard) tgCard.scrollIntoView({ behavior: 'smooth', block: 'nearest' });

    // Open Telegram Bot in new window/tab
    window.open(data.deepLink, '_blank', 'noopener');
    showToast('Telegram opening… Tap Start in the bot to connect.');

    startTgPolling();
  } catch (err) {
    showToast(err.message, true);
    if (feedback) {
      feedback.textContent = err.message;
      feedback.style.color = '#ef4444';
      feedback.style.display = 'block';
    }
  } finally {
    if (btnElement) {
      btnElement.disabled = false;
      btnElement.textContent = 'Connect VYZN Telegram';
    }
  }
}

async function initTelegramControls() {
  const btnConnect = document.getElementById('btn-connect-telegram');
  const btnDisconnect = document.getElementById('btn-disconnect-telegram');
  const btnToggleAlerts = document.getElementById('btn-toggle-tg-alerts');
  const btnTestAlert = document.getElementById('btn-test-tg-alert');
  const btnSimulate = document.getElementById('tg-test-simulate-btn');
  const feedback = document.getElementById('tg-feedback');

  const btnPhoneConnect = document.getElementById('btn-phone-card-connect-tg');
  const btnSaveToken = document.getElementById('btn-save-tg-bot-token');
  const inputToken = document.getElementById('input-tg-bot-token');
  const tokenFeedback = document.getElementById('tg-token-feedback');

  await refreshTelegramStatus();

  // Load existing Bot Token status if configured
  try {
    const cfgRes = await fetch('/api/telegram/config', { credentials: 'include' });
    if (cfgRes.ok) {
      const cfgData = await cfgRes.json();
      if (cfgData.is_token_set && inputToken) {
        inputToken.placeholder = `Token active (${cfgData.bot_token_masked})`;
      }
    }
  } catch (e) {}

  // Save BotFather token handler
  if (btnSaveToken && inputToken) {
    btnSaveToken.addEventListener('click', async () => {
      const tokVal = inputToken.value.trim();
      if (!tokVal) {
        if (tokenFeedback) {
          tokenFeedback.textContent = 'Please enter a valid bot token from @BotFather.';
          tokenFeedback.style.color = '#ef4444';
          tokenFeedback.style.display = 'block';
        }
        return;
      }
      btnSaveToken.disabled = true;
      btnSaveToken.textContent = 'Saving…';
      try {
        const res = await fetch('/api/telegram/config', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({ bot_token: tokVal, bot_username: 'Vyzn_security_bot' })
        });
        const d = await res.json();
        if (!res.ok) throw new Error(d.detail || 'Failed to save bot token');
        if (tokenFeedback) {
          tokenFeedback.textContent = 'Bot token saved and poller activated successfully!';
          tokenFeedback.style.color = '#10b981';
          tokenFeedback.style.display = 'block';
        }
        inputToken.value = '';
        inputToken.placeholder = 'Token configured and active';
        showToast('Telegram bot token saved and activated.');
        await refreshTelegramStatus();
      } catch (err) {
        if (tokenFeedback) {
          tokenFeedback.textContent = err.message;
          tokenFeedback.style.color = '#ef4444';
          tokenFeedback.style.display = 'block';
        }
        showToast(err.message, true);
      } finally {
        btnSaveToken.disabled = false;
        btnSaveToken.textContent = 'Save Token';
      }
    });
  }

  // Connect from Phone card
  if (btnPhoneConnect) {
    btnPhoneConnect.addEventListener('click', () => {
      triggerConnectTelegram(btnPhoneConnect);
    });
  }

  // Connect from Telegram card
  if (btnConnect) {
    btnConnect.addEventListener('click', () => {
      triggerConnectTelegram(btnConnect);
    });
  }

  if (btnSimulate) {
    btnSimulate.addEventListener('click', async () => {
      if (!currentTgToken) {
        showToast('Click Connect VYZN Telegram first to generate a link.', true);
        return;
      }
      btnSimulate.disabled = true;
      try {
        const res = await fetch('/api/telegram/simulate-link', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({ token: currentTgToken, username: 'demo_user' })
        });
        const d = await res.json();
        if (d.status === 'connected') {
          showToast('Simulated Telegram link confirmed!');
          await refreshTelegramStatus();
        }
      } catch (e) {
        showToast('Simulation failed', true);
      } finally {
        btnSimulate.disabled = false;
      }
    });
  }

  if (btnDisconnect) {
    btnDisconnect.addEventListener('click', async () => {
      if (!confirm('Are you sure you want to disconnect Telegram notifications?')) return;
      btnDisconnect.disabled = true;
      try {
        const res = await fetch('/api/telegram/disconnect', {
          method: 'POST',
          credentials: 'include'
        });
        if (!res.ok) throw new Error('Failed to disconnect');
        showToast('Telegram disconnected successfully.');
        await refreshTelegramStatus();
      } catch (err) {
        showToast(err.message, true);
      } finally {
        btnDisconnect.disabled = false;
      }
    });
  }

  if (btnToggleAlerts) {
    btnToggleAlerts.addEventListener('click', async () => {
      const isCurrentlyEnabled = btnToggleAlerts.getAttribute('data-enabled') === 'true';
      const nextState = !isCurrentlyEnabled;
      btnToggleAlerts.disabled = true;
      try {
        const res = await fetch('/api/telegram/toggle-alerts', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({ enabled: nextState })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Failed to toggle alerts');
        showToast(nextState ? 'Alerts unmuted.' : 'Alerts muted.');
        await refreshTelegramStatus();
      } catch (err) {
        showToast(err.message, true);
      } finally {
        btnToggleAlerts.disabled = false;
      }
    });
  }

  if (btnTestAlert) {
    btnTestAlert.addEventListener('click', async () => {
      btnTestAlert.disabled = true;
      btnTestAlert.textContent = 'Sending…';
      try {
        const res = await fetch('/api/telegram/test', {
          method: 'POST',
          credentials: 'include'
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Failed to deliver test alert');
        showToast(`Test alert delivered in ${data.latencyMs || 800}ms! Check Telegram.`);
      } catch (err) {
        showToast(err.message, true);
      } finally {
        btnTestAlert.disabled = false;
        btnTestAlert.textContent = 'Send Test Alert';
      }
    });
  }
}

function startTgPolling() {
  if (tgPollInterval) clearInterval(tgPollInterval);
  tgPollInterval = setInterval(async () => {
    try {
      const res = await fetch('/api/telegram/status', { credentials: 'include' });
      if (!res.ok) return;
      const data = await res.json();
      if (data.status === 'connected') {
        clearInterval(tgPollInterval);
        tgPollInterval = null;
        showToast('Telegram successfully connected!');
        await refreshTelegramStatus();
      }
    } catch (e) {}
  }, 2500);
}

async function refreshTelegramStatus() {
  try {
    const res = await fetch('/api/telegram/status', { credentials: 'include' });
    if (!res.ok) return;
    const data = await res.json();

    const badge = document.getElementById('tg-status-badge');
    const disconnectedView = document.getElementById('tg-disconnected-view');
    const connectedView = document.getElementById('tg-connected-view');
    const usernameEl = document.getElementById('val-tg-username');
    const toggleBtn = document.getElementById('btn-toggle-tg-alerts');
    const sublabel = document.getElementById('lbl-tg-alert-sublabel');

    if (data.status === 'connected') {
      if (badge) {
        badge.textContent = 'Connected';
        badge.className = 'settings-badge success';
      }
      if (disconnectedView) disconnectedView.style.display = 'none';
      if (connectedView) connectedView.style.display = 'block';
      const drawer = document.getElementById('tg-connect-drawer');
      if (drawer) drawer.style.display = 'none';

      if (usernameEl) {
        const u = data.telegram_username ? `@${data.telegram_username}` : `Chat ID: ${data.telegram_chat_id || 'Active'}`;
        usernameEl.textContent = u;
      }

      const alertsEnabled = data.telegram_alerts_enabled !== false;
      if (toggleBtn) {
        toggleBtn.setAttribute('data-enabled', alertsEnabled ? 'true' : 'false');
        toggleBtn.textContent = alertsEnabled ? 'Mute Alerts' : 'Unmute Alerts';
      }
      if (sublabel) {
        sublabel.textContent = alertsEnabled
          ? 'Active: Real-time photo alerts are delivered to your chat'
          : 'Muted: Threat notifications are temporarily paused';
        sublabel.style.color = alertsEnabled ? 'var(--text-3)' : '#f59e0b';
      }
    } else {
      if (badge) {
        badge.textContent = 'Disconnected';
        badge.className = 'settings-badge info';
      }
      if (disconnectedView) disconnectedView.style.display = 'block';
      if (connectedView) connectedView.style.display = 'none';
    }
  } catch (err) {
    console.warn('Failed to refresh telegram status:', err);
  }
}

// ==============================================================================
// BUSINESS HOURS CONFIGURATION CONTROLS
// ------------------------------------------------------------------------------
// In simple terms: lets users configure and save opening and closing hours.
// ==============================================================================

async function initBusinessHoursControls() {
  const cbEnabled = document.getElementById('cb-bh-enabled');
  const inputStart = document.getElementById('input-bh-start');
  const inputEnd = document.getElementById('input-bh-end');
  const btnSave = document.getElementById('btn-save-bh');
  const badge = document.getElementById('bh-status-badge');
  const feedback = document.getElementById('bh-feedback');

  // Load current business hours from backend
  try {
    const res = await fetch('/api/settings/business-hours', { credentials: 'include' });
    if (res.ok) {
      const data = await res.json();
      if (cbEnabled) cbEnabled.checked = data.enabled !== false;
      if (inputStart && data.start_time) inputStart.value = data.start_time;
      if (inputEnd && data.end_time) inputEnd.value = data.end_time;
      if (badge) {
        badge.textContent = data.enabled ? 'Active' : 'Disabled';
        badge.className = data.enabled ? 'settings-badge success' : 'settings-badge info';
      }
    }
  } catch (err) {
    console.warn('Failed to load business hours:', err);
  }

  // Handle saving new business hours
  if (btnSave) {
    btnSave.onclick = async () => {
      btnSave.disabled = true;
      btnSave.textContent = 'Saving…';
      if (feedback) feedback.style.display = 'none';

      const enabled = cbEnabled ? cbEnabled.checked : true;
      const startTime = inputStart ? inputStart.value : '09:00';
      const endTime = inputEnd ? inputEnd.value : '21:00';

      try {
        const res = await fetch('/api/settings/business-hours', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({
            enabled: enabled,
            start_time: startTime,
            end_time: endTime
          })
        });

        const data = await res.json();
        if (!res.ok) {
          throw new Error(data.detail || 'Failed to update business hours.');
        }

        if (badge) {
          badge.textContent = enabled ? 'Active' : 'Disabled';
          badge.className = enabled ? 'settings-badge success' : 'settings-badge info';
        }

        showToast('Business hours saved successfully!');
        if (feedback) {
          feedback.style.color = '#10b981';
          feedback.textContent = `✓ Business hours updated (${startTime} – ${endTime})`;
          feedback.style.display = 'block';
        }
      } catch (err) {
        showToast(err.message, true);
        if (feedback) {
          feedback.style.color = '#ef4444';
          feedback.textContent = err.message;
          feedback.style.display = 'block';
        }
      } finally {
        btnSave.disabled = false;
        btnSave.textContent = 'Save Business Hours';
      }
    };
  }
}

// ==============================================================================
// STORAGE SPACE FOLDER CONTROLS
// ------------------------------------------------------------------------------
// In simple terms: lets users configure their storage directory, view free space,
// and make sure camera footage & clips are safeguarded from deletion on errors.
// ==============================================================================

let edgeBaseUrl = null;

async function checkEdgeServer() {
  if (edgeBaseUrl !== null) return edgeBaseUrl;
  if (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1' || window.location.port === '8000') {
    edgeBaseUrl = '';
    return edgeBaseUrl;
  }
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 1200);
    const res = await fetch('http://127.0.0.1:8000/api/status', {
      method: 'GET',
      mode: 'cors',
      signal: controller.signal
    });
    clearTimeout(timer);
    if (res.ok) {
      edgeBaseUrl = 'http://127.0.0.1:8000';
      return edgeBaseUrl;
    }
  } catch (e) {}
  edgeBaseUrl = '';
  return edgeBaseUrl;
}

async function initStorageControls() {
  const inputFolder = document.getElementById('input-storage-folder');
  const btnSave = document.getElementById('btn-save-storage');
  const valPath = document.getElementById('val-storage-path');
  const valFree = document.getElementById('val-disk-free');
  const valClips = document.getElementById('val-clips-stored');
  const badge = document.getElementById('storage-status-badge');
  const feedback = document.getElementById('storage-feedback');

  // Load storage details from edge daemon or cloud server
  async function refreshStorageInfo() {
    try {
      const edge = await checkEdgeServer();
      let data = null;
      if (edge) {
        try {
          const edgeRes = await fetch(`${edge}/api/settings/storage`, { mode: 'cors' });
          if (edgeRes.ok) {
            data = await edgeRes.json();
          }
        } catch (e) {
          console.warn('Edge storage info fetch failed:', e);
        }
      }
      if (!data) {
        const res = await fetch('/api/settings/storage', { credentials: 'include' });
        if (res.ok) {
          data = await res.json();
        }
      }
      if (data) {
        if (inputFolder) {
          inputFolder.value = data.storage_dir || '';
        }
        if (valPath) {
          valPath.textContent = data.storage_dir || 'Default: ./data/clips';
        }
        if (valFree) {
          const used = data.disk_used_gb || 0;
          const total = data.disk_total_gb || 0;
          const freeGb = (total >= used && total > 0) ? (total - used).toFixed(1) : 0;
          const freePct = data.disk_free_pct !== undefined ? data.disk_free_pct : (total > 0 ? Math.round((freeGb / total) * 100) : 0);
          valFree.textContent = total > 0
            ? `${freePct}% free (${freeGb} GB free of ${total.toFixed(1)} GB)`
            : 'Available';
        }
        if (valClips) {
          valClips.textContent = `${data.clips_count || 0} clips (Safe & Preserved)`;
        }
        if (badge) {
          const isWritable = data.is_writable !== false;
          badge.textContent = isWritable ? 'Active & Writable' : 'Read-Only Warning';
          badge.className = isWritable ? 'settings-badge success' : 'settings-badge info';
        }
      }
    } catch (err) {
      console.warn('Failed to load storage info:', err);
    }
  }

  await refreshStorageInfo();

  if (btnSave) {
    btnSave.onclick = async () => {
      const dirVal = inputFolder ? inputFolder.value.trim() : '';
      if (!dirVal) {
        if (feedback) {
          feedback.style.color = '#ef4444';
          feedback.textContent = 'Please specify a valid folder path.';
          feedback.style.display = 'block';
        }
        return;
      }

      btnSave.disabled = true;
      btnSave.textContent = 'Verifying & Saving…';
      if (feedback) feedback.style.display = 'none';

      try {
        const edge = await checkEdgeServer();
        if (edge) {
          try {
            await fetch(`${edge}/api/settings/storage`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              mode: 'cors',
              body: JSON.stringify({ storage_dir: dirVal })
            });
          } catch (e) {
            console.warn('Edge storage save failed:', e);
          }
        }

        const res = await fetch('/api/settings/storage', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({ storage_dir: dirVal })
        });
        const data = await res.json();
        if (!res.ok) {
          throw new Error(data.detail || 'Failed to update storage folder.');
        }

        showToast('Storage folder updated successfully!');
        if (feedback) {
          feedback.style.color = '#10b981';
          feedback.textContent = '✓ Storage space folder saved and active. All footage will be kept safe here.';
          feedback.style.display = 'block';
        }
        await refreshStorageInfo();
      } catch (err) {
        showToast(err.message, true);
        if (feedback) {
          feedback.style.color = '#ef4444';
          feedback.textContent = err.message;
          feedback.style.display = 'block';
        }
      } finally {
        btnSave.disabled = false;
        btnSave.textContent = 'Save Storage Folder';
      }
    };
  }

  // Quick preset chips listeners
  document.querySelectorAll('.btn-preset-path').forEach(btn => {
    btn.onclick = () => {
      const p = btn.getAttribute('data-path');
      if (p && inputFolder) {
        inputFolder.value = p;
        showToast(`Selected preset: ${p}`);
        if (btnSave) btnSave.click();
      }
    };
  });

  // Opens native Windows file explorer folder selection dialog via local edge server or prompts for path
  const btnBrowse = document.getElementById('btn-browse-folder');
  const inputDirPicker = document.getElementById('input-folder-picker');


  if (btnBrowse) {
    btnBrowse.onclick = async () => {
      btnBrowse.disabled = true;
      btnBrowse.textContent = '📁 Opening Explorer…';

      try {
        // Strategy 1: Local Edge Node Native Windows Explorer Dialog
        const isLocalHost = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1' || window.location.port === '8000';
        if (isLocalHost) {
          try {
            const res = await fetch('/api/settings/browse-folder', { method: 'POST' });
            const data = await res.json();
            if (data.ok && data.selected_path) {
              if (inputFolder) inputFolder.value = data.selected_path;
              showToast(`Selected folder: ${data.selected_path}`);
              if (btnSave) btnSave.click();
              return;
            } else if (data.cancelled) {
              return;
            }
          } catch (e) {
            console.warn('Local browse-folder error:', e);
          }
        }

        // Strategy 2: File System Access API (Native Windows Explorer Directory Dialog)
        if (typeof window.showDirectoryPicker === 'function') {
          try {
            const dirHandle = await window.showDirectoryPicker({ id: 'vyzn_storage', mode: 'readwrite' });
            if (dirHandle && dirHandle.name) {
              const currentDir = inputFolder ? inputFolder.value.trim() : '';
              let selectedPath = `C:\\${dirHandle.name}`;
              if (currentDir && (currentDir.includes('\\') || currentDir.includes('/'))) {
                const sep = currentDir.includes('\\') ? '\\' : '/';
                const parts = currentDir.split(sep);
                parts[parts.length - 1] = dirHandle.name;
                selectedPath = parts.join(sep);
              }
              if (inputFolder) inputFolder.value = selectedPath;
              showToast(`Selected storage folder: ${selectedPath}`);
              if (btnSave) btnSave.click();
              return;
            }
          } catch (err) {
            if (err.name === 'AbortError') {
              // User closed or cancelled the picker
              return;
            }
            console.warn('showDirectoryPicker notice:', err);
          }
        }

        // Strategy 3: Native HTML input webkitdirectory picker
        if (inputDirPicker) {
          inputDirPicker.click();
          return;
        }

        // Strategy 4: Fallback prompt dialog
        const cur = inputFolder ? inputFolder.value.trim() : 'C:\\Vyzn testing data';
        const entered = window.prompt(
          'Select Storage Folder:\nEnter directory path for clips and continuous footage:',
          cur || 'C:\\Vyzn testing data'
        );
        if (entered && entered.trim()) {
          const cleaned = entered.trim();
          if (inputFolder) inputFolder.value = cleaned;
          showToast(`Storage path set to: ${cleaned}`);
          if (btnSave) btnSave.click();
        }
      } catch (err) {
        console.error('Folder picker error:', err);
      } finally {
        btnBrowse.disabled = false;
        btnBrowse.textContent = '📁 Choose Folder';
      }
    };
  }

  if (inputDirPicker) {
    inputDirPicker.onchange = (e) => {
      if (e.target.files && e.target.files.length > 0) {
        const file = e.target.files[0];
        const relPath = file.webkitRelativePath || '';
        const folderName = relPath.split('/')[0] || relPath.split('\\')[0] || '';
        if (folderName) {
          const currentDir = inputFolder.value.trim() || 'C:\\Vyzn testing data';
          const sep = currentDir.includes('\\') ? '\\' : '/';
          const baseParent = currentDir.includes(sep) ? currentDir.substring(0, currentDir.lastIndexOf(sep)) : 'C:';
          inputFolder.value = `${baseParent}${sep}${folderName}`;
          showToast(`Selected folder: ${folderName}`);
          if (btnSave) btnSave.click();
        }
      }
    };
  }

  // Purges all past clips cleanly with Security PIN verification
  const btnPurgeAll = document.getElementById('btn-purge-all-clips');
  if (btnPurgeAll) {
    btnPurgeAll.onclick = async () => {
      const pin = await promptSecurityPin({
        title: 'Delete All Previous Clips',
        description: 'Permanently purge all historical clips, recordings, and media from disk and database. This cannot be undone.',
        confirmText: 'Delete All Clips',
        isDanger: true
      });
      if (!pin) return;

      btnPurgeAll.disabled = true;
      btnPurgeAll.textContent = 'Purging clips…';
      try {
        const edge = await checkEdgeServer();
        if (edge) {
          try {
            await fetch(`${edge}/api/clips/purge-all`, {
              method: 'POST',
              headers: { 'X-Security-Pin': pin },
              mode: 'cors'
            });
          } catch (e) {
            console.warn('Edge purge failed:', e);
          }
        }
        const res = await fetch('/api/clips/purge-all', {
          method: 'POST',
          headers: { 'X-Security-Pin': pin },
          credentials: 'include'
        });
        const data = await res.json().catch(() => ({}));
        if (res.ok && data.ok) {
          showToast(data.message || 'All previous clips purged successfully.');
          await refreshStorageInfo();
        } else {
          showToast(data.detail || 'Failed to purge clips. Check Security PIN.', true);
        }
      } catch (err) {
        showToast('Error while purging clips.', true);
      } finally {
        btnPurgeAll.disabled = false;
        btnPurgeAll.textContent = '🗑️ Delete All Previous Clips';
      }
    };
  }
}

// ==============================================================================
// Camera Plan & Quota Management Controls
// ==============================================================================

async function initCameraPlanControls() {
  let planQuota = {
    purchased: 0,
    used: 0,
    available: 0,
    price_per_camera_paise: 50000,
    max_per_order: 20
  };
  let selectedQty = 1;
  let activeOrder = null;
  let timerInterval = null;
  let pollInterval = null;

  const modal = document.getElementById('modal-camera-plan');
  const btnOpenModal = document.getElementById('btn-open-plan-modal');
  const btnCloseModal = document.getElementById('btn-close-plan-modal');
  const step1 = document.getElementById('plan-step-1');
  const step2 = document.getElementById('plan-step-2');
  const step3 = document.getElementById('plan-step-3');

  // Load and display Quota
  async function loadQuota() {
    try {
      const res = await fetch('/billing/quota', { credentials: 'include' });
      if (!res.ok) return;
      const data = await res.json();
      planQuota = data;

      const valPurchased = document.getElementById('val-plan-purchased');
      const valUsed = document.getElementById('val-plan-used');
      const valAvailable = document.getElementById('val-plan-available');
      const valPrice = document.getElementById('val-plan-price');
      const badge = document.getElementById('plan-quota-badge');

      if (valPurchased) valPurchased.textContent = data.purchased;
      if (valUsed) valUsed.textContent = data.used;
      if (valAvailable) valAvailable.textContent = data.available;

      const unitPriceRs = (data.price_per_camera_paise / 100).toFixed(0);
      if (valPrice) valPrice.textContent = `₹${unitPriceRs}`;

      if (badge) {
        if (data.available > 0) {
          badge.textContent = `${data.available} Slots Free`;
          badge.className = 'settings-badge success';
        } else {
          badge.textContent = 'Quota Full';
          badge.className = 'settings-badge info';
        }
      }

      updateStepperDisplay();
    } catch (e) {
      console.warn('Could not load camera quota:', e);
    }
  }

  // Load and render Order History
  async function loadOrderHistory() {
    const tbody = document.getElementById('tbody-quota-orders');
    if (!tbody) return;

    try {
      const res = await fetch('/billing/quota-orders', { credentials: 'include' });
      if (!res.ok) {
        tbody.innerHTML = '<tr><td colspan="6" style="padding: 14px 10px; text-align: center; color: var(--text-3);">Could not load orders.</td></tr>';
        return;
      }
      const orders = await res.json();
      if (!orders || orders.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" style="padding: 16px 10px; text-align: center; color: var(--text-3);">No camera quota orders yet.</td></tr>';
        return;
      }

      const statusMap = {
        'paid': { label: 'Verified & Credited', cls: 'settings-badge success' },
        'submitted': { label: 'Verifying', cls: 'settings-badge info' },
        'awaiting_payment': { label: 'Awaiting Payment', cls: 'settings-badge info' },
        'rejected': { label: 'Declined', cls: 'settings-badge' },
        'expired': { label: 'Expired', cls: 'settings-badge' }
      };

      tbody.innerHTML = orders.map(ord => {
        const st = statusMap[ord.status] || { label: ord.status, cls: 'settings-badge' };
        const amountRs = (ord.amount_paise / 100).toFixed(2);
        const dateStr = ord.created_at ? new Date(ord.created_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '—';
        const utrDisplay = ord.utr ? `<code style="font-size: 11px;">${escapeHtml(ord.utr)}</code>` : '<span style="color: var(--text-3);">—</span>';

        return `
          <tr style="border-bottom: 1px solid rgba(255,255,255,0.04); cursor: pointer;" data-order-id="${ord.id}" data-order-status="${ord.status}">
            <td style="padding: 10px; font-weight: 600; font-family: monospace; color: #ffffff;">${escapeHtml(ord.order_code)}</td>
            <td style="padding: 10px; color: var(--text-2);">${dateStr}</td>
            <td style="padding: 10px; color: var(--text-1);">${ord.quantity} camera${ord.quantity > 1 ? 's' : ''}</td>
            <td style="padding: 10px; font-weight: 600; color: #ffffff;">₹${amountRs}</td>
            <td style="padding: 10px;"><span class="${st.cls}">${st.label}</span></td>
            <td style="padding: 10px;">${utrDisplay}</td>
          </tr>
        `;
      }).join('');

      // Add click handler to resume open orders
      tbody.querySelectorAll('tr[data-order-id]').forEach(row => {
        row.addEventListener('click', async () => {
          const ordId = row.getAttribute('data-order-id');
          const ordStatus = row.getAttribute('data-order-status');
          if (ordStatus === 'awaiting_payment' || ordStatus === 'submitted') {
            await resumeOrder(ordId);
          }
        });
      });
    } catch (e) {
      tbody.innerHTML = '<tr><td colspan="6" style="padding: 14px 10px; text-align: center; color: var(--text-3);">Error loading orders.</td></tr>';
    }
  }

  function updateStepperDisplay() {
    const qtyEl = document.getElementById('display-plan-qty');
    const totalEl = document.getElementById('display-plan-total');
    const rateEl = document.getElementById('display-plan-rate');

    if (qtyEl) qtyEl.textContent = selectedQty;

    const rate = planQuota.price_per_camera_paise / 100;
    const total = selectedQty * rate;

    if (totalEl) totalEl.textContent = `₹${total.toFixed(2)}`;
    if (rateEl) rateEl.textContent = `(₹${rate.toFixed(0)} per camera)`;
  }

  // Stepper buttons
  const btnMinus = document.getElementById('btn-qty-minus');
  const btnPlus = document.getElementById('btn-qty-plus');

  if (btnMinus) {
    btnMinus.addEventListener('click', () => {
      if (selectedQty > 1) {
        selectedQty--;
        updateStepperDisplay();
      }
    });
  }

  if (btnPlus) {
    btnPlus.addEventListener('click', () => {
      const maxAllowed = planQuota.max_per_order || 20;
      if (selectedQty < maxAllowed) {
        selectedQty++;
        updateStepperDisplay();
      }
    });
  }

  function showModal() {
    if (modal) modal.style.display = 'flex';
  }

  function hideModal() {
    if (modal) modal.style.display = 'none';
    if (timerInterval) { clearInterval(timerInterval); timerInterval = null; }
    if (pollInterval) { clearInterval(pollInterval); pollInterval = null; }
    activeOrder = null;
    loadQuota();
    loadOrderHistory();
  }

  function showStep(stepIndex) {
    if (step1) step1.style.display = stepIndex === 1 ? 'block' : 'none';
    if (step2) step2.style.display = stepIndex === 2 ? 'block' : 'none';
    if (step3) step3.style.display = stepIndex === 3 ? 'block' : 'none';

    const titleEl = document.getElementById('modal-plan-title');
    if (titleEl) {
      if (stepIndex === 1) titleEl.textContent = 'Add Camera Plan';
      if (stepIndex === 2) titleEl.textContent = 'Pay via UPI QR';
      if (stepIndex === 3) titleEl.textContent = 'Order Status';
    }
  }

  if (btnOpenModal) {
    btnOpenModal.addEventListener('click', () => {
      selectedQty = 1;
      updateStepperDisplay();
      const errEl = document.getElementById('plan-step1-error');
      if (errEl) errEl.style.display = 'none';
      showStep(1);
      showModal();
    });
  }

  if (btnCloseModal) {
    btnCloseModal.addEventListener('click', hideModal);
  }

  // Step 1 -> Proceed: create quota order
  const btnProceed = document.getElementById('btn-proceed-order');
  if (btnProceed) {
    btnProceed.addEventListener('click', async () => {
      const errEl = document.getElementById('plan-step1-error');
      if (errEl) errEl.style.display = 'none';

      btnProceed.disabled = true;
      btnProceed.textContent = 'Creating order…';

      try {
        const res = await fetch('/billing/quota-orders', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({ quantity: selectedQty })
        });

        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          if (res.status === 409) {
            // Already has open order
            errEl.textContent = data.detail || 'An open order already exists. Resuming open order…';
            errEl.style.display = 'block';
            await loadOrderHistory();
            return;
          }
          throw new Error(data.detail || 'Failed to create order.');
        }

        activeOrder = data;
        renderStep2Payment(data);
        showStep(2);
      } catch (err) {
        if (errEl) {
          errEl.textContent = err.message;
          errEl.style.display = 'block';
        }
      } finally {
        btnProceed.disabled = false;
        btnProceed.textContent = 'Proceed to Payment →';
      }
    });
  }

  // Render Step 2 Payment View
  function renderStep2Payment(ord) {
    const codeEl = document.getElementById('step2-order-code');
    const amountEl = document.getElementById('step2-amount');
    const qtyDescEl = document.getElementById('step2-qty-desc');
    const qrImg = document.getElementById('step2-qr-img');
    const upiLink = document.getElementById('step2-upi-link');
    const utrInput = document.getElementById('step2-input-utr');
    const utrErr = document.getElementById('step2-utr-error');

    if (codeEl) codeEl.textContent = ord.order_code;
    if (amountEl) amountEl.textContent = `₹${(ord.amount_paise / 100).toFixed(2)}`;
    if (qtyDescEl) qtyDescEl.textContent = `for ${ord.quantity} camera slot${ord.quantity > 1 ? 's' : ''}`;
    if (qrImg && ord.qr) qrImg.src = ord.qr;
    if (upiLink && ord.upi_link) upiLink.href = ord.upi_link;
    if (utrInput) utrInput.value = '';
    if (utrErr) utrErr.style.display = 'none';

    // Start countdown timer
    startExpiryTimer(ord.expires_at);
  }

  function startExpiryTimer(expiresAtIso) {
    if (timerInterval) clearInterval(timerInterval);
    const timerEl = document.getElementById('step2-timer');
    if (!timerEl) return;

    const targetTime = expiresAtIso ? new Date(expiresAtIso).getTime() : Date.now() + 30 * 60 * 1000;

    const updateTimer = () => {
      const remainingSec = Math.max(0, Math.floor((targetTime - Date.now()) / 1000));
      const mins = Math.floor(remainingSec / 60);
      const secs = remainingSec % 60;
      timerEl.textContent = `⏱️ ${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;

      if (remainingSec <= 0) {
        clearInterval(timerInterval);
        timerInterval = null;
        timerEl.textContent = '⏱️ Expired';
        showToast('Order has expired. Please create a new order.', true);
      }
    };

    updateTimer();
    timerInterval = setInterval(updateTimer, 1000);
  }

  // Step 2 -> Submit UTR
  const btnSubmitUtr = document.getElementById('btn-submit-utr');
  if (btnSubmitUtr) {
    btnSubmitUtr.addEventListener('click', async () => {
      const utrInput = document.getElementById('step2-input-utr');
      const utrErr = document.getElementById('step2-utr-error');
      const utrVal = utrInput ? utrInput.value.trim() : '';

      if (!/^\d{12}$/.test(utrVal)) {
        if (utrErr) {
          utrErr.textContent = 'Please enter a valid 12-digit UPI reference (UTR) number.';
          utrErr.style.display = 'block';
        }
        return;
      }

      if (utrErr) utrErr.style.display = 'none';
      btnSubmitUtr.disabled = true;
      btnSubmitUtr.textContent = 'Submitting UTR…';

      try {
        const res = await fetch(`/billing/quota-orders/${activeOrder.id}/submit-utr`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({ utr: utrVal })
        });

        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          throw new Error(data.detail || 'Failed to submit UTR.');
        }

        activeOrder = data;
        renderStep3Tracker('submitted', data);
        showStep(3);
        startPollingOrderStatus(activeOrder.id);
      } catch (err) {
        if (utrErr) {
          utrErr.textContent = err.message;
          utrErr.style.display = 'block';
        }
      } finally {
        btnSubmitUtr.disabled = false;
        btnSubmitUtr.textContent = 'Submit UTR for Verification';
      }
    });
  }

  // Step 3 Live Status Tracker
  function renderStep3Tracker(status, orderData) {
    const iconEl = document.getElementById('step3-icon');
    const titleEl = document.getElementById('step3-title');
    const msgEl = document.getElementById('step3-msg');
    const actionWrap = document.getElementById('step3-action-wrap');
    const badgeEl = document.getElementById('step3-polling-badge');

    if (status === 'submitted') {
      if (iconEl) iconEl.textContent = '⏳';
      if (titleEl) titleEl.textContent = 'Verifying Payment';
      if (msgEl) msgEl.textContent = 'UTR submitted. Payments are verified manually. Once approved, your quota will be activated automatically.';
      if (badgeEl) badgeEl.style.display = 'inline-flex';
      if (actionWrap) {
        actionWrap.innerHTML = `
          <button type="button" class="btn btn-secondary" id="btn-step3-close" style="width: 100%;">
            Close & Wait for Approval
          </button>
        `;
        document.getElementById('btn-step3-close')?.addEventListener('click', hideModal);
      }
    } else if (status === 'paid') {
      if (iconEl) iconEl.textContent = '✅';
      if (titleEl) titleEl.textContent = 'Payment Verified!';
      const qty = orderData.quantity || activeOrder?.quantity || 1;
      if (msgEl) msgEl.innerHTML = `<strong style="color: #10b981;">${qty}</strong> camera slot${qty > 1 ? 's' : ''} added to your quota!`;
      if (badgeEl) badgeEl.style.display = 'none';
      if (actionWrap) {
        actionWrap.innerHTML = `
          <a href="/add-camera" class="btn btn-primary" style="display: block; width: 100%; text-align: center; text-decoration: none; padding: 12px; font-weight: 600;">
            Add Camera Now →
          </a>
        `;
      }
    } else if (status === 'rejected') {
      if (iconEl) iconEl.textContent = '❌';
      if (titleEl) titleEl.textContent = 'Payment Declined';
      const reason = orderData.reject_reason || 'Verification was declined by administrator.';
      if (msgEl) msgEl.textContent = `Reason: ${reason}`;
      if (badgeEl) badgeEl.style.display = 'none';
      if (actionWrap) {
        actionWrap.innerHTML = `
          <button type="button" class="btn btn-primary" id="btn-step3-retry" style="width: 100%; padding: 12px;">
            Try Again
          </button>
        `;
        document.getElementById('btn-step3-retry')?.addEventListener('click', () => {
          showStep(1);
        });
      }
    } else if (status === 'expired') {
      if (iconEl) iconEl.textContent = '⚠️';
      if (titleEl) titleEl.textContent = 'Order Expired';
      if (msgEl) msgEl.textContent = 'This payment request expired before verification. Please initiate a new order.';
      if (badgeEl) badgeEl.style.display = 'none';
      if (actionWrap) {
        actionWrap.innerHTML = `
          <button type="button" class="btn btn-primary" id="btn-step3-restart" style="width: 100%; padding: 12px;">
            Start New Order
          </button>
        `;
        document.getElementById('btn-step3-restart')?.addEventListener('click', () => {
          showStep(1);
        });
      }
    }
  }

  function startPollingOrderStatus(orderId) {
    if (pollInterval) clearInterval(pollInterval);

    pollInterval = setInterval(async () => {
      try {
        const res = await fetch(`/billing/quota-orders/${orderId}`, { credentials: 'include' });
        if (!res.ok) return;
        const ord = await res.json();
        activeOrder = ord;

        if (ord.status !== 'submitted') {
          clearInterval(pollInterval);
          pollInterval = null;
          renderStep3Tracker(ord.status, ord);
          loadQuota();
          loadOrderHistory();
        }
      } catch (e) {}
    }, 4000);
  }

  async function resumeOrder(orderId) {
    try {
      const res = await fetch(`/billing/quota-orders/${orderId}`, { credentials: 'include' });
      if (!res.ok) return;
      const ord = await res.json();
      activeOrder = ord;
      showModal();

      if (ord.status === 'awaiting_payment') {
        renderStep2Payment(ord);
        showStep(2);
      } else if (ord.status === 'submitted') {
        renderStep3Tracker('submitted', ord);
        showStep(3);
        startPollingOrderStatus(ord.id);
      }
    } catch (e) {}
  }

  // Initial load
  await loadQuota();
  await loadOrderHistory();
}




