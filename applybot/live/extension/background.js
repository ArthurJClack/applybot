// Relays between pages and the local ApplyBot bridge. Only the extension can reach the bridge:
// the bridge refuses requests that come from web pages.
const api = typeof browser !== "undefined" ? browser : chrome;
const DEFAULT_PORT = 8765;

async function base() {
  const got = await api.storage.local.get("port");
  return "http://127.0.0.1:" + (got.port || DEFAULT_PORT);
}

async function call(path, body) {
  const opts = body === undefined
    ? { method: "GET" }
    : { method: "POST", headers: { "Content-Type": "application/json", "X-ApplyBot": "1" }, body: JSON.stringify(body) };
  const res = await fetch((await base()) + path, opts);
  if (!res.ok) throw new Error("ApplyBot bridge said " + res.status);
  return res;
}

api.runtime.onMessage.addListener((msg, sender) => {
  const tab = sender.tab ? String(sender.tab.id) : "0";
  if (msg.type === "file") {
    return call(msg.path).then(async (res) => {
      const buf = await res.arrayBuffer();
      return { ok: true, bytes: Array.from(new Uint8Array(buf)), name: res.headers.get("X-Filename") || "document.pdf" };
    }).catch((e) => ({ ok: false, error: String(e) }));
  }
  if (msg.type === "commands") {
    return call("/live/commands?tab=" + tab).then((r) => r.json()).catch(() => ({ commands: [], offline: true }));
  }
  const paths = { page: "/live/page", state: "/live/state", submitted: "/live/submitted", confirmed: "/live/confirmed" };
  if (paths[msg.type]) {
    return call(paths[msg.type], Object.assign({ tab }, msg.data))
      .then((r) => r.json()).catch((e) => ({ offline: true, error: String(e) }));
  }
});

// Toolbar button: run ApplyBot on a site that isn't in the built-in list.
api.browserAction.onClicked.addListener((tab) => {
  api.tabs.executeScript(tab.id, { file: "content.js", allFrames: true });
});

// Self-reload: ApplyBot can ask the extension to reload (new code after a git pull) - no about:debugging trip.
const JOB_TABS = (api.runtime.getManifest().content_scripts || [])[0]?.matches || [];
async function checkIn() {
  try {
    const res = await fetch((await base()) + "/live/ping?ext=1");
    const j = await res.json();
    if (j.reload) {
      await api.storage.local.set({ reloadTabs: true });
      api.runtime.reload();
    }
  } catch (e) { /* bridge not running - fine */ }
}
setInterval(checkIn, 4000);

// After a self-reload, refresh the job tabs so they run the new content script.
(async () => {
  const got = await api.storage.local.get("reloadTabs");
  if (!got.reloadTabs) return;
  await api.storage.local.set({ reloadTabs: false });
  const tabs = await api.tabs.query({ url: JOB_TABS });
  for (const t of tabs) api.tabs.reload(t.id);
})();
