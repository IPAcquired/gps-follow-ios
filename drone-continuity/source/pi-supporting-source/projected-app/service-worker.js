const CACHE='drone-companion-v19-compact-touch-navigation';
const ASSETS=['/','/index.html','/style.css','/app.js','/manifest.webmanifest','/icon.svg'];

self.addEventListener('install',event=>{
  self.skipWaiting();
  event.waitUntil(caches.open(CACHE).then(cache=>cache.addAll(ASSETS)));
});

self.addEventListener('activate',event=>{
  event.waitUntil(Promise.all([
    caches.keys().then(keys=>Promise.all(keys.filter(key=>key.startsWith('drone-companion-')&&key!==CACHE).map(key=>caches.delete(key)))),
    self.clients.claim(),
  ]));
});

self.addEventListener('fetch',event=>{
  const url=new URL(event.request.url);
  if(event.request.method!=='GET'||url.pathname.startsWith('/api/')||url.origin!==self.location.origin||!ASSETS.includes(url.pathname))return;
  event.respondWith(
    fetch(event.request,{cache:'no-cache'}).then(response=>{
      if(response.ok){
        const copy=response.clone();
        event.waitUntil(caches.open(CACHE).then(cache=>cache.put(event.request,copy)).catch(()=>{}));
      }
      return response;
    }).catch(async()=>await caches.match(event.request)||new Response('The companion page is not cached. Reconnect to the board and reload.',{status:503,headers:{'Content-Type':'text/plain; charset=utf-8'}})),
  );
});
