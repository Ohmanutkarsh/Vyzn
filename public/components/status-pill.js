import { escapeHtml } from '../utils.js';

/**
 * Renders the top-level status pill with dot and text.
 * @param {object} props
 * @param {'neutral'|'amber'|'red'|'green'} [props.type='neutral']
 * @param {string} props.text
 * @param {string} [props.icon='']
 * @returns {string} HTML string
 */
export function renderStatusPill({ type = 'neutral', text, icon = '' }) {
  const iconHtml = icon ? `<span class="pill-icon">${icon}</span>` : `<span class="status-dot ${type}"></span>`;
  return `
    <div class="status-pill" role="status">
      ${iconHtml}
      <span>${escapeHtml(text)}</span>
    </div>
  `.trim();
}
