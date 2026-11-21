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
  if (msg.type === "focus" && sender.tab) {   // "Show this page" on the dashboard
    api.tabs.update(sender.tab.id, { active: true });
    api.windows.update(sender.tab.windowId, { focused: true, drawAttention: true });
    return Promise.resolve({ ok: true });
  }
  if (msg.type === "markQueue" && sender.tab) {   // the tab that works through the queue
    return api.storage.local.set({ queueTab: sender.tab.id }).then(() => ({ ok: true }));
  }
  if (msg.type === "isQueue" && sender.tab) {
    // the queue's tab was closed (or never set): the next job page that asks becomes the queue's tab
    return api.storage.local.get("queueTab").then(async (g) => {
      if (g.queueTab === sender.tab.id) return { queue: true };
      const alive = g.queueTab != null && await api.tabs.get(g.queueTab).then(() => true, () => false);
      if (alive) return { queue: false };
      await api.storage.local.set({ queueTab: sender.tab.id });
      return { queue: true };
    });
  }
  if (msg.type === "commands") {
    return call("/live/commands?tab=" + tab).then((r) => r.json()).catch(() => ({ commands: [], offline: true }));
  }
  const paths = { page: "/live/page", state: "/live/state", submitted: "/live/submitted", confirmed: "/live/confirmed",
                  control: "/live/control" };
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
  // Tidy up while we're at it: one tab works the queue; every other job tab just fights it for attention
  // (the jobs that needed you are on the dashboard's "Needs you" list), so close them.
  const tabs = await api.tabs.query({ url: JOB_TABS });
  const { queueTab } = await api.storage.local.get("queueTab");
  const sorted = tabs.sort((a, b) => (b.lastAccessed || 0) - (a.lastAccessed || 0));
  const keep = sorted.find((t) => t.id === queueTab) || sorted[0];
  if (keep) await api.storage.local.set({ queueTab: keep.id });   // before the reload, so the page sees it
  for (const t of sorted) {
    if (keep && t.id === keep.id) api.tabs.reload(t.id);
    else api.tabs.remove(t.id);
  }
})();

// Company careers pages that embed Greenhouse (?gh_jid=123) load the form late or not at all. While ApplyBot has
// a queue running, send those tabs to Greenhouse's own copy of the form instead.
function greenhouseForm(url) {
  const m = /[?&]gh_jid=(\d+)/.exec(url || "");
  if (!m || /greenhouse\.io/.test(url)) return null;
  return "https://boards.greenhouse.io/embed/job_app?token=" + m[1];
}
async function queueRunning() {
  try { return ((await (await fetch((await base()) + "/live/ping")).json()).queued || 0) > 0; } catch (e) { return false; }
}
async function rescue(tabId, url) {
  const to = greenhouseForm(url);
  if (to && (await queueRunning())) api.tabs.update(tabId, { url: to });
}
api.tabs.onUpdated.addListener((tabId, info) => { if (info.url) rescue(tabId, info.url); });
api.tabs.query({}).then((tabs) => tabs.forEach((t) => rescue(t.id, t.url)));
