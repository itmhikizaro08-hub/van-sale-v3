// Minimal service worker — required for "installable" PWA status in most
// browsers. Deliberately does NOT cache anything: this app shows live
// financial data (balances, stock, prices), so serving a stale cached
// response instead of hitting the server would be actively misleading.
// Every request still goes straight to the network as normal.
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (e) => e.waitUntil(self.clients.claim()));
self.addEventListener('fetch', () => {});
