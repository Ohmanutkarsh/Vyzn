import { escapeHtml } from '../utils.js';

/**
 * Renders a standardized button string or DOM element.
 * @param {object} props
 * @param {string} props.label
 * @param {'primary'|'secondary'|'quiet'|'danger'} [props.variant='primary']
 * @param {boolean} [props.disabled=false]
 * @param {string} [props.icon='']
 * @param {string} [props.id='']
 * @param {string} [props.className='']
 * @returns {string} HTML string
 */
export function renderButton({ label, variant = 'primary', disabled = false, icon = '', id = '', className = '' }) {
  const idAttr = id ? `id="${escapeHtml(id)}"` : '';
  const disabledAttr = disabled ? 'disabled' : '';
  const iconHtml = icon ? `<span class="btn-icon">${icon}</span>` : '';
  
  return `
    <button type="button" class="btn btn-${escapeHtml(variant)} ${escapeHtml(className)}" ${idAttr} ${disabledAttr}>
      ${iconHtml}
      <span>${escapeHtml(label)}</span>
    </button>
  `.trim();
}
