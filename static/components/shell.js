/**
 * VYZN Unified App Shell & Navigation Component (Section 6.0)
 * Renders desktop sidebar / mobile bottom bar, header status pill with priority 1-5,
 * and user account menu with theme switcher.
 */

import { escapeHtml } from '../utils.js';

export function initShell({ activePage = 'overview' } = {}) {
  // Apply saved theme
  const savedTheme = localStorage.getItem('vyzn_theme') || 'dark';
  document.documentElement.setAttribute('data-theme', savedTheme);

  // Render shell elements
  renderSidebar(activePage);
  renderHeader();
  renderBottomNav(activePage);
  attachShellEvents();

  // Initial poll for header status pill
  pollShellStatus();
  setInterval(pollShellStatus, 10000);
}

function renderSidebar(activePage) {
  const sidebarContainer = document.getElementById('app-sidebar');
  if (!sidebarContainer) return;

  const navItems = [
    { id: 'overview', href: '/overview', label: 'Overview', icon: '◫' },
    { id: 'clips', href: '/clips', label: 'Clips', icon: '▶' },
    { id: 'areas', href: '/areas', label: 'Areas', icon: '⬚' },
    { id: 'cameras', href: '/cameras', label: 'Cameras', icon: '📹' },
    { id: 'settings', href: '/settings', label: 'Settings', icon: '⚙' },
  ];

  sidebarContainer.innerHTML = `
    <aside class="shell-sidebar">
      <div class="sidebar-brand">
        <a href="/overview" class="brand-link">
          <span class="brand-name">VYZN</span>
        </a>
      </div>
      <nav class="sidebar-nav" aria-label="Main Navigation">
        ${navItems.map(item => `
          <a href="${item.href}" class="nav-item ${item.id === activePage ? 'is-active' : ''}" data-nav="${item.id}">
            <span class="nav-icon">${item.icon}</span>
            <span class="nav-label">${item.label}</span>
          </a>
        `).join('')}
      </nav>
      <div class="sidebar-footer">
        <div class="retention-pill" title="Footage and clips delete after 72 hours">
          <span>72 h retention</span>
        </div>
      </div>
    </aside>
  `;
}

function renderHeader() {
  const headerContainer = document.getElementById('app-header');
  if (!headerContainer) return;

  headerContainer.innerHTML = `
    <header class="shell-header">
      <div class="header-left">
        <div class="mobile-brand">
          <a href="/overview" class="brand-link">
            <span class="brand-name">VYZN</span>
          </a>
        </div>
        <h1 class="header-page-title" id="page-title-text"></h1>
      </div>
      <div class="header-right">
        <!-- Status Pill Priority 1-5 -->
        <div class="status-pill-wrap" id="status-pill-wrap">
          <button type="button" class="header-status-pill neutral" id="btn-status-pill" aria-expanded="false" aria-label="System status">
            <span class="status-dot neutral" id="pill-dot"></span>
            <span class="pill-text desktop-only" id="pill-text-desktop">Checking…</span>
            <span class="pill-text mobile-only" id="pill-text-mobile">Checking…</span>
          </button>
          <div class="status-popover" id="status-popover" style="display: none;" role="dialog" aria-label="Connection details">
            <div class="popover-header">System status</div>
            <div class="popover-body" id="popover-body">
              <div class="popover-item" id="popover-telegram">Telegram: Checking…</div>
              <div class="popover-cameras-list" id="popover-cameras-list"></div>
            </div>
          </div>
        </div>

        <!-- Account Avatar UK & Menu -->
        <div class="account-menu-wrap">
          <button type="button" class="account-avatar-btn" id="btn-account-menu" aria-label="Account menu" aria-expanded="false">
            <span class="avatar-initials">UK</span>
          </button>
          <div class="account-dropdown" id="account-dropdown" style="display: none;">
            <div class="dropdown-header">
              <span class="user-role">Shop Owner</span>
            </div>
            <div class="dropdown-divider"></div>
            <div class="theme-switch-row">
              <span class="theme-label">Theme</span>
              <div class="theme-btn-group" id="theme-btn-group">
                <button type="button" class="theme-opt-btn" data-set-theme="light">Light</button>
                <button type="button" class="theme-opt-btn" data-set-theme="dark">Dark</button>
              </div>
            </div>
            <div class="dropdown-divider"></div>
            <a href="/settings" class="dropdown-item">Settings</a>
            <button type="button" class="dropdown-item danger" id="btn-signout">Sign out</button>
          </div>
        </div>
      </div>
    </header>
  `;
}

function renderBottomNav(activePage) {
  const bottomNavContainer = document.getElementById('app-bottom-nav');
  if (!bottomNavContainer) return;

  const mobileItems = [
    { id: 'overview', href: '/overview', label: 'Over', icon: '◫' },
    { id: 'clips', href: '/clips', label: 'Clips', icon: '▶' },
    { id: 'areas', href: '/areas', label: 'Areas', icon: '⬚' },
    { id: 'cameras', href: '/cameras', label: 'Cams', icon: '📹' },
    { id: 'settings', href: '/settings', label: 'More', icon: '⋯' },
  ];

  bottomNavContainer.innerHTML = `
    <nav class="shell-bottom-nav" aria-label="Mobile Navigation">
      ${mobileItems.map(item => `
        <a href="${item.href}" class="bottom-nav-item ${item.id === activePage ? 'is-active' : ''}">
          <span class="bottom-icon">${item.icon}</span>
          <span class="bottom-label">${item.label}</span>
        </a>
      `).join('')}
    </nav>
  `;
}

function attachShellEvents() {
  // Theme Switching
  const currentTheme = document.documentElement.getAttribute('data-theme') || 'dark';
  updateThemeButtons(currentTheme);

  document.querySelectorAll('[data-set-theme]').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const theme = btn.getAttribute('data-set-theme');
      document.documentElement.setAttribute('data-theme', theme);
      localStorage.setItem('vyzn_theme', theme);
      updateThemeButtons(theme);
    });
  });

  // Account Menu Toggle
  const accountBtn = document.getElementById('btn-account-menu');
  const accountDropdown = document.getElementById('account-dropdown');
  if (accountBtn && accountDropdown) {
    accountBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      const isOpen = accountDropdown.style.display === 'block';
      closeAllPopovers();
      if (!isOpen) {
        accountDropdown.style.display = 'block';
        accountBtn.setAttribute('aria-expanded', 'true');
      }
    });
  }

  // Status Pill Popover Toggle
  const pillBtn = document.getElementById('btn-status-pill');
  const statusPopover = document.getElementById('status-popover');
  if (pillBtn && statusPopover) {
    pillBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      const isOpen = statusPopover.style.display === 'block';
      closeAllPopovers();
      if (!isOpen) {
        statusPopover.style.display = 'block';
        pillBtn.setAttribute('aria-expanded', 'true');
      }
    });
  }

  // Close menus on outside click
  document.addEventListener('click', () => {
    closeAllPopovers();
  });

  // Sign out button
  const signOutBtn = document.getElementById('btn-signout');
  if (signOutBtn) {
    signOutBtn.addEventListener('click', async () => {
      try {
        await fetch('/api/auth/signout', { method: 'POST' });
      } catch (err) {}
      window.location.href = '/login';
    });
  }
}

function closeAllPopovers() {
  const accountDropdown = document.getElementById('account-dropdown');
  const statusPopover = document.getElementById('status-popover');
  const accountBtn = document.getElementById('btn-account-menu');
  const pillBtn = document.getElementById('btn-status-pill');

  if (accountDropdown) accountDropdown.style.display = 'none';
  if (statusPopover) statusPopover.style.display = 'none';
  if (accountBtn) accountBtn.setAttribute('aria-expanded', 'false');
  if (pillBtn) pillBtn.setAttribute('aria-expanded', 'false');
}

function updateThemeButtons(theme) {
  document.querySelectorAll('[data-set-theme]').forEach(btn => {
    btn.classList.toggle('is-selected', btn.getAttribute('data-set-theme') === theme);
  });
}

export async function pollShellStatus() {
  try {
    const res = await fetch('/api/shell/status');
    if (!res.ok) return;
    const data = await res.json();
    const pill = data.pill;
    if (!pill) return;

    const pillBtn = document.getElementById('btn-status-pill');
    const pillDot = document.getElementById('pill-dot');
    const textDesk = document.getElementById('pill-text-desktop');
    const textMob = document.getElementById('pill-text-mobile');

    if (pillBtn) {
      pillBtn.className = `header-status-pill ${pill.style}`;
    }
    if (pillDot) {
      pillDot.className = `status-dot ${pill.style}`;
    }
    if (textDesk) textDesk.textContent = pill.text;
    if (textMob) textMob.textContent = pill.short_text || pill.text;

    // Update Popover content
    const popTg = document.getElementById('popover-telegram');
    if (popTg) {
      popTg.textContent = data.telegram_connected ? 'Telegram: Connected' : 'Telegram: Not connected';
      popTg.className = `popover-item ${data.telegram_connected ? 'ok' : 'warn'}`;
    }
  } catch (err) {
    // Quiet fail on network hiccups
  }
}

/**
 * Reusable modal prompting user for their 6-digit Security PIN
 * before sensitive operations (e.g. adding/deleting cameras, deleting clips).
 */
export function promptSecurityPin({
  title = 'Security Verification',
  description = 'Enter your 6-digit Security PIN to proceed with this action.',
  confirmText = 'Confirm',
  isDanger = false
} = {}) {
  return new Promise((resolve) => {
    let modal = document.getElementById('security-pin-modal');
    if (!modal) {
      modal = document.createElement('div');
      modal.id = 'security-pin-modal';
      modal.className = 'modal-scrim';
      modal.style.cssText = 'position:fixed; inset:0; background:rgba(0,0,0,0.75); display:none; align-items:center; justify-content:center; z-index:9999; padding:16px; backdrop-filter:blur(4px);';
      document.body.appendChild(modal);
    }

    modal.innerHTML = `
      <div class="modal-card" style="background:var(--bg-1, #131720); border:1px solid var(--border-subtle, #232a3b); border-radius:14px; padding:24px; max-width:400px; width:100%; box-shadow:0 24px 48px rgba(0,0,0,0.6); box-sizing:border-box;">
        <div style="display:flex; align-items:center; gap:12px; margin-bottom:12px;">
          <div style="width:38px; height:38px; border-radius:10px; background:rgba(59, 130, 246, 0.15); display:flex; align-items:center; justify-content:center; font-size:20px;">🛡️</div>
          <h3 style="margin:0; font-size:18px; font-weight:600; color:var(--text-1, #f1f5f9);">${escapeHtml(title)}</h3>
        </div>
        <p style="margin:0 0 16px 0; font-size:14px; color:var(--text-2, #94a3b8); line-height:1.5;">${escapeHtml(description)}</p>
        <div style="margin-bottom:20px;">
          <label style="display:block; font-size:11px; font-weight:600; letter-spacing:0.5px; text-transform:uppercase; color:var(--text-3, #64748b); margin-bottom:8px;">6-digit Security PIN</label>
          <input type="password" id="sec-modal-pin-input" maxlength="8" inputmode="numeric" pattern="[0-9]*" placeholder="••••••" style="width:100%; box-sizing:border-box; padding:12px 14px; font-size:22px; letter-spacing:6px; text-align:center; background:var(--bg-2, #1a202c); color:var(--text-1, #f1f5f9); border:1px solid var(--border-subtle, #2e384d); border-radius:8px; outline:none;" autocomplete="off" />
          <div style="font-size:12px; color:var(--text-3, #64748b); margin-top:8px; display:flex; justify-content:space-between; align-items:center;">
            <span>Default PIN: <strong>202600</strong></span>
            <a href="/settings" style="color:var(--action, #3b82f6); text-decoration:none;">Manage in Settings</a>
          </div>
          <div id="sec-modal-error" style="color:#ef4444; font-size:12px; margin-top:6px; display:none;"></div>
        </div>
        <div style="display:flex; justify-content:flex-end; gap:10px;">
          <button type="button" class="btn btn-secondary" id="sec-modal-btn-cancel" style="padding:8px 16px;">Cancel</button>
          <button type="button" class="btn ${isDanger ? 'btn-danger' : 'btn-primary'}" id="sec-modal-btn-confirm" style="padding:8px 16px; ${isDanger ? 'background:#ef4444; color:#fff; border:none;' : ''}">${escapeHtml(confirmText)}</button>
        </div>
      </div>
    `;

    modal.style.display = 'flex';
    const input = document.getElementById('sec-modal-pin-input');
    const btnConfirm = document.getElementById('sec-modal-btn-confirm');
    const btnCancel = document.getElementById('sec-modal-btn-cancel');

    setTimeout(() => { if (input) input.focus(); }, 50);

    const cleanup = () => {
      modal.style.display = 'none';
      modal.innerHTML = '';
    };

    const handleConfirm = () => {
      const pin = input ? input.value.trim() : '';
      if (!pin) {
        const err = document.getElementById('sec-modal-error');
        if (err) {
          err.textContent = 'Please enter your Security PIN.';
          err.style.display = 'block';
        }
        if (input) input.focus();
        return;
      }
      cleanup();
      resolve(pin);
    };

    const handleCancel = () => {
      cleanup();
      resolve(null);
    };

    if (btnConfirm) btnConfirm.addEventListener('click', handleConfirm);
    if (btnCancel) btnCancel.addEventListener('click', handleCancel);

    if (input) {
      input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') handleConfirm();
        if (e.key === 'Escape') handleCancel();
      });
    }
  });
}

