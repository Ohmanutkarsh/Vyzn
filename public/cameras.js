import { initShell, promptSecurityPin } from './components/shell.js';
import { renderCameraTile } from './components/camera-tile.js';
import { t, initI18n } from './i18n.js';
import { escapeHtml } from './utils.js';

let camerasList = [];
let pendingRemoveId = null;
let pendingRenameId = null;

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

document.addEventListener('DOMContentLoaded', async () => {
  await initI18n();
  initShell({ activePage: 'cameras' });

  // Set page title
  const titleEl = document.getElementById('page-title-text');
  if (titleEl) titleEl.textContent = t('cameras.page_title', 'Cameras');

  await loadCameras();
  attachEventListeners();

  // Snapshot refresh every 8 seconds per spec
  setInterval(refreshSnapshots, 8000);
});

async function loadCameras() {
  const grid = document.getElementById('cameras-grid');
  const countEl = document.getElementById('txt-cameras-count');

  try {
    await checkEdgeServer();
    const res = await fetch('/api/cameras', { credentials: 'include' });
    if (!res.ok) throw new Error('Failed to load cameras');
    camerasList = await res.json();

    if (edgeBaseUrl) {
      camerasList.forEach(c => {
        const cid = c.id || c.camera_id;
        c.snapshot_url = `${edgeBaseUrl}/api/cameras/${cid}/snapshot.jpg?t=${Date.now()}`;
      });
    } else {
      camerasList.forEach(c => {
        const cid = c.id || c.camera_id;
        c.snapshot_url = `/api/cameras/${cid}/snapshot.jpg?t=${Date.now()}`;
      });
    }

    if (countEl) {
      const count = camerasList.length;
      countEl.textContent = count === 1 ? '1 camera configured' : `${count} cameras configured`;
    }

    if (!camerasList || camerasList.length === 0) {
      grid.innerHTML = `
        <div class="empty-state" style="grid-column: 1 / -1; width: 100%;">
          <div style="font-size: 32px;">📹</div>
          <div style="font-size: 16px; font-weight: 600; color: var(--text-1);">${escapeHtml(t('overview.add_first_camera', 'Add your first camera'))}</div>
          <p class="empty-state-text">${escapeHtml(t('overview.add_first_camera_sub', 'Connect a CCTV camera, a recorder, or a spare phone.'))}</p>
          <a href="/cameras/new" class="btn btn-primary" style="text-decoration: none;">${escapeHtml(t('overview.add_camera_btn', 'Add a camera'))}</a>
        </div>
      `;
      return;
    }

    grid.innerHTML = camerasList.map(c => renderCameraTile({ camera: c, showActions: true })).join('');
    attachTileActions();
  } catch (err) {
    if (grid) {
      grid.innerHTML = `<div class="empty-state" style="grid-column: 1 / -1;"><p class="empty-state-text">Failed to load cameras. Please refresh.</p></div>`;
    }
  }
}

function attachTileActions() {
  // Menu trigger toggle
  document.querySelectorAll('.btn-menu-trigger').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const camId = btn.getAttribute('data-cam-id');
      const menu = document.getElementById(`menu-${camId}`);
      if (!menu) return;

      const isShown = menu.style.display === 'block';
      closeAllMenus();
      if (!isShown) menu.style.display = 'block';
    });
  });

  // Rename Action
  document.querySelectorAll('.action-rename').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      closeAllMenus();
      pendingRenameId = btn.getAttribute('data-cam-id');
      const currentName = btn.getAttribute('data-cam-name') || '';
      openRenameModal(pendingRenameId, currentName);
    });
  });

  // Remove Action
  document.querySelectorAll('.action-remove').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      closeAllMenus();
      pendingRemoveId = btn.getAttribute('data-cam-id');
      const currentName = btn.getAttribute('data-cam-name') || 'this camera';
      openRemoveModal(pendingRemoveId, currentName);
    });
  });
}

function closeAllMenus() {
  document.querySelectorAll('.camera-menu-dropdown').forEach(m => m.style.display = 'none');
}

function openRemoveModal(camId, camName) {
  pendingRemoveId = camId;
  const modal = document.getElementById('modal-remove');
  const title = document.getElementById('modal-remove-title');
  const body = document.getElementById('modal-remove-body');

  if (title) title.textContent = t('cameras.remove_confirm_title', `Remove ${camName}?`, { name: camName });
  if (body) body.textContent = t('cameras.remove_confirm_body', 'Its saved footage and clips will be deleted now.');
  if (modal) modal.style.display = 'flex';
}

function closeRemoveModal() {
  const modal = document.getElementById('modal-remove');
  if (modal) modal.style.display = 'none';
  pendingRemoveId = null;
}

function openRenameModal(camId, currentName) {
  const modal = document.getElementById('modal-rename');
  const input = document.getElementById('input-rename-name');
  if (input) input.value = currentName;
  if (modal) modal.style.display = 'flex';
  if (input) input.focus();
}

function closeRenameModal() {
  const modal = document.getElementById('modal-rename');
  if (modal) modal.style.display = 'none';
  pendingRenameId = null;
}

function attachEventListeners() {
  document.addEventListener('click', () => closeAllMenus());

  // Cancel Remove
  const btnCancelRemove = document.getElementById('btn-cancel-remove');
  if (btnCancelRemove) btnCancelRemove.addEventListener('click', closeRemoveModal);

  // Confirm Remove
  const btnConfirmRemove = document.getElementById('btn-confirm-remove');
  if (btnConfirmRemove) {
    btnConfirmRemove.addEventListener('click', async () => {
      if (!pendingRemoveId) return;
      const targetId = pendingRemoveId;
      closeRemoveModal();

      const pin = await promptSecurityPin({
        title: 'Delete Camera',
        description: 'Permanently remove this camera from edge surveillance. This operation requires your 6-digit Security PIN.',
        confirmText: 'Delete Camera',
        isDanger: true
      });
      if (!pin) return;

      try {
        const res = await fetch(`/api/cameras/${encodeURIComponent(targetId)}`, {
          method: 'DELETE',
          credentials: 'include',
          headers: {
            'X-Security-Pin': pin
          }
        });
        if (edgeBaseUrl) {
          fetch(`${edgeBaseUrl}/api/cameras/${encodeURIComponent(targetId)}`, {
            method: 'DELETE',
            headers: {
              'X-Security-Pin': pin
            }
          }).catch(() => {});
        }
        if (res.ok) {
          await loadCameras();
        } else {
          const errData = await res.json().catch(() => ({}));
          alert(errData.detail || 'Failed to remove camera. Check Security PIN.');
        }
      } catch (err) {
        alert('Failed to remove camera');
      }
    });
  }

  // Cancel Rename
  const btnCancelRename = document.getElementById('btn-cancel-rename');
  if (btnCancelRename) btnCancelRename.addEventListener('click', closeRenameModal);

  // Confirm Rename
  const btnConfirmRename = document.getElementById('btn-confirm-rename');
  if (btnConfirmRename) {
    btnConfirmRename.addEventListener('click', async () => {
      if (!pendingRenameId) return;
      const input = document.getElementById('input-rename-name');
      const newName = input ? input.value.trim() : '';
      if (!newName) return;

      btnConfirmRename.disabled = true;
      try {
        const res = await fetch(`/api/cameras/${encodeURIComponent(pendingRenameId)}`, {
          method: 'PATCH',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name: newName })
        });
        if (res.ok) {
          closeRenameModal();
          await loadCameras();
        }
      } catch (err) {
        alert('Failed to rename camera');
      } finally {
        btnConfirmRename.disabled = false;
      }
    });
  }
}

function refreshSnapshots() {
  const images = document.querySelectorAll('.camera-thumb-img');
  const now = Date.now();
  images.forEach(img => {
    const tile = img.closest('.camera-tile');
    const cid = tile ? tile.getAttribute('data-camera-id') : null;
    if (cid && edgeBaseUrl) {
      img.src = `${edgeBaseUrl}/api/cameras/${cid}/snapshot.jpg?t=${now}`;
    } else {
      const currentSrc = img.src.split('?')[0];
      if (currentSrc && !currentSrc.startsWith('data:')) {
        img.src = `${currentSrc}?t=${now}`;
      }
    }
  });
}
