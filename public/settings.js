import { initShell } from './components/shell.js';
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

async function initTelegramControls() {
  const btnConnect = document.getElementById('btn-connect-telegram');
  const btnDisconnect = document.getElementById('btn-disconnect-telegram');
  const btnToggleAlerts = document.getElementById('btn-toggle-tg-alerts');
  const btnTestAlert = document.getElementById('btn-test-tg-alert');
  const btnSimulate = document.getElementById('tg-test-simulate-btn');
  const feedback = document.getElementById('tg-feedback');

  await refreshTelegramStatus();

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

  if (btnConnect) {
    btnConnect.addEventListener('click', async () => {
      btnConnect.disabled = true;
      btnConnect.textContent = 'Generating Link…';
      if (feedback) feedback.style.display = 'none';

      try {
        const res = await fetch('/api/telegram/link', {
          method: 'POST',
          credentials: 'include'
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Failed to generate link');

        currentTgToken = data.token;
        const drawer = document.getElementById('tg-connect-drawer');
        const openLink = document.getElementById('tg-open-deep-link');
        if (openLink) openLink.href = data.deepLink;
        if (drawer) drawer.style.display = 'block';

        // Automatically open the deep link in a new tab for seamless UX
        window.open(data.deepLink, '_blank', 'noopener');

        startTgPolling();
      } catch (err) {
        showToast(err.message, true);
        if (feedback) {
          feedback.textContent = err.message;
          feedback.style.color = '#ef4444';
          feedback.style.display = 'block';
        }
      } finally {
        btnConnect.disabled = false;
        btnConnect.textContent = 'Connect VYZN Telegram';
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

