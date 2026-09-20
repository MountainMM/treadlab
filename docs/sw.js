"use strict";
/* TreadLab service worker -- makes the installed web app work with no
   network at all.

   Strategy: stale-while-revalidate. The cached copy answers instantly (so
   the app opens on a plane, or in a gym basement), while a fresh copy is
   fetched in the background for next launch. Bump CACHE on release to
   retire old entries.

   Note: app.js only registers this when the page is NOT on localhost, so
   running TreadLab.bat on your PC always serves the files straight from
   disk and never shows you a stale build. */

const CACHE = "treadlab-v0.5.1";

const SHELL = [
  "./",
  "./style.css",
  "./app.js",
  "./engine/index.js",
  "./engine/fitbase.js",
  "./engine/fit_writer.js",
  "./engine/fit_reader.js",
  "./engine/merge.js",
  "./engine/gps_loop.js",
  "./engine/terrain.js",
  "./manifest.json",
  "./icon-192.png",
  "./icon-512.png",
  "./apple-touch-icon.png",
];

self.addEventListener("install", (e) => {
  e.waitUntil(
    caches.open(CACHE)
      .then((c) => c.addAll(SHELL))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(
        keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;
  if (url.pathname.includes("/_test")) return; // dev-only suite, never cached

  e.respondWith(
    caches.match(req, { ignoreSearch: true }).then((hit) => {
      const network = fetch(req).then((res) => {
        if (res && res.ok && res.type === "basic") {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(req, copy));
        }
        return res;
      }).catch(() => hit || caches.match("./"));
      return hit || network;
    })
  );
});
