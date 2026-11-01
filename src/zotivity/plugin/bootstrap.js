/* Zotivity – Zotero-Plugin (Zotero 8–10). Bewusst schlank: die Arbeit macht der lokale Dienst. */
/* global Services, Zotero */
var Zotivity;

function install() {}

async function startup({ id, version, rootURI }) {
  Services.scriptloader.loadSubScript(rootURI + "content/zotivity.js");
  Zotivity.init({ id, version, rootURI });
  Zotivity.addToAllWindows();
  await Zotivity.main();
}

function onMainWindowLoad({ window }) {
  Zotivity?.addToWindow(window);
}

function onMainWindowUnload({ window }) {
  Zotivity?.removeFromWindow(window);
}

function shutdown() {
  Zotivity?.shutdown();
  Zotivity = undefined;
}

function uninstall() {}
