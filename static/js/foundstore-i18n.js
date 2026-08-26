(() => {
  'use strict';
  const COOKIE = 'foundstore_locale';
  const YEAR = 60 * 60 * 24 * 365;
  const normalize = value => {
    if (!value) return null;
    const raw = String(value).replace('_', '-').trim();
    const exact = [...document.querySelectorAll('select[data-language-selector] option')].find(o => o.value.toLowerCase() === raw.toLowerCase());
    if (exact) return exact.value;
    const base = raw.split('-')[0].toLowerCase();
    return [...document.querySelectorAll('select[data-language-selector] option')].find(o => o.value.toLowerCase() === base)?.value || null;
  };
  const setCookie = (value, maxAge) => { document.cookie = `${COOKIE}=${value ? encodeURIComponent(value) : ''}; Max-Age=${maxAge}; Path=/; SameSite=Lax`; };
  const changeLocale = value => {
    const url = new URL(window.location.href);
    if (!value || value === 'auto') {
      setCookie('', 0);
      url.searchParams.delete('lang');
    } else {
      const locale = normalize(value) || 'es';
      setCookie(locale, YEAR);
      url.searchParams.set('lang', locale);
    }
    window.location.assign(url.toString());
  };
  const cookieValue = () => {
    const match = document.cookie.match(new RegExp(`(?:^|; )${COOKIE}=([^;]*)`));
    return match ? decodeURIComponent(match[1]) : null;
  };
  document.addEventListener('change', event => {
    if (event.target?.matches('select[data-language-selector]')) changeLocale(event.target.value);
  });
  const explicit = new URL(window.location.href).searchParams.get('lang');
  const selected = normalize(explicit) || normalize(cookieValue());
  document.querySelectorAll('select[data-language-selector]').forEach(select => {
    const option = selected ? [...select.options].find(item => item.value === selected) : select.querySelector('option[value="auto"]');
    if (option) select.value = option.value;
  });
})();
