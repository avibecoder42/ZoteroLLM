"""Bildet die Prüfungen nach, die Zotero 10 (Firefox-140-Basis) beim Installieren eines Plugins macht.

Quellen im Zotero-Programm (omni.ja):
- modules/Extension.sys.mjs: applications.zotero.{id, update_url, strict_max_version} sind Pflicht
- modules/addons/XPIInstall.sys.mjs: kein '*' in strict_min_version; targetApplication zotero@zotero.org
- modules/addons/XPIDatabase.sys.mjs: isUsableAddon → providesUpdatesSecurely (update_url muss https: sein)
"""

import io
import json
import re
import zipfile

from zotivity.plugin_build import xpi_bytes

ZOTERO_VERSION = "10.0.5"
EXTENSION_ID = re.compile(r"(?i)^[a-z0-9-._]*@[a-z0-9-._]+$")


def _vparts(v: str) -> list:
    return [(10**9 if p == "*" else int(re.match(r"\d*", p).group() or 0)) for p in v.split(".")]


def vc_compare(a: str, b: str) -> int:
    pa, pb = _vparts(a), _vparts(b)
    n = max(len(pa), len(pb))
    pa += [0] * (n - len(pa))
    pb += [0] * (n - len(pb))
    return (pa > pb) - (pa < pb)


def test_xpi_passes_zotero_install_checks():
    z = zipfile.ZipFile(io.BytesIO(xpi_bytes()))
    names = set(z.namelist())
    manifest = json.loads(z.read("manifest.json"))
    app = manifest["applications"]["zotero"]

    assert manifest["manifest_version"] == 2
    assert "bootstrap.js" in names and "prefs.js" in names
    assert EXTENSION_ID.match(app["id"])
    assert app["update_url"].startswith("https:"), "Zotero deaktiviert Plugins mit http-update_url"
    assert app["strict_max_version"] and "*" not in app["strict_min_version"]
    assert vc_compare(ZOTERO_VERSION, app["strict_min_version"]) >= 0
    assert vc_compare(ZOTERO_VERSION, app["strict_max_version"]) <= 0
    for icon in manifest.get("icons", {}).values():
        assert icon in names, f"Icon fehlt im Paket: {icon}"
    for loc in ("de-DE", "en-US"):
        ftl = z.read(f"locale/{loc}/zotivity.ftl").decode()
        assert "zotivity-open =" in ftl and ".label =" in ftl


def test_prefs_point_to_service():
    z = zipfile.ZipFile(io.BytesIO(xpi_bytes("http://127.0.0.1:24000/")))
    assert 'pref("extensions.zotivity.serviceURL", "http://127.0.0.1:24000/");' in z.read("prefs.js").decode()
