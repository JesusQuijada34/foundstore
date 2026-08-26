(function () {
  'use strict';
  function setLocale(value) {
    if (!value || value === 'auto') {
      document.cookie = 'foundstore_locale=; Max-Age=0; Path=/; SameSite=Lax';
      return;
    }
    document.cookie = 'foundstore_locale=' + encodeURIComponent(value) + '; Max-Age=31536000; Path=/; SameSite=Lax';
    var url = new URL(window.location.href);
    url.searchParams.set('lang', value);
    window.location.assign(url.toString());
  }
  document.addEventListener('change', function (event) {
    if (event.target && event.target.matches('select[data-language-selector]')) setLocale(event.target.value);
  });
  document.querySelectorAll('select[data-language-selector]').forEach(function (select) {
    var match = document.cookie.match(/(?:^|; )foundstore_locale=([^;]*)/);
    var value = match ? decodeURIComponent(match[1]) : document.documentElement.lang;
    if (value && select.querySelector('option[value="' + CSS.escape(value) + '"]')) select.value = value;
  });
}());
