'use strict';
const $=id=>document.getElementById(id);
let token=location.hash.slice(1), unlocked=false, lastSnapshot=0, polling=false, refreshing=false, authEpoch=0;
const initialView=new URLSearchParams(location.search).has('setup')?'connect':'dashboard';
history.replaceState(null,'','/');
function showView(name){if(window.axlDesktopView)window.axlDesktopView(name==='desktop');for(const id of ['dashboard','connect','desktop','guide'])$(id).hidden=id!==name;document.querySelectorAll('nav a').forEach(a=>{if(a.hash==='#'+name)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');});}
document.querySelectorAll('a[href^="#"]').forEach(a=>a.addEventListener('click',event=>{const id=a.hash.slice(1);if(['dashboard','connect','desktop','guide'].includes(id)){event.preventDefault();showView(id);}}));
showView(initialView);
async function request(path,value={},bearer=''){
 const epoch=authEpoch,control=new AbortController(),timer=setTimeout(()=>control.abort(),7000);
 try{
  const headers={'Content-Type':'application/json'};if(bearer)headers.Authorization='Bearer '+bearer;
  const response=await fetch(path,{method:'POST',cache:'no-store',credentials:'same-origin',headers,body:JSON.stringify(value),signal:control.signal});
  const data=await response.json();if(epoch!==authEpoch)throw new DOMException('Session changed','AbortError');
  if(response.status===401){unlocked=false;$('unlock').hidden=false;const error=new Error('Unlock this browser using your private field link.');error.locked=true;throw error;}
  if(!response.ok||!data.ok){const error=new Error(data.error||'Pi request failed.');error.locked=!!data.locked;throw error;}
  unlocked=true;$('unlock').hidden=true;return data;
 }finally{clearTimeout(timer);}
}
function offline(message){lastSnapshot=0;paintSummary(null);$('state').textContent=unlocked?'Dashboard unlocked · live data unavailable':'Private dashboard locked';$('freshness').textContent=message||'Pi data unavailable. Join Drone-Display or your saved hotspot.';$('metrics').replaceChildren();$('faults').replaceChildren();$('phone-state').textContent='Phone GPS unavailable; no fresh Pi confirmation.';}
async function refresh(){
 if(refreshing||document.hidden)return;refreshing=true;
 try{
  const data=await request('/status');
  $('network-state').textContent=data.connected?'Upstream Wi-Fi: '+data.ssid+'.':'No upstream Wi-Fi. The local Pi connection can still work.';
  if(!lastSnapshot)$('state').textContent='Dashboard unlocked · waiting for live telemetry';
  $('review-text').textContent=$('network-state').textContent+' Confirm this is the network you want to use here.';$('review').hidden=!data.review_required;$('review-hint').hidden=!data.review_required;
  $('connect-result').textContent=data.connect_requested?'Connection requested; waiting for the safe network-change check.':data.pending?'New network saved; waiting for activation or your Connect request.':data.connection_result?.detail||'Saved secure networks are available for automatic connection.';
  const networks=await request('/networks'),chosen=$('saved').value;$('saved').replaceChildren();
  for(const name of [...new Set([...networks.saved,...(networks.pending_ssid?[networks.pending_ssid]:[])])]){const option=document.createElement('option');option.value=name;option.textContent=name+(name===networks.pending_ssid?' (saved, pending)':'');$('saved').append(option);}
  if([...$('saved').options].some(o=>o.value===chosen))$('saved').value=chosen;
 }catch(error){$('network-state').textContent=error.name==='AbortError'?'Wi-Fi settings request timed out; live telemetry has a separate status.':error.message;if(!unlocked)offline(error.message);}finally{refreshing=false;}
}
function label(value){return value.replaceAll('_',' ').replace(/\b\w/g,c=>c.toUpperCase());}
function metricRows(value,prefix='',rows=[]){
 if(!value||typeof value!=='object')return rows;
 for(const [key,item] of Object.entries(value)){
  const name=prefix?prefix+' / '+label(key):label(key);
  if(item&&typeof item==='object'&&'fresh' in item&&'value' in item)rows.push([name,item.fresh&&item.value!==null?String(item.value)+' '+(item.unit||''):'Unavailable',item.fresh?'Fresh':item.reason||'No fresh observation']);
  else if(item&&typeof item==='object'&&!Array.isArray(item))metricRows(item,name,rows);
 }return rows;
}
const panelNodes=new Map();
function section(title,rows){
 let details=panelNodes.get(title);
 if(!details){details=document.createElement('details');details.open=['Orange Pi','H743'].includes(title);const heading=document.createElement('summary');heading.textContent=title;details.append(heading,document.createElement('dl'));panelNodes.set(title,details);}
 const list=details.querySelector('dl');
 while(list.children.length>rows.length*2)list.lastChild.remove();
 rows.forEach(([name,value,source],index)=>{while(list.children.length<(index+1)*2)list.append(document.createElement('dt'),document.createElement('dd'));const term=list.children[index*2],definition=list.children[index*2+1],text=value+(source?' · '+source:'');if(term.textContent!==name)term.textContent=name;if(definition.textContent!==text)definition.textContent=text;});
 return details;
}
const summaryNodes=new Map();
function card(container,key,title,value,detail,tone='unknown'){
 let node=summaryNodes.get(key);
 if(!node){node=document.createElement('article');const heading=document.createElement('h3'),reading=document.createElement('p'),note=document.createElement('small');node.append(heading,reading,note);summaryNodes.set(key,node);$(container).append(node);}
 node.className='dashboard-card '+tone;
 [title,value,detail].forEach((text,index)=>{if(node.children[index].textContent!==text)node.children[index].textContent=text;});
}
function observed(item){return item?.fresh===true&&item.value!==null&&item.value!==undefined?item.value:null;}
function reading(item,unit='',digits=1){const value=observed(item);return typeof value==='number'&&Number.isFinite(value)?value.toFixed(digits)+(unit?' '+unit:''):'—';}
function paintSummary(snapshot){
 const pi=snapshot?.pi||{},h=snapshot?.h743||{};
 const flight=observed(h.connected)===true,phone=snapshot?.follow_location?.status==='fresh',ai=observed(pi.ai_process_active);
 card('connection-cards','pi-link','Orange Pi',snapshot?'Connected':'Data unavailable',snapshot?'Authenticated telemetry':'Waiting for a fresh snapshot',snapshot?'good':'unknown');
 card('connection-cards','h743-link','H743',flight?'Connected':'No fresh heartbeat','Independent of the Pi connection',flight?'good':'warning');
 card('connection-cards','phone-link','Phone GPS',phone?'Receiving location':'Unavailable','Your position, not drone GPS',phone?'good':'unknown');
 card('connection-cards','ai-link','AI service',ai===true?'Process active':ai===false?'Process stopped':'Not verified','Process status is not an inference test',ai===true?'good':'unknown');
 card('summary-cards','speed','Ground speed',reading(h.groundspeed_mps,'m/s'),'H743 telemetry');
 card('summary-cards','battery','Flight battery',reading(h.battery_voltage_v,'V'),'H743 telemetry');
 card('summary-cards','satellites','GPS satellites',reading(h.gps_satellites,'',0),'Drone GPS receiver');
 card('summary-cards','altitude','Relative altitude',reading(h.relative_altitude_m,'m'),'H743 telemetry');
 card('summary-cards','temperature','Pi temperature',reading(pi.cpu_max_temperature_c,'°C'),'Measured CPU temperature');
 card('summary-cards','cpu','Pi CPU load',reading(pi.cpu_busy_percent,'%'),'Measured processor activity');
 const memory=observed(pi.memory_available_bytes);
 card('summary-cards','memory','Pi memory available',typeof memory==='number'?(memory/1073741824).toFixed(2)+' GiB':'—','Available RAM');
 card('summary-cards','signal','Pi Wi-Fi signal',reading(pi.wifi_rssi_dbm,'dBm',0),'Pi upstream Wi-Fi, not distance');
}
paintSummary(null);
function paint(snapshot){
 paintSummary(snapshot);$('state').textContent='Private dashboard · authenticated Pi telemetry';

 const panels=[section('Orange Pi',metricRows(snapshot.pi)),section('H743',metricRows(snapshot.h743))];
 if(snapshot.batteries)panels.push(section('Batteries',Object.entries(snapshot.batteries).flatMap(([key,item])=>metricRows(item,'Battery '+key))));
 panels.push(section('Sensors',Object.entries(snapshot.sensor_health||{}).map(([key,item])=>[label(key),item.fresh?'Fresh data':'Unavailable',item.reason||item.status])));
 panels.push(section('Rangefinders',(snapshot.rangefinders||[]).map((item,index)=>['Range '+(item.id??index),item.fresh?JSON.stringify(item):'Unavailable','Read-only observation'])));
 const rc=snapshot.rc_channels||{};panels.push(section('RC channels',(rc.values||[]).map((value,index)=>['Channel '+(index+1),rc.fresh?.[index]?value+' µs':'Unavailable','Raw telemetry only'])));
 panels.push(section('Pi services',[[snapshot.pi_service_health?.fresh?'Current failed-service inventory':'Service inventory unavailable',snapshot.pi_service_health?.fresh?((snapshot.pi_service_health?.units||[]).join(', ')||'No listed failures'):'Not verified','Not a full hardware health test']]));
 panels.push(section('Camera',[[snapshot.camera?.fresh?'Fresh camera observation':'Camera unavailable',snapshot.camera?.fresh?String(snapshot.camera.detection_count)+' detections':'No fresh observation','Observation only']]));
 for(const panel of panels)if(panel.parentNode!==$('metrics'))$('metrics').append(panel);
 $('faults').replaceChildren(...(snapshot.faults||[]).map(item=>{const p=document.createElement('p');p.className='fault';p.textContent=item.text||item.code||'Unspecified fault';return p;}));
 $('phone-state').textContent='Phone GPS: '+(snapshot.follow_location?.status||'unavailable')+'. Phone position is separate from drone GPS.';
 $('freshness').textContent='Authenticated Pi snapshot received now. Individual measurements carry their own freshness checks.';lastSnapshot=performance.now();
}
async function poll(force=false){if(polling||document.hidden||(!unlocked&&!force))return;polling=true;try{const result=await request('/telemetry');if(!document.hidden&&unlocked)paint(result.snapshot);}catch(error){offline(error.name==='AbortError'?'Pi response timed out; all live readings cleared.':error.message);}finally{polling=false;}}
$('pair').addEventListener('submit',async event=>{event.preventDefault();let value=$('access').value.trim();$('access').value='';try{if(value.startsWith('https://')){const url=new URL(value);if(url.hostname!=='orangepi-drone.local'||url.port!=='8446')throw new Error('Use your private Pi field link.');value=url.hash.slice(1);}if(/^join=[A-Za-z0-9_-]{43}$/.test(value))await request('/pair',{code:value.slice(5)});else if(/^[0-9a-f]{64}$/.test(value))await request('/session',{},value);else throw new Error('Private link format is not valid.');showView('dashboard');await Promise.all([refresh(),poll(true)]);}catch(error){$('state').textContent=error.message;}finally{value='';}});
$('hotspot').addEventListener('submit',async event=>{event.preventDefault();$('save').disabled=true;const value={ssid:$('ssid').value,password:$('password').value};$('password').value='';try{await request('/hotspot',value);await refresh();$('saved').value=value.ssid;$('connect-result').textContent='Saved securely. Select this network and tap Connect when ready.';}catch(error){$('connect-result').textContent=error.message;}finally{value.password='';$('save').disabled=false;}});
$('connect-now').addEventListener('click',async()=>{const ssid=$('saved').value;if(!ssid)return;$('connect-now').disabled=true;try{await request('/connect',{ssid});$('connect-result').textContent='Connection requested. Allow about one minute; keep iPhone hotspot Settings open.';}catch(error){$('connect-result').textContent=error.message;}finally{$('connect-now').disabled=false;}});
$('review-done').addEventListener('click',async()=>{try{await request('/review');$('review').hidden=true;$('review-hint').hidden=true;}catch(error){$('state').textContent=error.message;}});
$('refresh').addEventListener('click',refresh);
$('logout').addEventListener('click',async()=>{++authEpoch;unlocked=false;if(window.axlDesktopLock)window.axlDesktopLock();try{await request('/logout');}finally{unlocked=false;$('unlock').hidden=false;offline('This browser is locked.');}});
document.addEventListener('visibilitychange',()=>{if(document.hidden)offline('App is in the background; no live data is displayed.');else{refresh();poll();}});
window.addEventListener('offline',()=>offline());setInterval(()=>{if(lastSnapshot&&performance.now()-lastSnapshot>3500)offline('Snapshot expired; waiting for fresh Pi data.');},500);
setInterval(poll,750);setInterval(()=>{if(unlocked&&!document.hidden)refresh();},12000);
(async()=>{try{if(/^join=[A-Za-z0-9_-]{43}$/.test(token))await request('/pair',{code:token.slice(5)});else if(/^[0-9a-f]{64}$/.test(token))await request('/session',{},token);}catch(error){$('state').textContent=error.message;}finally{token='';}await Promise.all([refresh(),poll(true)]);if('serviceWorker' in navigator)navigator.serviceWorker.register('/sw.js',{updateViaCache:'none'}).catch(()=>{});})();
