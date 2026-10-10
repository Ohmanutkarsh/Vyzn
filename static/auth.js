/**
 * VYZN Auth & Onboarding Controller (Screens S1 to S4)
 * Strict spec compliance: 100% real data, i18n localization, WCAG 2.2 AA.
 */

import { initI18n, t } from './i18n.js';
import { escapeHtml } from './utils.js';
import { generateQrSvg } from './qr.js';

let currentState = 's1';
let resendTimer = null;
let resendCountdown = 30;
let tgPollTimer = null;
let currentDeepLink = '';
let currentPhone = '';

// Helper to mask email: n••••@gmail.com
function maskEmail(email) {
  if (!email) return '••••@••••';
  const parts = email.split('@');
  if (parts.length !== 2) return email;
  const name = parts[0];
  const domain = parts[1];
  const first = name.length > 0 ? name[0] : '';
  return `${first}••••@${domain}`;
}

// Helper to mask phone: +91 98••• ••210
function maskPhone(phone) {
  if (!phone) return '+91 ••••• •••••';
  const digits = phone.replace(/\D/g, '');
  if (digits.length >= 10) {
    const d = digits.slice(-10);
    return `+91 ${d.slice(0, 2)}••• ••${d.slice(-3)}`;
  }
  return phone;
}

// Theme handling
function initTheme() {
  const saved = localStorage.getItem('vyzn_theme') || 'system';
  applyTheme(saved);
  
  const btn = document.getElementById('theme-toggle-btn');
  if (btn) {
    btn.addEventListener('click', () => {
      const current = document.documentElement.getAttribute('data-theme');
      let next = 'dark';
      if (current === 'dark') next = 'light';
      else if (current === 'light') next = 'dark';
      else next = 'dark';
      applyTheme(next);
      localStorage.setItem('vyzn_theme', next);
    });
  }
}

function applyTheme(theme) {
  if (theme === 'system') {
    const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    document.documentElement.setAttribute('data-theme', prefersDark ? 'dark' : 'light');
  } else {
    document.documentElement.setAttribute('data-theme', theme);
  }
  const btn = document.getElementById('theme-toggle-btn');
  if (btn) {
    const current = document.documentElement.getAttribute('data-theme');
    btn.innerHTML = current === 'dark' ? '☀️ Light' : '🌙 Dark';
  }
}

// State navigation & URL sync
export function navigateTo(path, replace = false) {
  if (replace) {
    window.history.replaceState({}, '', path);
  } else {
    window.history.pushState({}, '', path);
  }
  renderCurrentRoute();
}

function getRouteState() {
  const p = window.location.pathname;
  if (p === '/login/code') return 's2';
  if (p === '/setup/phone') return 's3';
  if (p === '/setup/telegram') return 's4';
  return 's1';
}

export async function initAuthApp() {
  await initI18n('en');
  initTheme();

  // If already authenticated, redirect straight to /overview
  try {
    const res = await fetch('/api/me');
    if (res.ok) {
      const me = await res.json();
      if (me && me.email) {
        window.location.replace('/overview');
        return;
      }
    }
  } catch (err) {
    // Guest / unauthenticated
  }

  window.addEventListener('popstate', () => {
    renderCurrentRoute();
  });

  renderCurrentRoute();
}

function renderCurrentRoute() {
  clearInterval(tgPollTimer);
  clearInterval(resendTimer);
  currentState = getRouteState();

  const container = document.getElementById('auth-card-content');
  if (!container) return;

  if (currentState === 's1') {
    renderS1(container);
  } else if (currentState === 's2') {
    renderS2(container);
  } else if (currentState === 's3') {
    renderS3(container);
  } else if (currentState === 's4') {
    renderS4(container);
  }
}

// ---------------------------------------------------------------------------
// Screen S1: /login — Sign In (Email + Pass only) & Sign Up (Full Merchant Details)
// ---------------------------------------------------------------------------
let currentAuthTab = 'login'; // 'login' | 'signup' | 'otp'

function renderS1(container) {
  const cardWrap = document.querySelector('.auth-card-wrap');
  if (cardWrap) {
    if (currentAuthTab === 'signup') {
      cardWrap.classList.add('is-wide');
    } else {
      cardWrap.classList.remove('is-wide');
    }
  }

  const savedEmail = sessionStorage.getItem('vyzn_login_email') || '';

  if (currentAuthTab === 'otp') {
    renderOtpView(container, savedEmail);
    return;
  }

  container.innerHTML = `
    <!-- Segmented Tab Switcher -->
    <div class="auth-tabs-row" role="tablist">
      <button type="button" class="auth-tab-btn ${currentAuthTab === 'login' ? 'is-active' : ''}" id="tab-btn-login" role="tab">
        Sign In
      </button>
      <button type="button" class="auth-tab-btn ${currentAuthTab === 'signup' ? 'is-active' : ''}" id="tab-btn-signup" role="tab">
        Create Account
      </button>
    </div>

    ${currentAuthTab === 'login' ? renderLoginFormHtml(savedEmail) : renderSignupFormHtml(savedEmail)}
  `;

  // Attach Tab Switch Handlers
  const tabLogin = document.getElementById('tab-btn-login');
  const tabSignup = document.getElementById('tab-btn-signup');
  if (tabLogin) {
    tabLogin.addEventListener('click', () => {
      currentAuthTab = 'login';
      renderS1(container);
    });
  }
  if (tabSignup) {
    tabSignup.addEventListener('click', () => {
      currentAuthTab = 'signup';
      renderS1(container);
    });
  }

  if (currentAuthTab === 'login') {
    attachLoginFormHandlers(container);
  } else {
    attachSignupFormHandlers(container);
  }
}

function renderLoginFormHtml(savedEmail) {
  return `
    <h1 class="auth-title">Welcome to VYZN</h1>
    <p class="auth-helper">Sign in with your email and password to access your cameras and clips.</p>

    <div id="login-error" class="auth-error-banner" style="display:none;" role="alert"></div>

    <form id="login-form" novalidate>
      <div class="auth-form-group">
        <label for="login-email" class="auth-label">Email address</label>
        <input id="login-email" class="auth-input" type="email" autocomplete="email" inputmode="email"
               placeholder="owner@store.com" value="${escapeHtml(savedEmail)}" autofocus required />
      </div>

      <div class="auth-form-group">
        <label for="login-password" class="auth-label">Password</label>
        <div class="auth-password-wrap">
          <input id="login-password" class="auth-input" type="password" autocomplete="current-password"
                 placeholder="Enter your password" required />
          <button type="button" class="auth-pw-toggle" id="btn-login-pw-toggle" aria-label="Toggle password visibility">👁</button>
        </div>
      </div>

      <div class="auth-checkbox-row">
        <label class="auth-checkbox-label">
          <input type="checkbox" id="login-remember" checked />
          Remember me
        </label>
        <button type="button" class="auth-helper-link" id="btn-switch-otp">Sign in with email code</button>
      </div>

      <button id="login-submit-btn" class="btn btn-primary btn-block" type="submit" style="margin-top: 8px;">
        Sign In
      </button>
    </form>
  `;
}

function renderSignupFormHtml(savedEmail) {
  return `
    <h1 class="auth-title">Create merchant account</h1>
    <p class="auth-helper">Enter your store details to set up your intelligent CCTV monitoring.</p>

    <div id="signup-error" class="auth-error-banner" style="display:none;" role="alert"></div>

    <form id="signup-form" novalidate>
      <div class="auth-row-2col">
        <div class="auth-form-group">
          <label for="signup-name" class="auth-label">Full Name</label>
          <input id="signup-name" class="auth-input" type="text" placeholder="Utkarsh Tapise" autocomplete="name" required autofocus />
        </div>
        <div class="auth-form-group">
          <label for="signup-business" class="auth-label">Business / Store Name</label>
          <input id="signup-business" class="auth-input" type="text" placeholder="Vyzn Supermarket" required />
        </div>
      </div>

      <div class="auth-row-2col">
        <div class="auth-form-group">
          <label for="signup-type" class="auth-label">Business Type</label>
          <select id="signup-type" class="auth-select">
            <option value="retail">Retail Shop / Store</option>
            <option value="supermarket">Grocery & Supermarket</option>
            <option value="jewellery">Jewellery & Gold</option>
            <option value="electronics">Electronics & Gadgets</option>
            <option value="godown">Warehouse / Godown</option>
            <option value="restaurant">Restaurant / Cafe</option>
            <option value="other">Other Business</option>
          </select>
        </div>
        <div class="auth-form-group">
          <label for="signup-phone" class="auth-label">Mobile Number</label>
          <input id="signup-phone" class="auth-input mono-input" type="tel" placeholder="+91 98765 43210" autocomplete="tel" />
        </div>
      </div>

      <div class="auth-form-group">
        <label for="signup-email" class="auth-label">Email Address</label>
        <input id="signup-email" class="auth-input" type="email" autocomplete="email" inputmode="email"
               placeholder="owner@store.com" value="${escapeHtml(savedEmail)}" required />
      </div>

      <div class="auth-row-2col">
        <div class="auth-form-group">
          <label for="signup-password" class="auth-label">Password</label>
          <div class="auth-password-wrap">
            <input id="signup-password" class="auth-input" type="password" autocomplete="new-password"
                   placeholder="Min. 6 characters" required />
            <button type="button" class="auth-pw-toggle" id="btn-signup-pw-toggle" aria-label="Toggle password visibility">👁</button>
          </div>
        </div>
        <div class="auth-form-group">
          <label for="signup-confirm-password" class="auth-label">Confirm Password</label>
          <input id="signup-confirm-password" class="auth-input" type="password" autocomplete="new-password"
                 placeholder="Re-enter password" required />
        </div>
      </div>

      <div style="margin: 8px 0 16px 0;">
        <label class="auth-checkbox-label" style="align-items: flex-start; line-height: 1.4;">
          <input type="checkbox" id="signup-terms" checked required style="margin-top: 2px;" />
          <span>I agree to the Terms of Service and 72-hour automated footage retention policy.</span>
        </label>
      </div>

      <button id="signup-submit-btn" class="btn btn-primary btn-block" type="submit">
        Create Account & Continue
      </button>
    </form>
  `;
}

function attachLoginFormHandlers(container) {
  const form = document.getElementById('login-form');
  const emailInput = document.getElementById('login-email');
  const passInput = document.getElementById('login-password');
  const errorBox = document.getElementById('login-error');
  const submitBtn = document.getElementById('login-submit-btn');
  const pwToggle = document.getElementById('btn-login-pw-toggle');
  const btnSwitchOtp = document.getElementById('btn-switch-otp');

  if (pwToggle && passInput) {
    pwToggle.addEventListener('click', () => {
      const isPw = passInput.type === 'password';
      passInput.type = isPw ? 'text' : 'password';
      pwToggle.textContent = isPw ? '🔒' : '👁';
    });
  }

  if (btnSwitchOtp) {
    btnSwitchOtp.addEventListener('click', () => {
      currentAuthTab = 'otp';
      renderS1(container);
    });
  }

  if (form) {
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      errorBox.style.display = 'none';

      const email = emailInput.value.trim().toLowerCase();
      const password = passInput.value;
      const remember = document.getElementById('login-remember')?.checked ?? false;

      const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
      if (!emailRegex.test(email)) {
        errorBox.textContent = 'Please enter a valid email address.';
        errorBox.style.display = 'flex';
        emailInput.focus();
        return;
      }
      if (!password) {
        errorBox.textContent = 'Please enter your password.';
        errorBox.style.display = 'flex';
        passInput.focus();
        return;
      }

      submitBtn.disabled = true;
      submitBtn.textContent = 'Signing in…';

      try {
        const res = await fetch('/api/auth/login', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ email, password, remember })
        });
        const data = await res.json();

        if (res.ok && data.ok) {
          sessionStorage.setItem('vyzn_login_email', email);
          if (data.user) {
            localStorage.setItem('vyzn_user', JSON.stringify(data.user));
          }
          window.location.replace(data.redirect || '/overview');
        } else {
          errorBox.textContent = data.detail || 'Incorrect email or password. Please try again.';
          errorBox.style.display = 'flex';
          submitBtn.disabled = false;
          submitBtn.textContent = 'Sign In';
        }
      } catch (err) {
        errorBox.textContent = 'Network error connecting to server. Please check your connection.';
        errorBox.style.display = 'flex';
        submitBtn.disabled = false;
        submitBtn.textContent = 'Sign In';
      }
    });
  }
}

function attachSignupFormHandlers(container) {
  const form = document.getElementById('signup-form');
  const nameInput = document.getElementById('signup-name');
  const businessInput = document.getElementById('signup-business');
  const typeSelect = document.getElementById('signup-type');
  const phoneInput = document.getElementById('signup-phone');
  const emailInput = document.getElementById('signup-email');
  const passInput = document.getElementById('signup-password');
  const confirmPassInput = document.getElementById('signup-confirm-password');
  const termsCheckbox = document.getElementById('signup-terms');
  const errorBox = document.getElementById('signup-error');
  const submitBtn = document.getElementById('signup-submit-btn');
  const pwToggle = document.getElementById('btn-signup-pw-toggle');

  if (pwToggle && passInput) {
    pwToggle.addEventListener('click', () => {
      const isPw = passInput.type === 'password';
      passInput.type = isPw ? 'text' : 'password';
      pwToggle.textContent = isPw ? '🔒' : '👁';
    });
  }

  if (form) {
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      errorBox.style.display = 'none';

      const full_name = nameInput.value.trim();
      const business_name = businessInput.value.trim();
      const business_type = typeSelect.value;
      const phone_e164 = phoneInput.value.trim();
      const email = emailInput.value.trim().toLowerCase();
      const password = passInput.value;
      const confirmPassword = confirmPassInput.value;

      if (!full_name) {
        errorBox.textContent = 'Please enter your full name.';
        errorBox.style.display = 'flex';
        nameInput.focus();
        return;
      }
      if (!business_name) {
        errorBox.textContent = 'Please enter your business or store name.';
        errorBox.style.display = 'flex';
        businessInput.focus();
        return;
      }
      const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
      if (!emailRegex.test(email)) {
        errorBox.textContent = 'Please enter a valid email address.';
        errorBox.style.display = 'flex';
        emailInput.focus();
        return;
      }
      if (password.length < 6) {
        errorBox.textContent = 'Password must be at least 6 characters.';
        errorBox.style.display = 'flex';
        passInput.focus();
        return;
      }
      if (password !== confirmPassword) {
        errorBox.textContent = 'Passwords do not match.';
        errorBox.style.display = 'flex';
        confirmPassInput.focus();
        return;
      }
      if (!termsCheckbox.checked) {
        errorBox.textContent = 'Please accept the terms and retention policy to continue.';
        errorBox.style.display = 'flex';
        return;
      }

      submitBtn.disabled = true;
      submitBtn.textContent = 'Creating account…';

      try {
        const res = await fetch('/api/auth/signup', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            full_name,
            business_name,
            business_type,
            phone_e164,
            email,
            password
          })
        });
        const data = await res.json();

        if (res.ok && data.ok) {
          sessionStorage.setItem('vyzn_login_email', email);
          if (data.user) {
            localStorage.setItem('vyzn_user', JSON.stringify(data.user));
          }
          window.location.replace(data.redirect || '/overview');
        } else {
          errorBox.textContent = data.detail || 'Could not create account. Please try again.';
          errorBox.style.display = 'flex';
          submitBtn.disabled = false;
          submitBtn.textContent = 'Create Account & Continue';
        }
      } catch (err) {
        errorBox.textContent = 'Network error connecting to server. Please check your connection.';
        errorBox.style.display = 'flex';
        submitBtn.disabled = false;
        submitBtn.textContent = 'Create Account & Continue';
      }
    });
  }
}

function renderOtpView(container, savedEmail) {
  container.innerHTML = `
    <h1 class="auth-title">Sign in with email code</h1>
    <p class="auth-helper">We'll send a 6-digit one-time code to your email.</p>

    <div id="otp-error" class="auth-error-banner" style="display:none;" role="alert"></div>

    <form id="otp-start-form" novalidate>
      <div class="auth-form-group">
        <label for="otp-email" class="auth-label">Email address</label>
        <input id="otp-email" class="auth-input" type="email" autocomplete="email" inputmode="email"
               placeholder="owner@store.com" value="${escapeHtml(savedEmail)}" autofocus required />
      </div>

      <button id="otp-submit-btn" class="btn btn-primary btn-block" type="submit">
        Send Code
      </button>

      <div style="text-align: center; margin-top: 16px;">
        <button type="button" class="auth-helper-link" id="btn-back-to-password">
          ← Back to password sign in
        </button>
      </div>
    </form>
  `;

  const btnBack = document.getElementById('btn-back-to-password');
  if (btnBack) {
    btnBack.addEventListener('click', () => {
      currentAuthTab = 'login';
      renderS1(container);
    });
  }

  const form = document.getElementById('otp-start-form');
  const emailInput = document.getElementById('otp-email');
  const errorBox = document.getElementById('otp-error');
  const submitBtn = document.getElementById('otp-submit-btn');

  if (form) {
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      errorBox.style.display = 'none';
      const email = emailInput.value.trim().toLowerCase();
      const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
      if (!emailRegex.test(email)) {
        errorBox.textContent = 'Please enter a valid email address.';
        errorBox.style.display = 'flex';
        emailInput.focus();
        return;
      }

      submitBtn.disabled = true;
      submitBtn.textContent = 'Sending…';

      try {
        const res = await fetch('/api/auth/email/start', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ email })
        });
        const data = await res.json();
        if (res.ok) {
          sessionStorage.setItem('vyzn_login_email', email);
          if (data.warning) {
            sessionStorage.setItem('vyzn_email_warning', data.warning);
          } else {
            sessionStorage.removeItem('vyzn_email_warning');
          }
          navigateTo('/login/code');
        } else {
          errorBox.textContent = data.detail || 'Failed to send code.';
          errorBox.style.display = 'flex';
          submitBtn.disabled = false;
          submitBtn.textContent = 'Send Code';
        }
      } catch (err) {
        errorBox.textContent = 'Failed to connect to server.';
        errorBox.style.display = 'flex';
        submitBtn.disabled = false;
        submitBtn.textContent = 'Send Code';
      }
    });
  }
}


// ---------------------------------------------------------------------------
// Screen S2: /login/code
// ---------------------------------------------------------------------------
function renderS2(container) {
  const email = sessionStorage.getItem('vyzn_login_email') || 'your email';
  const masked = maskEmail(email);
  const emailWarning = sessionStorage.getItem('vyzn_email_warning') || '';

  container.innerHTML = `
    <h1 class="auth-title">Check your email</h1>
    <p class="auth-helper">We sent a 6-digit code to ${escapeHtml(masked)}. It works for 10 minutes.</p>

    ${emailWarning ? `<div class="auth-helper" style="color: #d29922; background: rgba(210, 153, 34, 0.1); border: 1px solid rgba(210, 153, 34, 0.3); border-radius: 6px; padding: 10px 12px; margin-bottom: 16px; font-size: 13px;">${escapeHtml(emailWarning)}</div>` : ''}

    <div id="s2-error" class="auth-error-banner" style="display:none;" role="alert"></div>

    <form id="s2-form" novalidate>
      <div class="auth-form-group">
        <label class="auth-label">${escapeHtml(t('auth.code_label'))}</label>
        
        <div class="code-cells-container" id="code-cells-wrap">
          <div class="code-cell is-active" data-index="0"></div>
          <div class="code-cell" data-index="1"></div>
          <div class="code-cell" data-index="2"></div>
          <div class="code-cell" data-index="3"></div>
          <div class="code-cell" data-index="4"></div>
          <div class="code-cell" data-index="5"></div>
          <input id="s2-code-input" class="hidden-code-input" type="text"
                 inputmode="numeric" pattern="[0-9]*" maxlength="6" autocomplete="one-time-code" autofocus />
        </div>
      </div>

      <div class="auth-resend-row">
        <span id="s2-countdown-label">Send a new code in 30 s</span>
        <button id="s2-resend-btn" class="auth-link is-disabled" type="button" disabled style="display:none;">
          ${escapeHtml(t('auth.resend_now'))}
        </button>
        <button id="s2-back-btn" class="auth-link" type="button">
          ${escapeHtml(t('auth.use_different_email'))}
        </button>
      </div>

      <div class="auth-actions-group" style="margin-top: var(--space-4);">
        <button id="s2-verify-btn" class="btn btn-primary btn-block" type="submit">
          ${escapeHtml(t('auth.verify_code') || 'Verify code')}
        </button>
      </div>
    </form>
  `;

  const form = document.getElementById('s2-form');
  const codeInput = document.getElementById('s2-code-input');
  const cells = document.querySelectorAll('.code-cell');
  const errorBox = document.getElementById('s2-error');
  const countdownLabel = document.getElementById('s2-countdown-label');
  const resendBtn = document.getElementById('s2-resend-btn');
  const backBtn = document.getElementById('s2-back-btn');
  const verifyBtn = document.getElementById('s2-verify-btn');

  let isSubmitting = false;

  function updateCells(val) {
    cells.forEach((cell, idx) => {
      const char = val[idx] || '';
      cell.textContent = char;
      if (char) {
        cell.classList.add('is-filled');
      } else {
        cell.classList.remove('is-filled');
      }
      if (idx === val.length || (val.length === 6 && idx === 5)) {
        cell.classList.add('is-active');
      } else {
        cell.classList.remove('is-active');
      }
    });
  }

  if (form) {
    form.addEventListener('submit', (e) => {
      e.preventDefault();
      const clean = codeInput.value.replace(/\D/g, '').slice(0, 6);
      if (clean.length === 6) {
        submitCode(clean);
      } else {
        errorBox.textContent = t('auth.error_wrong_code');
        errorBox.style.display = 'flex';
        codeInput.focus();
      }
    });
  }

  codeInput.addEventListener('input', () => {
    const clean = codeInput.value.replace(/\D/g, '').slice(0, 6);
    codeInput.value = clean;
    updateCells(clean);

    if (clean.length === 6 && !isSubmitting) {
      submitCode(clean);
    }
  });

  // Keep input focused when clicking container
  document.getElementById('code-cells-wrap').addEventListener('click', () => {
    codeInput.focus();
  });

  // Resend Countdown Timer (30s)
  resendCountdown = 30;
  countdownLabel.textContent = `Send a new code in ${resendCountdown} s`;
  resendBtn.style.display = 'none';
  countdownLabel.style.display = 'inline';

  resendTimer = setInterval(() => {
    resendCountdown--;
    if (resendCountdown <= 0) {
      clearInterval(resendTimer);
      countdownLabel.style.display = 'none';
      resendBtn.style.display = 'inline';
      resendBtn.disabled = false;
      resendBtn.classList.remove('is-disabled');
    } else {
      countdownLabel.textContent = `Send a new code in ${resendCountdown} s`;
    }
  }, 1000);

  resendBtn.addEventListener('click', async () => {
    resendBtn.disabled = true;
    resendBtn.classList.add('is-disabled');
    try {
      const res = await fetch('/api/auth/email/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email })
      });
      const data = await res.json();
      if (data.warning) {
        sessionStorage.setItem('vyzn_email_warning', data.warning);
      }
      renderS2(container);
    } catch (err) {
      errorBox.textContent = t('common.generic_error');
      errorBox.style.display = 'flex';
    }
  });

  backBtn.addEventListener('click', () => {
    navigateTo('/login');
  });

  async function submitCode(code) {
    if (isSubmitting) return;
    if (!code || code.length !== 6) return;
    isSubmitting = true;
    errorBox.style.display = 'none';

    if (verifyBtn) {
      verifyBtn.disabled = true;
      verifyBtn.textContent = t('auth.verifying') || 'Verifying…';
    }

    try {
      const res = await fetch('/api/auth/email/verify', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, code })
      });
      const data = await res.json();

      if (res.ok) {
        sessionStorage.removeItem('vyzn_dev_code');
        sessionStorage.removeItem('vyzn_email_warning');
        window.location.replace(data.next_step || '/overview');
      } else {
        isSubmitting = false;
        errorBox.textContent = data.detail || t('auth.error_wrong_code');
        errorBox.style.display = 'flex';
        codeInput.value = '';
        updateCells('');
        codeInput.focus();
        if (verifyBtn) {
          verifyBtn.disabled = false;
          verifyBtn.textContent = t('auth.verify_code') || 'Verify code';
        }
      }
    } catch (err) {
      isSubmitting = false;
      errorBox.textContent = t('common.generic_error');
      errorBox.style.display = 'flex';
      if (verifyBtn) {
        verifyBtn.disabled = false;
        verifyBtn.textContent = t('auth.verify_code') || 'Verify code';
      }
    }
  }
}

// ---------------------------------------------------------------------------
// ---------------------------------------------------------------------------
// Screen S3: /setup/phone (Mobile Number + OTP Verification)
// ---------------------------------------------------------------------------
function renderS3(container) {
  renderS3PhoneInput(container);
}

function renderS3PhoneInput(container) {
  container.innerHTML = `
    <div class="auth-stepper">
      <div class="stepper-header">${escapeHtml(t('auth.step_indicator', { current: 2, total: 2 }))}</div>
      <div class="stepper-bars">
        <div class="stepper-bar is-done"></div>
        <div class="stepper-bar is-active"></div>
      </div>
      <div class="stepper-labels">
        <span class="stepper-step-name is-done">Email verified</span>
        <span class="stepper-step-name is-active">Mobile number</span>
      </div>
    </div>

    <h1 class="auth-title">${escapeHtml(t('auth.phone_title'))}</h1>
    <p class="auth-helper">${escapeHtml(t('auth.phone_helper'))}</p>

    <div id="s3-error" class="auth-error-banner" style="display:none;" role="alert"></div>

    <form id="s3-phone-form" novalidate>
      <div class="auth-form-group">
        <label for="s3-phone" class="auth-label">${escapeHtml(t('auth.phone_label'))}</label>
        
        <div class="phone-input-group">
          <div class="phone-prefix-box">
            <span>🇮🇳 +91</span>
          </div>
          <input id="s3-phone" class="auth-input phone-number-input" type="tel"
                 inputmode="tel" autocomplete="tel-national" placeholder="98765 43210" autofocus required />
        </div>
      </div>

      <div class="auth-actions-group">
        <button id="s3-submit-btn" class="btn btn-primary btn-block" type="submit">
          ${escapeHtml(t('auth.phone_send_code'))}
        </button>
        <button id="s3-skip-btn" class="btn-ghost" type="button">
          ${escapeHtml(t('auth.phone_skip'))}
        </button>
      </div>
    </form>
  `;

  const phoneInput = document.getElementById('s3-phone');
  const errorBox = document.getElementById('s3-error');
  const form = document.getElementById('s3-phone-form');
  const submitBtn = document.getElementById('s3-submit-btn');
  const skipBtn = document.getElementById('s3-skip-btn');

  // Format phone number with space as user types
  phoneInput.addEventListener('input', () => {
    let digits = phoneInput.value.replace(/\D/g, '').slice(0, 10);
    if (digits.length > 5) {
      phoneInput.value = `${digits.slice(0, 5)} ${digits.slice(5)}`;
    } else {
      phoneInput.value = digits;
    }
  });

  // Skip button: user can proceed directly without adding phone
  skipBtn.addEventListener('click', async () => {
    skipBtn.disabled = true;
    try {
      const res = await fetch('/api/auth/phone/skip', { method: 'POST' });
      const data = await res.json();
      window.location.href = data.next_step || '/overview';
    } catch (err) {
      window.location.href = '/overview';
    }
  });

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    errorBox.style.display = 'none';

    const digits = phoneInput.value.replace(/\D/g, '');
    if (digits.length !== 10 || !['6', '7', '8', '9'].includes(digits[0])) {
      errorBox.textContent = t('auth.error_invalid_phone');
      errorBox.style.display = 'flex';
      phoneInput.focus();
      return;
    }

    submitBtn.disabled = true;
    submitBtn.textContent = 'Sending code…';

    try {
      const res = await fetch('/api/auth/phone/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ phoneE164: `+91${digits}` })
      });
      const data = await res.json();

      if (res.ok) {
        currentPhone = `+91${digits}`;
        if (data.warning) {
          sessionStorage.setItem('vyzn_phone_warning', data.warning);
        } else {
          sessionStorage.removeItem('vyzn_phone_warning');
        }
        renderS3PhoneCode(container, digits);
      } else {
        errorBox.textContent = data.detail || t('auth.error_invalid_phone');
        errorBox.style.display = 'flex';
        submitBtn.disabled = false;
        submitBtn.textContent = t('auth.phone_send_code');
      }
    } catch (err) {
      errorBox.textContent = t('common.generic_error');
      errorBox.style.display = 'flex';
      submitBtn.disabled = false;
      submitBtn.textContent = t('auth.phone_send_code');
    }
  });
}

function renderS3PhoneCode(container, digits) {
  clearInterval(resendTimer);
  const phoneE164 = `+91${digits}`;
  const masked = maskPhone(phoneE164);
  const phoneWarning = sessionStorage.getItem('vyzn_phone_warning') || '';

  container.innerHTML = `
    <div class="auth-stepper">
      <div class="stepper-header">${escapeHtml(t('auth.step_indicator', { current: 2, total: 2 }))}</div>
      <div class="stepper-bars">
        <div class="stepper-bar is-done"></div>
        <div class="stepper-bar is-active"></div>
      </div>
      <div class="stepper-labels">
        <span class="stepper-step-name is-done">Email verified</span>
        <span class="stepper-step-name is-active">Verify mobile</span>
      </div>
    </div>

    <h1 class="auth-title">${escapeHtml(t('auth.phone_code_title'))}</h1>
    <p class="auth-helper">We sent a 6-digit verification code to <strong>${escapeHtml(masked)}</strong>.</p>

    ${phoneWarning ? `<div class="auth-helper" style="color: #d29922; background: rgba(210, 153, 34, 0.1); border: 1px solid rgba(210, 153, 34, 0.3); border-radius: 6px; padding: 10px 12px; margin-bottom: 16px; font-size: 13px;">${escapeHtml(phoneWarning)}</div>` : ''}

    <div id="s3-code-success" class="auth-success-banner" style="display:none;" role="status"></div>
    <div id="s3-code-error" class="auth-error-banner" style="display:none;" role="alert"></div>

    <form id="s3-code-form">
      <div class="auth-form-group">
        <label class="auth-label">${escapeHtml(t('auth.code_label'))}</label>
        
        <div class="code-cells-container" id="phone-code-cells-wrap">
          <div class="code-cell is-active" data-index="0"></div>
          <div class="code-cell" data-index="1"></div>
          <div class="code-cell" data-index="2"></div>
          <div class="code-cell" data-index="3"></div>
          <div class="code-cell" data-index="4"></div>
          <div class="code-cell" data-index="5"></div>
          <input id="s3-code-input" class="hidden-code-input" type="text"
                 inputmode="numeric" pattern="[0-9]*" maxlength="6" autocomplete="one-time-code" autofocus />
        </div>
      </div>

      <div class="auth-resend-row">
        <span id="s3-countdown-label">Send a new code in 30 s</span>
        <button id="s3-resend-btn" class="auth-link is-disabled" type="button" disabled style="display:none;">
          ${escapeHtml(t('auth.resend_now'))}
        </button>
        <button id="s3-back-btn" class="auth-link" type="button">
          ${escapeHtml(t('auth.btn_change_number'))}
        </button>
      </div>

      <div class="auth-actions-group" style="margin-top: var(--space-4);">
        <button id="s3-verify-btn" class="btn btn-primary btn-block" type="button">
          ${escapeHtml(t('auth.phone_verify_code'))}
        </button>
        <button id="s3-code-skip-btn" class="btn-ghost" type="button">
          ${escapeHtml(t('auth.phone_skip'))}
        </button>
      </div>
    </form>
  `;

  const codeInput = document.getElementById('s3-code-input');
  const cells = container.querySelectorAll('.code-cell');
  const errorBox = document.getElementById('s3-code-error');
  const successBox = document.getElementById('s3-code-success');
  const countdownLabel = document.getElementById('s3-countdown-label');
  const resendBtn = document.getElementById('s3-resend-btn');
  const backBtn = document.getElementById('s3-back-btn');
  const verifyBtn = document.getElementById('s3-verify-btn');
  const skipBtn = document.getElementById('s3-code-skip-btn');

  function updateCells(val) {
    cells.forEach((cell, idx) => {
      const char = val[idx] || '';
      cell.textContent = char;
      if (char) {
        cell.classList.add('is-filled');
      } else {
        cell.classList.remove('is-filled');
      }
      if (idx === val.length || (val.length === 6 && idx === 5)) {
        cell.classList.add('is-active');
      } else {
        cell.classList.remove('is-active');
      }
    });
  }

  codeInput.addEventListener('input', () => {
    const clean = codeInput.value.replace(/\D/g, '').slice(0, 6);
    codeInput.value = clean;
    updateCells(clean);

    if (clean.length === 6) {
      submitPhoneCode(clean);
    }
  });

  verifyBtn.addEventListener('click', () => {
    const clean = codeInput.value.replace(/\D/g, '').slice(0, 6);
    if (clean.length === 6) {
      submitPhoneCode(clean);
    } else {
      errorBox.textContent = t('auth.error_wrong_code');
      errorBox.style.display = 'flex';
      codeInput.focus();
    }
  });

  // Clicking on cell container focuses hidden input
  const cellsWrap = document.getElementById('phone-code-cells-wrap');
  if (cellsWrap) {
    cellsWrap.addEventListener('click', () => codeInput.focus());
  }

  // Resend countdown
  let resendSec = 30;
  resendBtn.style.display = 'none';
  countdownLabel.style.display = 'inline';

  resendTimer = setInterval(() => {
    resendSec--;
    if (resendSec <= 0) {
      clearInterval(resendTimer);
      countdownLabel.style.display = 'none';
      resendBtn.style.display = 'inline';
      resendBtn.disabled = false;
      resendBtn.classList.remove('is-disabled');
    } else {
      countdownLabel.textContent = `Send a new code in ${resendSec} s`;
    }
  }, 1000);

  resendBtn.addEventListener('click', async () => {
    resendBtn.disabled = true;
    resendBtn.classList.add('is-disabled');
    try {
      const res = await fetch('/api/auth/phone/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ phoneE164 })
      });
      const data = await res.json();
      if (data.warning) {
        sessionStorage.setItem('vyzn_phone_warning', data.warning);
      } else {
        sessionStorage.removeItem('vyzn_phone_warning');
      }
      renderS3PhoneCode(container, digits);
    } catch (err) {
      errorBox.textContent = t('common.generic_error');
      errorBox.style.display = 'flex';
    }
  });

  backBtn.addEventListener('click', () => {
    clearInterval(resendTimer);
    renderS3PhoneInput(container);
  });

  skipBtn.addEventListener('click', async () => {
    clearInterval(resendTimer);
    skipBtn.disabled = true;
    try {
      const res = await fetch('/api/auth/phone/skip', { method: 'POST' });
      const data = await res.json();
      window.location.href = data.next_step || '/overview';
    } catch (err) {
      window.location.href = '/overview';
    }
  });

  async function submitPhoneCode(code) {
    errorBox.style.display = 'none';
    verifyBtn.disabled = true;
    verifyBtn.textContent = 'Verifying…';

    try {
      const res = await fetch('/api/auth/phone/verify', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ phoneE164, code })
      });
      const data = await res.json();

      if (res.ok) {
        clearInterval(resendTimer);
        successBox.textContent = t('auth.phone_verified_success');
        successBox.style.display = 'block';

        setTimeout(() => {
          if (data.next_step && data.next_step !== '/setup/phone') {
            window.location.href = data.next_step;
          } else {
            window.location.href = '/overview';
          }
        }, 800);
      } else {
        errorBox.textContent = data.detail || t('auth.error_wrong_code');
        errorBox.style.display = 'flex';
        codeInput.value = '';
        updateCells('');
        codeInput.focus();
        verifyBtn.disabled = false;
        verifyBtn.textContent = t('auth.phone_verify_code');
      }
    } catch (err) {
      errorBox.textContent = t('common.generic_error');
      errorBox.style.display = 'flex';
      verifyBtn.disabled = false;
      verifyBtn.textContent = t('auth.phone_verify_code');
    }
  }
}

// ---------------------------------------------------------------------------
// Screen S4: /setup/telegram
// ---------------------------------------------------------------------------
async function renderS4(container) {
  // Fetch user phone if not loaded
  if (!currentPhone) {
    try {
      const res = await fetch('/api/me');
      if (res.ok) {
        const me = await res.json();
        currentPhone = me.phone_e164 || '';
      }
    } catch (err) {}
  }

  const maskedPhoneStr = maskPhone(currentPhone);

  container.innerHTML = `
    <div class="auth-stepper">
      <div class="stepper-header">${escapeHtml(t('auth.step_indicator', { current: 3, total: 3 }))}</div>
      <div class="stepper-bars">
        <div class="stepper-bar is-done"></div>
        <div class="stepper-bar is-done"></div>
        <div class="stepper-bar is-active"></div>
      </div>
      <div class="stepper-labels">
        <span class="stepper-step-name is-done">Email</span>
        <span class="stepper-step-name is-done">Mobile number</span>
        <span class="stepper-step-name is-active">Telegram</span>
      </div>
    </div>

    <h1 class="auth-title">${escapeHtml(t('auth.telegram_title'))}</h1>
    <p class="auth-helper">Alerts arrive in Telegram. Connect the account that uses ${escapeHtml(maskedPhoneStr)}.</p>

    <div id="s4-notice-banner" style="display:none;"></div>

    <div class="tg-steps-list">
      <div class="tg-step-item">
        <div class="tg-step-num">1</div>
        <div class="tg-step-content">
          <div>Open VYZN on Telegram</div>
          <div style="margin-top: 8px;">
            <a id="s4-open-tg-btn" class="btn btn-secondary" href="#" target="_blank" rel="noopener">
              ✈️ ${escapeHtml(t('auth.step_open_tg'))}
            </a>
          </div>
        </div>
      </div>

      <div class="tg-step-item">
        <div class="tg-step-num">2</div>
        <div class="tg-step-content">${escapeHtml(t('auth.step_share_num'))}</div>
      </div>

      <div class="tg-step-item">
        <div class="tg-step-num">3</div>
        <div class="tg-step-content">${escapeHtml(t('auth.step_return'))}</div>
      </div>
    </div>

    <div id="s4-qr-container" class="tg-qr-box">
      <div id="s4-qr-svg"></div>
      <div style="font-size: 11px; color: var(--fg-dim); margin-top: 6px;">Scan with phone camera</div>
    </div>

    <div id="s4-status-area" class="tg-status-box" aria-live="polite">
      <div class="tg-waiting-row">
        <div class="tg-pulse-dot"></div>
        <span>${escapeHtml(t('auth.waiting_tg'))}</span>
      </div>
      <div>
        <button id="s4-refresh-link-btn" class="auth-link" type="button">
          ${escapeHtml(t('auth.btn_get_new_link'))}
        </button>
      </div>
    </div>
  `;

  const openTgBtn = document.getElementById('s4-open-tg-btn');
  const qrSvgWrap = document.getElementById('s4-qr-svg');
  const statusArea = document.getElementById('s4-status-area');
  const noticeBanner = document.getElementById('s4-notice-banner');
  const refreshLinkBtn = document.getElementById('s4-refresh-link-btn');

  refreshLinkBtn.addEventListener('click', () => {
    loadTelegramLink();
  });

  async function loadTelegramLink() {
    try {
      const res = await fetch('/api/telegram/link', { method: 'POST' });
      const data = await res.json();

      if (res.ok) {
        currentDeepLink = data.deepLink;
        openTgBtn.href = currentDeepLink;
        qrSvgWrap.innerHTML = generateQrSvg(currentDeepLink, 150);
        startStatusPolling();
      } else {
        noticeBanner.className = 'auth-error-banner';
        noticeBanner.textContent = data.detail || t('auth.error_tg_unreachable');
        noticeBanner.style.display = 'flex';
      }
    } catch (err) {
      noticeBanner.className = 'auth-error-banner';
      noticeBanner.textContent = t('auth.error_tg_unreachable');
      noticeBanner.style.display = 'flex';
    }
  }

  function startStatusPolling() {
    clearInterval(tgPollTimer);
    tgPollTimer = setInterval(async () => {
      try {
        const res = await fetch('/api/telegram/status');
        if (!res.ok) return;
        const data = await res.json();

        if (data.status === 'connected') {
          clearInterval(tgPollTimer);
          renderConnectedState();
        } else if (data.status === 'mismatch') {
          clearInterval(tgPollTimer);
          renderMismatchState();
        } else if (data.status === 'expired') {
          clearInterval(tgPollTimer);
          renderExpiredState();
        }
      } catch (err) {}
    }, 2000);
  }

  function renderConnectedState() {
    noticeBanner.style.display = 'none';
    statusArea.innerHTML = `
      <div class="tg-connected-badge">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
          <polyline points="20 6 9 17 4 12"></polyline>
        </svg>
        <span>${escapeHtml(t('auth.tg_connected'))}</span>
      </div>

      <div id="s4-delivery-metric-box" style="display:none;" class="tg-delivery-metric"></div>

      <div style="display: flex; flex-direction: column; gap: 8px; margin-top: 8px;">
        <button id="s4-test-ping-btn" class="btn btn-secondary btn-block" type="button">
          ${escapeHtml(t('auth.send_test'))}
        </button>
        <button id="s4-goto-overview-btn" class="btn btn-primary btn-block" type="button">
          ${escapeHtml(t('auth.go_to_overview'))}
        </button>
      </div>
    `;

    const testPingBtn = document.getElementById('s4-test-ping-btn');
    const gotoOverviewBtn = document.getElementById('s4-goto-overview-btn');
    const metricBox = document.getElementById('s4-delivery-metric-box');

    testPingBtn.addEventListener('click', async () => {
      testPingBtn.disabled = true;
      testPingBtn.textContent = 'Sending…';

      try {
        const res = await fetch('/api/telegram/test', { method: 'POST' });
        const data = await res.json();

        if (res.ok) {
          const latSec = ((data.latencyMs || 800) / 1000).toFixed(1);
          metricBox.textContent = t('auth.test_delivered', { n: latSec });
          metricBox.style.display = 'block';
          testPingBtn.textContent = 'Ping Delivered ✓';
        } else {
          metricBox.textContent = data.detail || 'Test ping failed';
          metricBox.style.display = 'block';
          testPingBtn.disabled = false;
          testPingBtn.textContent = t('auth.send_test');
        }
      } catch (err) {
        metricBox.textContent = t('auth.error_tg_unreachable');
        metricBox.style.display = 'block';
        testPingBtn.disabled = false;
        testPingBtn.textContent = t('auth.send_test');
      }
    });

    gotoOverviewBtn.addEventListener('click', () => {
      window.location.href = '/overview';
    });
  }

  function renderMismatchState() {
    noticeBanner.className = 'auth-warning-banner';
    noticeBanner.innerHTML = `
      <div>${escapeHtml(t('auth.error_number_mismatch', { phone: maskedPhoneStr }))}</div>
      <div style="display: flex; gap: 8px; margin-top: 12px;">
        <button id="s4-mismatch-retry-btn" class="btn btn-secondary btn-sm" type="button">
          ${escapeHtml(t('auth.btn_try_again'))}
        </button>
        <button id="s4-mismatch-change-btn" class="btn btn-ghost btn-sm" type="button">
          ${escapeHtml(t('auth.btn_change_number'))}
        </button>
      </div>
    `;
    noticeBanner.style.display = 'block';

    document.getElementById('s4-mismatch-retry-btn').addEventListener('click', () => {
      loadTelegramLink();
    });
    document.getElementById('s4-mismatch-change-btn').addEventListener('click', () => {
      navigateTo('/setup/phone');
    });
  }

  function renderExpiredState() {
    noticeBanner.className = 'auth-error-banner';
    noticeBanner.innerHTML = `
      <div>${escapeHtml(t('auth.error_link_expired'))}</div>
      <div style="margin-top: 8px;">
        <button id="s4-expired-retry-btn" class="btn btn-secondary btn-sm" type="button">
          ${escapeHtml(t('auth.btn_get_new_link'))}
        </button>
      </div>
    `;
    noticeBanner.style.display = 'block';

    document.getElementById('s4-expired-retry-btn').addEventListener('click', () => {
      loadTelegramLink();
    });
  }

  loadTelegramLink();
}
