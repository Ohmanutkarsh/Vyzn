/**
 * Clips Archive Controller (Section 6.3)
 * URL-synced multi-dimensional filtering, responsive ClipCard grid,
 * desktop hover preview, and deep-link drawer opening.
 */

import { initShell } from './components/shell.js';
import { renderClipCard } from './components/clip-card.js';
import { openClipDrawer, initClipDrawer } from './components/clip-drawer.js';
import { t, initI18n } from './i18n.js';
import { escapeHtml } from './utils.js';

let loadedClips = [];
let allCameras = [];

const currentFilters = {
  camera: 'all',
  tier: 'all',
  status: 'unreviewed',
  object: 'all',
  when: 'last_72h'
};

document.addEventListener('DOMContentLoaded', async () => {
  await initI18n();
  initShell({ activePage: 'clips' });
  initClipDrawer({ onClipUpdated: () => loadClips() });

  const titleEl = document.getElementById('page-title-text');
  if (titleEl) titleEl.textContent = 'Clips';

  await loadCamerasList();
  readFiltersFromUrl();
  bindFilterEvents();
  await loadClips();

  // Check if deep link opened specific clip: /clips/:id
  checkDeepLink();
});

/**
 * Loads cameras to populate the filter dropdowns.
 */
async function loadCamerasList() {
  try {
    const res = await fetch('/api/cameras');
    if (res.ok) {
      allCameras = await res.json();
      populateCameraDropdowns();
    }
  } catch (e) {
    console.error('Error loading cameras list:', e);
  }
}

function populateCameraDropdowns() {
  const desktopSelect = document.getElementById('filter-camera');
  const mobileSelect = document.getElementById('m-filter-camera');

  const optionsHtml = ['<option value="all">All</option>']
    .concat(allCameras.map(c => `<option value="${escapeHtml(c.id || c.camera_id)}">${escapeHtml(c.name)}</option>`))
    .join('');

  if (desktopSelect) desktopSelect.innerHTML = optionsHtml;
  if (mobileSelect) mobileSelect.innerHTML = optionsHtml;
}

/**
 * Reads initial filter state from URL search params.
 */
function readFiltersFromUrl() {
  const params = new URLSearchParams(window.location.search);
  if (params.has('camera')) currentFilters.camera = params.get('camera');
  if (params.has('tier')) currentFilters.tier = params.get('tier');
  if (params.has('status')) currentFilters.status = params.get('status');
  if (params.has('object')) currentFilters.object = params.get('object');
  if (params.has('when')) currentFilters.when = params.get('when');

  syncUiWithFilterState();
}

/**
 * Synchronizes DOM form controls with the current filter state.
 */
function syncUiWithFilterState() {
  // Desktop controls
  const camSel = document.getElementById('filter-camera');
  if (camSel) camSel.value = currentFilters.camera;

  const impGroup = document.getElementById('filter-importance-group');
  if (impGroup) {
    impGroup.querySelectorAll('.filter-seg-btn').forEach(btn => {
      btn.classList.toggle('is-active', btn.getAttribute('data-val') === currentFilters.tier);
    });
  }

  const statusSel = document.getElementById('filter-status');
  if (statusSel) statusSel.value = currentFilters.status;

  const whatSel = document.getElementById('filter-what');
  if (whatSel) whatSel.value = currentFilters.object;

  const whenSel = document.getElementById('filter-when');
  if (whenSel) whenSel.value = currentFilters.when;

  // Mobile sheet controls
  const mCam = document.getElementById('m-filter-camera');
  if (mCam) mCam.value = currentFilters.camera;

  const mImp = document.getElementById('m-filter-importance');
  if (mImp) {
    mImp.querySelectorAll('.segmented-option').forEach(btn => {
      btn.classList.toggle('is-selected', btn.getAttribute('data-val') === currentFilters.tier);
    });
  }

  const mStat = document.getElementById('m-filter-status');
  if (mStat) mStat.value = currentFilters.status;

  const mWhat = document.getElementById('m-filter-what');
  if (mWhat) mWhat.value = currentFilters.object;

  const mWhen = document.getElementById('m-filter-when');
  if (mWhen) mWhen.value = currentFilters.when;

  // Badge count for mobile
  let activeCount = 0;
  if (currentFilters.camera !== 'all') activeCount++;
  if (currentFilters.tier !== 'all') activeCount++;
  if (currentFilters.status !== 'unreviewed') activeCount++;
  if (currentFilters.object !== 'all') activeCount++;
  if (currentFilters.when !== 'last_72h') activeCount++;

  const badge = document.getElementById('mobile-filter-count-badge');
  if (badge) {
    if (activeCount > 0) {
      badge.style.display = 'inline-block';
      badge.textContent = activeCount;
    } else {
      badge.style.display = 'none';
    }
  }
}

/**
 * Pushes filter state to URL query string.
 */
function pushFiltersToUrl() {
  const params = new URLSearchParams();
  if (currentFilters.camera !== 'all') params.set('camera', currentFilters.camera);
  if (currentFilters.tier !== 'all') params.set('tier', currentFilters.tier);
  if (currentFilters.status !== 'unreviewed') params.set('status', currentFilters.status);
  if (currentFilters.object !== 'all') params.set('object', currentFilters.object);
  if (currentFilters.when !== 'last_72h') params.set('when', currentFilters.when);

  const qs = params.toString();
  const newUrl = qs ? `${window.location.pathname}?${qs}` : window.location.pathname;
  history.replaceState(null, '', newUrl);
}

/**
 * Binds UI change events to filter controls.
 */
function bindFilterEvents() {
  const camSel = document.getElementById('filter-camera');
  const impGroup = document.getElementById('filter-importance-group');
  const statusSel = document.getElementById('filter-status');
  const whatSel = document.getElementById('filter-what');
  const whenSel = document.getElementById('filter-when');
  const clearBtn = document.getElementById('btn-clear-filters');
  const emptyClearBtn = document.getElementById('btn-empty-clear-filters');

  // Desktop events
  if (camSel) camSel.addEventListener('change', () => {
    currentFilters.camera = camSel.value;
    onFiltersChanged();
  });

  if (impGroup) {
    impGroup.querySelectorAll('.filter-seg-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        currentFilters.tier = btn.getAttribute('data-val');
        onFiltersChanged();
      });
    });
  }

  if (statusSel) statusSel.addEventListener('change', () => {
    currentFilters.status = statusSel.value;
    onFiltersChanged();
  });

  if (whatSel) whatSel.addEventListener('change', () => {
    currentFilters.object = whatSel.value;
    onFiltersChanged();
  });

  if (whenSel) whenSel.addEventListener('change', () => {
    currentFilters.when = whenSel.value;
    onFiltersChanged();
  });

  if (clearBtn) clearBtn.addEventListener('click', resetFilters);
  if (emptyClearBtn) emptyClearBtn.addEventListener('click', resetFilters);

  // Mobile modal events
  const mobileModal = document.getElementById('modal-mobile-filters');
  const openMobileBtn = document.getElementById('btn-open-mobile-filters');
  const closeMobileBtn = document.getElementById('btn-close-mobile-filters');
  const applyMobileBtn = document.getElementById('m-btn-apply-filters');
  const clearMobileBtn = document.getElementById('m-btn-clear-filters');

  if (openMobileBtn) openMobileBtn.addEventListener('click', () => {
    mobileModal.style.display = 'flex';
  });

  if (closeMobileBtn) closeMobileBtn.addEventListener('click', () => {
    mobileModal.style.display = 'none';
  });

  const mImp = document.getElementById('m-filter-importance');
  if (mImp) {
    mImp.querySelectorAll('.segmented-option').forEach(btn => {
      btn.addEventListener('click', () => {
        mImp.querySelectorAll('.segmented-option').forEach(b => b.classList.remove('is-selected'));
        btn.classList.add('is-selected');
      });
    });
  }

  if (applyMobileBtn) applyMobileBtn.addEventListener('click', () => {
    currentFilters.camera = document.getElementById('m-filter-camera').value;
    const selectedImp = mImp ? mImp.querySelector('.segmented-option.is-selected') : null;
    currentFilters.tier = selectedImp ? selectedImp.getAttribute('data-val') : 'all';
    currentFilters.status = document.getElementById('m-filter-status').value;
    currentFilters.object = document.getElementById('m-filter-what').value;
    currentFilters.when = document.getElementById('m-filter-when').value;

    mobileModal.style.display = 'none';
    onFiltersChanged();
  });

  if (clearMobileBtn) clearMobileBtn.addEventListener('click', () => {
    mobileModal.style.display = 'none';
    resetFilters();
  });
}

function resetFilters() {
  currentFilters.camera = 'all';
  currentFilters.tier = 'all';
  currentFilters.status = 'all';
  currentFilters.object = 'all';
  currentFilters.when = 'last_72h';
  onFiltersChanged();
}

function onFiltersChanged() {
  syncUiWithFilterState();
  pushFiltersToUrl();
  loadClips();
}

/**
 * Loads clips matching active filters from /api/clips.
 */
async function loadClips() {
  const grid = document.getElementById('clips-grid');
  const zeroEmpty = document.getElementById('clips-zero-empty');
  const noMatchEmpty = document.getElementById('clips-no-match-empty');
  const summaryBadge = document.getElementById('clips-summary-badge');

  if (!grid) return;

  // Build query string
  const params = new URLSearchParams();
  if (currentFilters.camera !== 'all') params.set('camera', currentFilters.camera);
  if (currentFilters.tier !== 'all') params.set('tier', currentFilters.tier);
  if (currentFilters.status !== 'all') params.set('status', currentFilters.status);
  if (currentFilters.object !== 'all') params.set('object', currentFilters.object);

  const now = Date.now();
  if (currentFilters.when === 'last_6h') {
    params.set('from', now - 6 * 3600 * 1000);
  } else if (currentFilters.when === 'last_24h') {
    params.set('from', now - 24 * 3600 * 1000);
  } else if (currentFilters.when === 'all') {
    // Show all available clips without from boundary
  } else {
    // 72 hours standard retention
    params.set('from', now - 72 * 3600 * 1000);
  }

  try {
    const res = await fetch(`/api/clips?${params.toString()}`, { credentials: 'include' });
    if (!res.ok) throw new Error('Failed to load clips');
    const data = await res.json();
    loadedClips = data.clips || [];
    const total = data.total !== undefined ? data.total : loadedClips.length;

    if (summaryBadge) {
      summaryBadge.textContent = t('clips.summary', { count: total }, `${total} clips in the last 72 h`);
    }

    if (loadedClips.length === 0) {
      grid.style.display = 'none';
      const isFiltered = currentFilters.camera !== 'all' || currentFilters.tier !== 'all' ||
                         currentFilters.status !== 'all' || currentFilters.object !== 'all' ||
                         currentFilters.when !== 'last_72h';

      if (isFiltered) {
        if (noMatchEmpty) noMatchEmpty.style.display = 'flex';
        if (zeroEmpty) zeroEmpty.style.display = 'none';
      } else {
        if (zeroEmpty) zeroEmpty.style.display = 'flex';
        if (noMatchEmpty) noMatchEmpty.style.display = 'none';
      }
      return;
    }

    if (zeroEmpty) zeroEmpty.style.display = 'none';
    if (noMatchEmpty) noMatchEmpty.style.display = 'none';
    grid.style.display = 'grid';

    grid.innerHTML = loadedClips.map(clip => renderClipCard({ clip })).join('');

    // Attach card click handlers to open drawer
    grid.querySelectorAll('.clip-card').forEach(card => {
      const cid = card.getAttribute('data-clip-id');
      const clip = loadedClips.find(c => c.id === cid);

      card.addEventListener('click', () => {
        if (clip) openClipDrawer(clip, loadedClips);
      });
      card.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          if (clip) openClipDrawer(clip, loadedClips);
        }
      });
    });
  } catch (e) {
    console.error('Error fetching clips:', e);
  }
}

/**
 * Checks if current page URL specifies a clip to open directly.
 */
function checkDeepLink() {
  const path = window.location.pathname;
  if (path.startsWith('/clips/')) {
    const clipId = decodeURIComponent(path.replace('/clips/', '').trim());
    if (clipId) {
      openClipDrawer(clipId, loadedClips);
      return;
    }
  }

  const params = new URLSearchParams(window.location.search);
  if (params.has('open')) {
    openClipDrawer(params.get('open'), loadedClips);
  }
}
