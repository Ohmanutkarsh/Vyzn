import { initShell } from './components/shell.js';
import { escapeHtml } from './utils.js';

document.addEventListener('DOMContentLoaded', async () => {
  initShell({ activePage: 'settings' });

  const titleEl = document.getElementById('page-title-text');
  if (titleEl) titleEl.textContent = 'Admin Billing';

  const btnRefresh = document.getElementById('btn-refresh-orders');
  if (btnRefresh) {
    btnRefresh.addEventListener('click', loadPendingOrders);
  }

  await loadPendingOrders();
});

function showToast(message, isError = false) {
  const toast = document.getElementById('toast-notification');
  if (!toast) return;
  toast.textContent = message;
  toast.style.borderColor = isError ? '#ef4444' : '#10b981';
  toast.style.color = isError ? '#ef4444' : '#f4f4f5';
  toast.style.display = 'block';
  setTimeout(() => {
    toast.style.display = 'none';
  }, 4000);
}

async function loadPendingOrders() {
  const tbody = document.getElementById('tbody-pending-orders');
  const badge = document.getElementById('badge-pending-count');
  if (!tbody) return;

  try {
    let res = await fetch('/admin/billing/pending', { credentials: 'include' });
    if (!res.ok && res.status === 404) {
      res = await fetch('/api/admin/billing/pending', { credentials: 'include' });
    }

    if (res.status === 403) {
      tbody.innerHTML = `
        <tr>
          <td colspan="7" style="padding: 32px; text-align: center; color: #ef4444;">
            🚫 Access Denied: You do not have administrator permissions to verify billing orders.
          </td>
        </tr>
      `;
      if (badge) {
        badge.textContent = 'Restricted';
        badge.className = 'admin-badge';
      }
      return;
    }

    if (!res.ok) {
      throw new Error('Failed to load pending orders.');
    }

    const orders = await res.json();
    if (badge) {
      badge.textContent = `${orders.length} Pending`;
      badge.className = orders.length > 0 ? 'admin-badge pending' : 'admin-badge success';
    }

    if (!orders || orders.length === 0) {
      tbody.innerHTML = `
        <tr>
          <td colspan="7" style="padding: 36px 12px; text-align: center; color: var(--text-3, #71717a);">
            ✓ All clear! No pending UPI payments awaiting verification.
          </td>
        </tr>
      `;
      return;
    }

    tbody.innerHTML = orders.map(ord => {
      const amountRs = (ord.amount_paise / 100).toFixed(2);
      const timeStr = ord.submitted_at ? new Date(ord.submitted_at).toLocaleString() : (ord.created_at ? new Date(ord.created_at).toLocaleString() : '—');
      const utrStr = ord.utr ? `<strong style="font-family: monospace; letter-spacing: 0.05em; color: #60a5fa;">${escapeHtml(ord.utr)}</strong>` : '<span style="color: #71717a;">Not submitted</span>';

      return `
        <tr id="row-${ord.id}">
          <td style="font-weight: 700; font-family: monospace; color: #ffffff;">${escapeHtml(ord.order_code)}</td>
          <td style="color: var(--text-2, #a1a1aa); font-size: 12px;">${escapeHtml(ord.tenant_id)}</td>
          <td style="font-weight: 600; color: #ffffff;">+${ord.quantity} camera${ord.quantity > 1 ? 's' : ''}</td>
          <td style="font-weight: 700; color: #10b981;">₹${amountRs}</td>
          <td>${utrStr}</td>
          <td style="font-size: 12px; color: var(--text-2, #a1a1aa);">${timeStr}</td>
          <td style="text-align: right; white-space: nowrap;">
            <div style="display: inline-flex; gap: 8px;">
              <button type="button" class="btn-approve" data-id="${ord.id}" data-code="${ord.order_code}" data-qty="${ord.quantity}">
                ✓ Approve
              </button>
              <button type="button" class="btn-reject" data-id="${ord.id}" data-code="${ord.order_code}">
                Reject
              </button>
            </div>
          </td>
        </tr>
      `;
    }).join('');

    // Attach Approve handlers
    tbody.querySelectorAll('.btn-approve').forEach(btn => {
      btn.addEventListener('click', async () => {
        const orderId = btn.getAttribute('data-id');
        const orderCode = btn.getAttribute('data-code');
        const qty = btn.getAttribute('data-qty');

        btn.disabled = true;
        btn.textContent = 'Approving…';

        try {
          let res = await fetch(`/admin/billing/orders/${orderId}/approve`, {
            method: 'POST',
            credentials: 'include'
          });
          if (!res.ok && res.status === 404) {
            res = await fetch(`/api/admin/billing/orders/${orderId}/approve`, {
              method: 'POST',
              credentials: 'include'
            });
          }

          const data = await res.json().catch(() => ({}));
          if (!res.ok) {
            throw new Error(data.detail || 'Approval failed.');
          }

          showToast(`✓ Order ${orderCode} approved. Added ${qty} camera(s) to quota!`);
          await loadPendingOrders();
        } catch (err) {
          showToast(err.message, true);
          btn.disabled = false;
          btn.textContent = '✓ Approve';
        }
      });
    });

    // Attach Reject handlers
    tbody.querySelectorAll('.btn-reject').forEach(btn => {
      btn.addEventListener('click', async () => {
        const orderId = btn.getAttribute('data-id');
        const orderCode = btn.getAttribute('data-code');

        const reason = window.prompt(`Enter reason for declining order ${orderCode}:`, 'UTR not found in bank statement');
        if (reason === null) return; // user cancelled prompt

        btn.disabled = true;
        btn.textContent = 'Rejecting…';

        try {
          let res = await fetch(`/admin/billing/orders/${orderId}/reject`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include',
            body: JSON.stringify({ reason: reason.trim() || 'Payment verification declined' })
          });
          if (!res.ok && res.status === 404) {
            res = await fetch(`/api/admin/billing/orders/${orderId}/reject`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              credentials: 'include',
              body: JSON.stringify({ reason: reason.trim() || 'Payment verification declined' })
            });
          }


          const data = await res.json().catch(() => ({}));
          if (!res.ok) {
            throw new Error(data.detail || 'Rejection failed.');
          }

          showToast(`Order ${orderCode} declined.`);
          await loadPendingOrders();
        } catch (err) {
          showToast(err.message, true);
          btn.disabled = false;
          btn.textContent = 'Reject';
        }
      });
    });

  } catch (err) {
    tbody.innerHTML = `
      <tr>
        <td colspan="7" style="padding: 24px; text-align: center; color: #ef4444;">
          Error loading pending orders: ${escapeHtml(err.message)}
        </td>
      </tr>
    `;
  }
}
