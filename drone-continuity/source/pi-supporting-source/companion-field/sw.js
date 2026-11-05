'use strict';
const CACHE='axl-field-shell-v8';
const STATIC=['/','/field.js','/desktop.js','/field.css','/manifest.webmanifest','/icon.svg','/AXL-Field-Guide.pdf'];
self.addEventListener('install',event=>event.waitUntil(caches.open(CACHE).then(cache=>cache.addAll(STATIC))));
self.addEventListener('activate',event=>event.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(k=>k.startsWith('axl-field-shell-')&&k!==CACHE).map(k=>caches.delete(k)))).then(()=>self.clients.claim())));
self.addEventListener('fetch',event=>{
 const url=new URL(event.request.url);
 if(event.request.method!=='GET'||url.origin!==self.location.origin||!STATIC.includes(url.pathname))return;
 event.respondWith(fetch(event.request).catch(()=>caches.match(url.pathname)));
});
