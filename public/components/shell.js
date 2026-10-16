/**
 * VYZN Unified App Shell & Navigation Component (Section 6.0)
 * Renders desktop sidebar / mobile bottom bar, header status pill with priority 1-5,
 * and user account menu with theme switcher.
 */

import { escapeHtml } from '../utils.js';
import { openWallView } from './wall-view.js';

export async function enforceAuth() {
  try {
    const res = await fetch('/api/me', { credentials: 'include' });
    if (!res.ok) {
      localStorage.removeItem('vyzn_user');
      window.location.replace('/login');
      return null;
    }
    const user = await res.json();
    if (!user || !user.email) {
      localStorage.removeItem('vyzn_user');
      window.location.replace('/login');
      return null;
    }
    localStorage.setItem('vyzn_user', JSON.stringify(user));
    return user;
  } catch (err) {
    const cached = localStorage.getItem('vyzn_user');
    if (!cached) {
      window.location.replace('/login');
      return null;
    }
    try {
      return JSON.parse(cached);
    } catch (_) {
      window.location.replace('/login');
      return null;
    }
  }
}

export async function initShell({ activePage = 'overview' } = {}) {
  // Enforce authentication on all protected pages
  const user = await enforceAuth();
  if (!user) return;

  // Apply saved theme
  const savedTheme = localStorage.getItem('vyzn_theme') || 'dark';
  document.documentElement.setAttribute('data-theme', savedTheme);

  // Render shell elements with user state
  renderSidebar(activePage, user);
  renderHeader(activePage, user);
  renderBottomNav(activePage);
  attachShellEvents(user);

  // Initial poll for header status pill
  pollShellStatus();
  setInterval(pollShellStatus, 10000);
}

function renderSidebar(activePage, user = {}) {
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
          <span class="brand-name">
            <span class="brand-dot"></span>VYZN
          </span>
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

function renderHeader(activePage, user = {}) {
  const headerContainer = document.getElementById('app-header');
  if (!headerContainer) return;

  const initials = (user.full_name ? user.full_name.split(' ').map(n => n[0]).join('').substring(0, 2).toUpperCase() : (user.email ? user.email.substring(0, 2).toUpperCase() : 'VZ')) || 'VZ';
  const roleName = user.business_name || user.full_name || 'Society Owner';

  headerContainer.innerHTML = `
    <header class="shell-header">
      <div class="header-left">
        <div class="mobile-brand">
          <a href="/overview" class="brand-link">
            <span class="brand-name"><span class="brand-dot"></span>VYZN</span>
          </a>
        </div>
        <h1 class="header-page-title" id="page-title-text"></h1>
      </div>
      <div class="header-right">
        <!-- Wall View Button (Overview header) -->
        ${activePage === 'overview' ? `
          <button type="button" class="btn btn-secondary" id="btn-wall-view" title="Fullscreen all cameras (F)" style="height: 36px; min-height: 36px; font-size: 13px; gap: 6px; padding: 0 12px; margin-right: 4px; cursor: pointer;">
            <span style="font-size: 14px;">▦</span>
            <span>Wall view</span>
          </button>
        ` : ''}

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

        <!-- Account Avatar & Menu -->
        <div class="account-menu-wrap">
          <button type="button" class="account-avatar-btn" id="btn-account-menu" aria-label="Account menu" aria-expanded="false" title="${escapeHtml(user.email || '')}">
            <span class="avatar-initials">${escapeHtml(initials)}</span>
          </button>
          <div class="account-dropdown" id="account-dropdown" style="display: none;">
            <div class="dropdown-header">
              <span class="user-role">${escapeHtml(roleName)}</span>
              <span class="user-email" style="display: block; font-size: 11px; color: var(--text-3, #94a3b8); margin-top: 2px;">${escapeHtml(user.email || '')}</span>
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

function attachShellEvents(user = {}) {
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

  // Wall view header button
  const wallBtn = document.getElementById('btn-wall-view');
  if (wallBtn) {
    wallBtn.addEventListener('click', (e) => {
      e.preventDefault();
      openWallView();
    });
  }

  // Sign out button
  const signOutBtn = document.getElementById('btn-signout');
  if (signOutBtn) {
    signOutBtn.addEventListener('click', async () => {
      try {
        await fetch('/api/auth/signout', { method: 'POST', credentials: 'include' });
      } catch (err) {}
      localStorage.removeItem('vyzn_user');
      sessionStorage.clear();
      window.location.replace('/login');
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
    const res = await fetch('/api/shell/status', { credentials: 'include' });
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
  confirmText = 'Verify PIN',
  isDanger = false,
  onSuccess = null,
  onCancel = null
} = {}) {
  return new Promise((resolve) => {
    const existing = document.getElementById('vyzn-pin-modal');
    if (existing) existing.remove();

    const modal = document.createElement('div');
    modal.id = 'vyzn-pin-modal';
    modal.className = 'vms-modal-backdrop modal-scrim';
    modal.style.cssText = 'position:fixed;inset:0;background:rgba(2,6,23,0.8);z-index:99999;display:flex;align-items:center;justify-content:center;backdrop-filter:blur(4px);padding:16px;box-sizing:border-box;';

    modal.innerHTML = `
      <div class="vms-modal-content modal-card" style="background:var(--bg-elevated, #0f172a);border:1px solid var(--border-default, #1e293b);border-radius:12px;padding:24px;width:100%;max-width:380px;box-shadow:0 20px 25px -5px rgba(0,0,0,0.5);box-sizing:border-box;">
        <div style="display:flex; align-items:center; gap:12px; margin-bottom:12px;">
          <div style="width:36px; height:36px; border-radius:10px; background:rgba(59, 130, 246, 0.15); display:flex; align-items:center; justify-content:center; font-size:18px;">🛡️</div>
          <h3 style="margin:0;font-size:17px;font-weight:600;color:var(--text-1, #f8fafc);">${escapeHtml(title)}</h3>
        </div>
        <p style="margin:0 0 16px 0;font-size:13px;color:var(--text-2, #94a3b8);line-height:1.4;">${escapeHtml(description)}</p>
        
        <div id="pin-modal-error" style="display:none;background:rgba(239,68,68,0.15);border:1px solid rgba(239,68,68,0.3);color:#f87171;padding:8px 12px;border-radius:6px;font-size:12px;margin-bottom:12px;"></div>

        <div style="margin-bottom:16px;">
          <input type="password" id="pin-modal-input" maxlength="8" inputmode="numeric" autocomplete="one-time-code" placeholder="••••••" style="width:100%;box-sizing:border-box;padding:10px 14px;text-align:center;font-size:22px;letter-spacing:6px;background:var(--bg-card, #020617);border:1px solid var(--border-default, #334155);border-radius:8px;color:#fff;outline:none;" autofocus />
          <div style="font-size:11px; color:var(--text-3, #64748b); margin-top:8px; display:flex; justify-content:space-between; align-items:center;">
            <span>Default PIN: <strong>202600</strong></span>
            <a href="/settings" style="color:var(--action, #3b82f6); text-decoration:none;">Manage in Settings</a>
          </div>
        </div>

        <div style="display:flex;justify-content:flex-end;gap:8px;">
          <button type="button" id="btn-pin-cancel" class="btn btn-secondary" style="height:36px;padding:0 14px;font-size:13px;">Cancel</button>
          <button type="button" id="btn-pin-submit" class="btn ${isDanger ? 'btn-danger' : 'btn-primary'}" style="height:36px;padding:0 14px;font-size:13px;${isDanger ? 'background:#ef4444;color:#fff;border:none;' : ''}">${escapeHtml(confirmText)}</button>
        </div>
      </div>
    `;

    document.body.appendChild(modal);

    const input = modal.querySelector('#pin-modal-input');
    const submitBtn = modal.querySelector('#btn-pin-submit');
    const cancelBtn = modal.querySelector('#btn-pin-cancel');

    setTimeout(() => { if (input) input.focus(); }, 50);

    const cleanup = () => {
      modal.remove();
    };

    const handleConfirm = () => {
      const pin = (input && input.value.trim()) ? input.value.trim() : '202600';
      cleanup();
      if (typeof onSuccess === 'function') onSuccess(pin);
      resolve(pin);
    };

    const handleCancel = () => {
      cleanup();
      if (typeof onCancel === 'function') onCancel();
      resolve(null);
    };

    if (submitBtn) submitBtn.addEventListener('click', handleConfirm);
    if (cancelBtn) cancelBtn.addEventListener('click', handleCancel);

    if (input) {
      input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') handleConfirm();
        if (e.key === 'Escape') handleCancel();
      });
    }
  });
}
