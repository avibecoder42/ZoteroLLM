// Farbschema vor dem ersten Zeichnen setzen (kein helles Aufblitzen im dunklen Modus).
(function () {
  var pref = 'system';
  try { pref = localStorage.getItem('zllm.appearance') || 'system'; } catch (e) { /* privat */ }
  var mode = pref === 'system' ? (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light') : pref;
  document.documentElement.setAttribute('data-theme', mode);
})();
