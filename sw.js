// Офлайн-кэш: файлы приложения + Python (Pyodide) с CDN
const V = 'v1', APP = 'app-' + V, RT = 'rt-' + V;
const PY = 'https://cdn.jsdelivr.net/pyodide/v0.26.4/full/';
const SHELL = ['./', 'index.html', 'flowchart_core.py', 'manifest.webmanifest', 'icon-192.png', 'icon-512.png', 'apple-touch-icon.png'];
const PYFILES = ['pyodide.js', 'pyodide.asm.js', 'pyodide.asm.wasm', 'python_stdlib.zip', 'pyodide-lock.json'].map(f => PY + f);

self.addEventListener('install', e => {
  e.waitUntil((async () => {
    await (await caches.open(APP)).addAll(SHELL);
    const rt = await caches.open(RT);
    await Promise.allSettled(PYFILES.map(u => rt.add(u)));
    self.skipWaiting();
  })());
});
self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== APP && k !== RT).map(k => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener('fetch', e => {
  const r = e.request, u = new URL(r.url);
  if (r.method !== 'GET') return;
  if (u.origin === location.origin) {            // свои файлы: из кэша, обновление в фоне
    e.respondWith((async () => {
      const hit = await caches.match(r, {ignoreSearch: true});
      const net = fetch(r).then(async res => { if (res.ok) (await caches.open(APP)).put(r, res.clone()); return res; }).catch(() => null);
      return hit || (await net) || caches.match('index.html');
    })());
  } else if (u.hostname === 'cdn.jsdelivr.net') { // Python: из кэша, иначе из сети и в кэш
    e.respondWith((async () => {
      const hit = await caches.match(r);
      if (hit) return hit;
      const res = await fetch(r);
      if (res.ok) (await caches.open(RT)).put(r, res.clone());
      return res;
    })());
  }
});
