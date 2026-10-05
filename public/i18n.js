/**
 * VYZN Internationalization (i18n) Engine
 * Self-contained, lightweight interpolation with English default.
 */

let currentLocale = 'en';
let dictionaries = {};

/**
 * Initializes i18n with a locale dictionary.
 * @param {string} [locale='en']
 * @param {object} [data=null]
 */
export async function initI18n(locale = 'en', data = null) {
  currentLocale = locale;
  if (data) {
    dictionaries[locale] = data;
    return;
  }

  try {
    const res = await fetch(`/static/locales/${locale}.json`);
    if (res.ok) {
      dictionaries[locale] = await res.json();
    } else {
      console.warn(`[VYZN i18n] Failed to load /static/locales/${locale}.json, status: ${res.status}`);
    }
  } catch (err) {
    console.error(`[VYZN i18n] Error loading locale ${locale}:`, err);
  }
}

/**
 * Translates a key path using dot notation and interpolates {param} values.
 * @param {string} keyPath - e.g. "overview.flags_title", "status.all_online"
 * @param {object} [params={}] - key-value pairs for substitution
 * @returns {string} Translated string or the keyPath fallback
 */
export function t(keyPath, fallbackOrParams = {}, maybeParams = {}) {
  let fallback = null;
  let params = {};

  if (typeof fallbackOrParams === 'string') {
    fallback = fallbackOrParams;
    params = (maybeParams && typeof maybeParams === 'object') ? maybeParams : {};
  } else if (fallbackOrParams && typeof fallbackOrParams === 'object') {
    params = fallbackOrParams;
  }

  const dict = dictionaries[currentLocale] || dictionaries['en'] || {};
  const parts = keyPath.split('.');
  let val = dict;

  for (const part of parts) {
    if (val && typeof val === 'object' && part in val) {
      val = val[part];
    } else {
      val = null;
      break;
    }
  }

  if (typeof val !== 'string') {
    return fallback !== null ? fallback : keyPath;
  }

  // Parameter replacement: {name}, {count}, etc.
  return val.replace(/\{(\w+)\}/g, (match, p1) => {
    return (params && typeof params === 'object' && p1 in params) ? String(params[p1]) : match;
  });
}
