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

    const roleEl = document.getElementById('val-user-role');
    if (roleEl) roleEl.textContent = data.role === 'admin' ? 'Administrator' : 'Shop Owner';

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
