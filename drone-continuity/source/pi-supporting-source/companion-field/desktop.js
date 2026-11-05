'use strict';
(()=>{
 let active=false,owner=false,generation=0,revision=0,frameBusy=false,inputBusy=false,frameAt=0,expires=0,base='',objectURL='',timer=0,eventId=Date.now()*1000;
 const panel=$('desktop'),screen=$('desktop-image'),status=$('desktop-state');
 const say=text=>{status.textContent=text;};
 function clearFrame(){frameAt=0;base='';screen.hidden=true;screen.removeAttribute('src');if(objectURL)URL.revokeObjectURL(objectURL);objectURL='';}
 function controls(){const usable=owner&&frameAt&&performance.now()-frameAt<2500&&!inputBusy;panel.querySelectorAll('[data-desktop-input]').forEach(b=>b.disabled=!usable);$('desktop-unlock').disabled=owner;$('desktop-lock').disabled=!owner;}
 function localLock(message='Owner access locked. Unlock to view and control the Pi.'){
  ++generation;owner=false;clearTimeout(timer);clearFrame();panel.classList.remove('desktop-expanded');controls();say(message);
 }
 async function lock(){localLock();try{await request('/desktop/lock');}catch(_){} }
 window.axlDesktopLock=lock;
 window.axlDesktopView=enabled=>{active=enabled;if(!enabled){if(owner)lock();else panel.classList.remove('desktop-expanded');}else if(owner)schedule(0);};
 function schedule(delay){clearTimeout(timer);if(active&&owner&&!document.hidden)timer=setTimeout(frame,delay);}
 async function frame(){
  if(frameBusy||!owner||!active||document.hidden)return;
  if(performance.now()>=expires){lock();return;}
  frameBusy=true;const epoch=generation,atRevision=revision,began=performance.now();
  try{
   const value=await request('/desktop/frame',{base});
   if(epoch!==generation||!owner||!active||document.hidden||atRevision!==revision)return;
   if(value.jpeg){
    const bytes=Uint8Array.from(atob(value.jpeg),c=>c.charCodeAt(0));
    if(bytes.length>1048576||value.width>960||value.height>720)throw new Error('Invalid desktop image');
    const next=URL.createObjectURL(new Blob([bytes],{type:'image/jpeg'}));
    const loaded=new Image();loaded.src=next;
    try{await loaded.decode();}catch(error){URL.revokeObjectURL(next);throw error;}
    if(epoch!==generation||!owner||document.hidden||atRevision!==revision){URL.revokeObjectURL(next);return;}
    const old=objectURL;objectURL=next;screen.src=next;screen.hidden=false;if(old)URL.revokeObjectURL(old);
   }
   base=value.frame_id;frameAt=performance.now();
   say('Owner enabled · image response '+Math.round(frameAt-began)+' ms · '+Math.max(0,Math.ceil((expires-frameAt)/1000))+' s remaining');
  }catch(error){
   if(epoch===generation){if(error.locked)localLock(error.message);else{clearFrame();say(error.message+' Reconnect or unlock again.');}}
  }finally{frameBusy=false;controls();schedule(frameAt?250:1000);}
 }
 async function send(command){
  if(!owner||inputBusy||!frameAt||performance.now()-frameAt>=2500||document.hidden){say('Wait for a fresh desktop image before controlling the Pi.');return;}
  inputBusy=true;++revision;const epoch=generation,began=performance.now();controls();
  try{await request('/desktop/input',{event_id:++eventId,command});if(epoch===generation)say('Pi confirmed input in '+Math.round(performance.now()-began)+' ms');}
  catch(error){if(epoch===generation){if(error.locked)localLock(error.message);else say(error.message+' Input was not retried.');}}
  finally{inputBusy=false;controls();schedule(0);}
 }
 $('desktop-unlock').addEventListener('click',async()=>{
  const epoch=++generation;$('desktop-unlock').disabled=true;
  try{const result=await request('/desktop/unlock',{confirm:true});if(epoch!==generation||!active||document.hidden){request('/desktop/lock').catch(()=>{});return;}owner=true;expires=performance.now()+Math.min(300,result.expires_seconds)*1000;eventId=Date.now()*1000;clearFrame();say('Owner enabled. Loading the Pi desktop…');schedule(0);}
  catch(error){say(error.message);}finally{controls();}
 });
 $('desktop-lock').addEventListener('click',lock);
 $('desktop-back').addEventListener('click',()=>showView('dashboard'));
 $('desktop-expand').addEventListener('click',()=>panel.classList.toggle('desktop-expanded'));
 panel.querySelectorAll('[data-desktop-key]').forEach(button=>button.addEventListener('click',()=>send({type:'key',key:button.dataset.desktopKey})));
 panel.querySelectorAll('[data-desktop-scroll]').forEach(button=>button.addEventListener('click',()=>send({type:'scroll',dy:Number(button.dataset.desktopScroll)})));
 $('desktop-type').addEventListener('submit',event=>{event.preventDefault();const text=$('desktop-text').value;$('desktop-text').value='';if(text)send({type:'text',text});});
 let gesture=null;
 function point(event){const box=screen.getBoundingClientRect();return {x:Math.round(Math.max(0,Math.min(1,(event.clientX-box.left)/box.width))*10000),y:Math.round(Math.max(0,Math.min(1,(event.clientY-box.top)/box.height))*10000)};}
 screen.addEventListener('pointerdown',event=>{if(!owner||inputBusy||!frameAt||performance.now()-frameAt>=2500)return;event.preventDefault();gesture={id:event.pointerId,start:point(event),px:event.clientX,py:event.clientY};screen.setPointerCapture(event.pointerId);});
 screen.addEventListener('pointercancel',()=>{gesture=null;});
 screen.addEventListener('pointerup',event=>{
  if(!gesture||gesture.id!==event.pointerId)return;event.preventDefault();const old=gesture;gesture=null;const end=point(event),dx=event.clientX-old.px,dy=event.clientY-old.py;
  if(Math.hypot(dx,dy)>12){if($('desktop-mode').value==='drag')send({type:'drag',...old.start,end_x:end.x,end_y:end.y});else send({type:'scroll',dy:Math.max(-8,Math.min(8,Math.round(-dy/30)||Math.sign(-dy)))});}
  else send({type:'tap',...end,button:$('desktop-button').value});
 });
 document.addEventListener('visibilitychange',()=>{if(document.hidden&&owner)lock();});
 window.addEventListener('offline',()=>{localLock('Connection lost. Reconnect and unlock owner access again.');});
 setInterval(()=>{if(owner&&performance.now()>=expires)lock();controls();},250);
 controls();
})();
