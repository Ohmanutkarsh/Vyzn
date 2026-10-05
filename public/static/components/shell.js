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
