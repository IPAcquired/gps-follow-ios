'use strict';
const $=id=>document.getElementById(id);
let token='';
let reviewedCandidate=null;
let batteryHistorySession='';
let batteryBusy=false;
const batteryObservations=new Map();
let activeView='overview';
let statusTimer=null;
let flightTimer=null;
let insightTimer=null;
let dragLocked=false;
let pendingMove={x:0,y:0};
let moveInFlight=false;
let pendingScroll={x:0,y:0};
let scrollScheduled=false;
let inputSequence=0;
let inputGeneration=0;
let inputQueue=Promise.resolve();
let chatHistory=[];
let pollingGeneration=0;
let pollRecommendations={status:10000,flight:2000,insights:15000};
const pollFailures={status:0,flight:0,insights:0};
const activeRequests=new Set();
const activeUploads=new Set();
let loginInFlight=false;
let wifiPasswordSession='';
let wifiSavedSession='';
let wifiSavedNetworks=[];
let wifiRefreshGeneration=0;
let wifiActionGeneration=0;
const linkSamples=[];
const pointers=new Map();
const auth=()=>({'Authorization':`Bearer ${token}`});

sessionStorage.removeItem('boardSession');
localStorage.removeItem('boardSession');

function bytes(kib){if(!kib)return '—';const n=parseInt(kib)*1024;return n>1073741824?`${(n/1073741824).toFixed(1)} GB`:`${Math.round(n/1048576)} MB`}
function duration(seconds){const d=Math.floor(seconds/86400),h=Math.floor((seconds%86400)/3600);return d?`${d}d ${h}h`:`${h}h ${Math.floor((seconds%3600)/60)}m`}
function number(value,digits=1,suffix=''){return typeof value==='number'&&Number.isFinite(value)?`${value.toFixed(digits)}${suffix}`:'—'}
function record(value){return value!==null&&typeof value==='object'&&!Array.isArray(value)?value:{}}
function scalar(value,low=-Infinity,high=Infinity){return typeof value==='number'&&Number.isFinite(value)&&value>=low&&value<=high?value:undefined}
function integer(value,low,high){return Number.isInteger(value)&&value>=low&&value<=high?value:undefined}
function label(value,fallback,limit=80){return typeof value==='string'&&value.trim()?value.slice(0,limit):fallback}
function freshFlight(value){const f=record(value);return f.schema===1&&f.authority==='read_only_no_mavlink_transmit'&&f.connected===true&&f.fresh===true&&scalar(f.data_age_ms,0,7000)!==undefined}
function setConnection(text,state=''){const el=$('connection');el.className=`status-pill ${state}`;el.querySelector('span').textContent=text}
function setActivity(text,{busy=false,state=''}={}){const el=$('activity');if(!el)return;el.className=`activity-pill ${busy?'busy':''} ${state}`;el.querySelector('span').textContent=text}
function stamp(value){if(!value)return 'Not checked yet';const date=new Date(value);return Number.isNaN(date.getTime())?String(value):date.toLocaleString()}
function milliseconds(value){return Number.isFinite(value)?value<1000?`${Math.round(value)} ms`:`${(value/1000).toFixed(1)} s`:'—'}
function setStreamState(text,state=''){
  const el=$('stream-state');if(el){el.textContent=text;el.className=state}
}
function recordTransport(path,rttMs,serverMs){
  const wireMs=Math.max(0,rttMs-(Number.isFinite(serverMs)?serverMs:0));
  if(path!=='/api/chat'&&path!=='/api/logs'){
    linkSamples.push(wireMs);if(linkSamples.length>8)linkSamples.shift();
    const sorted=[...linkSamples].sort((a,b)=>a-b),median=sorted[Math.floor(sorted.length/2)];
    if($('link-rtt'))$('link-rtt').textContent=`${milliseconds(median)} link`;
  }
  if(path==='/api/input'&&$('input-rtt'))$('input-rtt').textContent=`${milliseconds(rttMs)} acknowledgement`;
  setStreamState('Live','good');
}
function initialAssistant(){return 'I run locally on the Orange Pi. Ask about the board, sensors, or reports. I cannot directly command the aircraft.'}
function clearTransient(){
  reviewedCandidate=null;
  if($('learning-confirm'))$('learning-confirm').checked=false;
  if($('learning-approve'))$('learning-approve').disabled=true;
  if($('learning-report'))$('learning-report').textContent='';
  if($('learning-candidates'))$('learning-candidates').replaceChildren();
  if($('weight-training-status'))$('weight-training-status').textContent='Fresh connection required to load onboard weight-training status.';
  if($('battery-training-status'))$('battery-training-status').textContent='Fresh connection required. No previous battery-training status is treated as current.';
  batteryHistorySession='';batteryBusy=false;batteryObservations.clear();
  if($('battery-label'))$('battery-label').value='';
  if($('battery-confirm'))$('battery-confirm').checked=false;
  if($('battery-assign'))$('battery-assign').disabled=true;
  if($('battery-register'))$('battery-register').disabled=false;
  if($('battery-observation'))$('battery-observation').replaceChildren();
  if($('battery-pack'))$('battery-pack').replaceChildren();
  if($('battery-profiles'))$('battery-profiles').replaceChildren();
  if($('battery-history-count'))$('battery-history-count').textContent='Waiting';
  if($('battery-progress'))$('battery-progress').textContent='Fresh login required. No previous pack selection is reused.';
  if($('wifi-password'))$('wifi-password').value='';
  if($('wifi-ssid'))$('wifi-ssid').value='';
  if($('wifi-saved'))$('wifi-saved').replaceChildren();
  if($('wifi-nearby'))$('wifi-nearby').replaceChildren();
  resetWifiControls();wifiRefreshGeneration+=1;wifiActionGeneration+=1;
  if($('logfile'))$('logfile').value='';
  if($('upload-status'))$('upload-status').textContent='Fresh login required; no prior upload is treated as current.';
  if($('message'))$('message').value='';
  if($('remote-type'))$('remote-type').value='';
  chatHistory=[];
  $('chat').replaceChildren(Object.assign(document.createElement('p'),{className:'assistant',textContent:initialAssistant()}));
  renderFlight({connected:false,reason:'fresh_connection_required',messages:[],battery:{},gps:{},motion:{},attitude:{}});
  renderDevices({});
  renderMatrix([]);
  dragLocked=false;pointers.clear();pendingMove={x:0,y:0};pendingScroll={x:0,y:0};moveInFlight=false;scrollScheduled=false;
  if($('touchpad'))$('touchpad').classList.remove('tracking');
  inputGeneration+=1;inputQueue=Promise.resolve();inputSequence=0;
  if($('drag-lock')){$('drag-lock').classList.remove('active');$('drag-lock').setAttribute('aria-pressed','false')}
  if($('input-status'))$('input-status').textContent='Waiting for a secured session';
  if($('input-link-badge'))$('input-link-badge').textContent='Checking desktop';
  if($('input-rtt'))$('input-rtt').textContent='No input acknowledgement yet';
  if($('link-rtt'))$('link-rtt').textContent='Measuring';
  if($('data-age'))$('data-age').textContent='No H743 data';
  setStreamState('Fresh login required','');
}
async function api(path,options={}){
  const session=token;
  const timeoutMs=options.timeoutMs??(path==='/api/input'?1800:path==='/api/flight'?3000:path==='/api/chat'?125000:path==='/api/insights'?10000:8000);
  const controller=new AbortController();activeRequests.add(controller);
  const timeout=setTimeout(()=>controller.abort(),timeoutMs),started=performance.now();
  const requestOptions={...options,headers:{...auth(),...(options.headers||{})},cache:'no-store',signal:controller.signal};
  delete requestOptions.timeoutMs;
  try{
    const response=await fetch(path,requestOptions),rttMs=performance.now()-started;
    if(token!==session)throw new Error('STALE_SESSION');
    const serverMs=Number(response.headers.get('X-OrangePi-Processing-Ms'));
    recordTransport(path,rttMs,serverMs);
    if(response.status===401)throw new Error('ACCESS');
    const data=await response.json();
    if(token!==session)throw new Error('STALE_SESSION');
    if(!response.ok)throw new Error(data.error||`Request failed (${response.status})`);
    Object.defineProperty(data,'__transport',{value:{rttMs,serverMs,requestId:response.headers.get('X-OrangePi-Request-Id')},enumerable:false});
    return data;
  }catch(error){
    if(token!==session)throw new Error('STALE_SESSION');
    if(error.name==='AbortError')throw new Error('Request timed out; the app will retry without replaying control input.');
    throw error;
  }finally{clearTimeout(timeout);activeRequests.delete(controller)}
}
async function performInput(payload,{quiet=false}={}){
  if(!token)return false;
  const session=token;
  try{
    const event={...payload,event_id:++inputSequence};
    const result=await api('/api/input',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(event)});
    if(token!==session)return false;
    if(result.event_id!==event.event_id)throw new Error('Input acknowledgement did not match the current event.');
    if(!quiet)$('input-status').textContent=`Ready · ${payload.action.replace('_',' ')} accepted · ${milliseconds(result.__transport?.rttMs)}`;
    return true;
  }catch(error){
    if(token!==session||error.message==='STALE_SESSION')return false;
    if(error.message==='ACCESS')requireLogin();
    else if(payload.action==='button'&&payload.state==='down'){
      const released=await failSafeReleaseAfterAmbiguousDown();
      if(token!==session)return false;
      $('input-status').textContent=released?'Drag acknowledgement was lost · fail-safe release confirmed':`Drag acknowledgement was lost · release not confirmed · tap Release all input or sign out`;
    }else{
      inputGeneration+=1;inputQueue=Promise.resolve();pendingMove={x:0,y:0};pendingScroll={x:0,y:0};moveInFlight=false;scrollScheduled=false;
      $('input-status').textContent=`Input unavailable · ${error.message} Older queued input was cancelled.`;
    }
    return false;
  }
}
async function failSafeReleaseAfterAmbiguousDown(){
  // A timed-out/downstream-lost response is ambiguous: the Pi may already
  // have pressed the button. Never replay the down event. Cancel older queued
  // input and send exactly one higher-sequence release with a bounded wait.
  inputGeneration+=1;inputQueue=Promise.resolve();
  const session=token;
  pendingMove={x:0,y:0};pendingScroll={x:0,y:0};moveInFlight=false;scrollScheduled=false;dragLocked=false;pointers.clear();
  if($('drag-lock')){$('drag-lock').classList.remove('active');$('drag-lock').setAttribute('aria-pressed','false')}
  const event={action:'release_all',event_id:++inputSequence};
  try{
    const result=await api('/api/input',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(event),timeoutMs:5000});
    return result.event_id===event.event_id&&result.action==='release_all';
  }catch(error){
    if(token!==session||error.message==='STALE_SESSION')return false;
    if(error.message==='ACCESS')requireLogin();
    return false;
  }
}
function sendInput(payload,options={}){
  // Preserve pointer/button/key order. Release bypasses the queue so a held
  // button can always be cleared immediately, even after a slow request.
  if(payload.action==='release_all'){
    inputGeneration+=1;inputQueue=Promise.resolve();
    return performInput(payload,options);
  }
  const generation=inputGeneration;
  const run=()=>generation===inputGeneration?performInput(payload,options):false;
  const pending=inputQueue.then(run,run);
  inputQueue=pending.then(()=>undefined,()=>undefined);
  return pending;
}
function queuePointerMove(dx,dy){
  pendingMove.x+=dx;pendingMove.y+=dy;
  if(moveInFlight)return;
  moveInFlight=true;
  const generation=inputGeneration;
  requestAnimationFrame(async()=>{
    if(generation!==inputGeneration)return;
    const move={x:pendingMove.x,y:pendingMove.y};pendingMove={x:0,y:0};
    await sendInput({action:'move',dx:move.x,dy:move.y},{quiet:true});
    if(generation!==inputGeneration)return;
    moveInFlight=false;
    if(Math.abs(pendingMove.x)+Math.abs(pendingMove.y)>.2)queuePointerMove(0,0);
  });
}
function queueScroll(dx,dy){
  pendingScroll.x+=dx;pendingScroll.y+=dy;
  if(scrollScheduled)return;
  scrollScheduled=true;
  const generation=inputGeneration;
  requestAnimationFrame(()=>{
    if(generation!==inputGeneration)return;
    const scroll={x:Math.max(-8,Math.min(8,Math.round(pendingScroll.x))),y:Math.max(-8,Math.min(8,Math.round(pendingScroll.y)))};
    pendingScroll={x:0,y:0};scrollScheduled=false;
    if(scroll.x||scroll.y)sendInput({action:'scroll',dx:scroll.x,dy:scroll.y},{quiet:true});
  });
}
async function releaseRemoteInput(){
  dragLocked=false;pointers.clear();pendingMove={x:0,y:0};pendingScroll={x:0,y:0};scrollScheduled=false;moveInFlight=false;
  $('drag-lock').classList.remove('active');$('drag-lock').setAttribute('aria-pressed','false');
  return sendInput({action:'release_all'});
}
function requireLogin(){
  token='';stopPolling();activeRequests.forEach(controller=>controller.abort());activeRequests.clear();
  activeUploads.forEach(upload=>upload.abort());activeUploads.clear();
  clearTransient();setConnection('Fresh login required','bad');if($('pi-link'))$('pi-link').textContent='Fresh login required';if($('h743-link'))$('h743-link').textContent='Waiting';$('unlock').hidden=false;$('dashboard').hidden=true;
}
function showView(name){
  if(!['overview','flight','sensors','control','ai','logs','network'].includes(name))name='overview';
  activeView=name;
  document.querySelectorAll('[data-view]').forEach(view=>{const active=view.dataset.view===name;view.hidden=!active;view.classList.toggle('active',active)});
  document.querySelectorAll('[data-view-target]').forEach(button=>button.classList.toggle('active',button.dataset.viewTarget===name));
  if(innerWidth<681)scrollTo({top:0,behavior:'smooth'});
  if(name==='logs'&&token)refreshInsights(true);
  if(name==='logs'&&token)refreshLearning();
  if(name==='logs'&&token)refreshBatteries();
  if(name==='network'&&token)refreshWifi();
  if(token)restartAdaptivePolls();
}
document.querySelectorAll('[data-view-target]').forEach(button=>button.addEventListener('click',event=>{event.preventDefault();showView(button.dataset.viewTarget)}));

function wifiSSID(value,hidden=false){
  if(typeof value!=='string'||(!value.length&&!hidden)||value.length>32||/[\u0000-\u001f\u007f]/.test(value))return undefined;
  let size=0;
  for(const character of value){
    const code=character.codePointAt(0);
    if(code>=0xd800&&code<=0xdfff)return undefined;
    size+=code<=0x7f?1:code<=0x7ff?2:code<=0xffff?3:4;
    if(size>32)return undefined;
  }
  return value;
}
function wifiText(value,fallback,limit=200){
  return typeof value==='string'&&value.trim()?value.replace(/[\u0000-\u001f\u007f]/g,' ').slice(0,limit):fallback;
}
function wifiIP(value){
  if(typeof value!=='string'||value.length>64)return 'No IP reported';
  if(/^\d{1,3}(?:\.\d{1,3}){3}$/.test(value)&&value.split('.').every(part=>Number(part)<=255)&&value!=='0.0.0.0')return value;
  if(value.includes(':')){
    try{const parsed=new URL(`http://[${value}]/`);if(parsed.hostname.startsWith('[')&&value!=='::')return value}catch{}
  }
  return 'No IP reported';
}
function resetWifiControls(){
  wifiPasswordSession='';wifiSavedSession='';wifiSavedNetworks=[];
  for(const id of ['wifi-save','wifi-password','wifi-connect','wifi-saved'])if($(id))$(id).disabled=true;
}
function unavailableWifi(message){
  resetWifiControls();
  $('wifi-saved').replaceChildren();$('wifi-saved').value='';
  $('wifi-password').value='';
  $('wifi-current').textContent='No verified Wi-Fi status';
  $('wifi-progress').textContent=message;
}
async function refreshWifi(){
  if(!token)return;
  const session=token,generation=++wifiRefreshGeneration,selected=$('wifi-saved').value;
  resetWifiControls();
  try{
    const data=record(await api('/api/wifi')),current=record(data.current);
    if(token!==session||generation!==wifiRefreshGeneration)return;
    if(!Array.isArray(data.saved)||data.saved.length>64||data.saved.some(ssid=>wifiSSID(ssid)===undefined)
      ||data.current!==current||(data.busy!==undefined&&typeof data.busy!=='boolean')
      ||(current.ssid!==undefined&&wifiSSID(current.ssid,true)===undefined)
      ||(current.state!==undefined&&typeof current.state!=='string')||(current.ip!==undefined&&typeof current.ip!=='string')){
      unavailableWifi(wifiText(data.error,'Network status could not be verified. Refresh before choosing a network.'));return;
    }
    const busy=data.busy===true,saved=busy?[]:[...new Set(data.saved)];
    $('wifi-current').textContent=`${current.ssid||'No confirmed Wi-Fi'} · ${wifiText(current.state,'Unknown',40)} · ${wifiIP(current.ip)}`;
    $('wifi-saved').replaceChildren(...saved.map(ssid=>Object.assign(document.createElement('option'),{value:ssid,textContent:ssid})));
    $('wifi-saved').value=saved.includes(selected)?selected:saved[0]||'';
    wifiSavedNetworks=saved;wifiSavedSession=session;
    $('wifi-saved').disabled=busy||!saved.length;$('wifi-connect').disabled=busy||!saved.length;
    const allowed=data.password_entry_allowed===true&&!busy;
    wifiPasswordSession=allowed?session:'';
    $('wifi-save').disabled=!allowed;$('wifi-password').disabled=!allowed;
    if(!allowed)$('wifi-password').value='';
    const job=record(data.job);
    if(data.error)unavailableWifi(wifiText(data.error,'Wi-Fi status unavailable. Refresh before retrying.'));
    else if(typeof job.detail==='string')$('wifi-progress').textContent=`${wifiText(job.state,'Status unknown',40)} · ${wifiText(job.detail,'Waiting for status')}`;
    else if(busy)$('wifi-progress').textContent='Wi-Fi switch in progress. Saved choices will reload from fresh status.';
    else $('wifi-progress').textContent='Saved networks refreshed. Wi-Fi changes are bench-only.';
  }catch(error){if(token!==session||generation!==wifiRefreshGeneration)return;if(error.message==='ACCESS')requireLogin();else unavailableWifi('Wi-Fi status is unavailable. Refresh before choosing a network; no action was repeated.')}
}
async function wifiAction(action,payload={}){
  if(!token)return;
  const session=token,generation=++wifiActionGeneration;
  if(!['scan','save','connect','updates'].includes(action))return;
  if(action==='connect'&&(wifiSavedSession!==session||!wifiSavedNetworks.includes(payload.ssid)||wifiSSID(payload.ssid)===undefined)){
    $('wifi-progress').textContent='Refresh saved networks and select a verified choice first.';return;
  }
  if(action==='save'&&(wifiPasswordSession!==session||wifiSSID(payload.ssid)===undefined
    ||typeof payload.password!=='string'||payload.password.length<8||payload.password.length>63||/[^\x20-\x7e]/.test(payload.password))){
    $('wifi-password').value='';
    $('wifi-progress').textContent='Refresh through the encrypted Windows connection first. Use a valid network name and 8–63 printable ASCII password characters.';return;
  }
  $('wifi-progress').textContent=action==='connect'?'Requesting Wi-Fi switch… USB stays independent.':'Working…';
  try{
    const data=record(await api(`/api/wifi/${action}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload),timeoutMs:action==='save'?18000:8000}));
    if(token!==session||generation!==wifiActionGeneration)return;
    $('wifi-progress').textContent=wifiText(data.detail,wifiText(data.state,'Request result is unknown. Check status before retrying.'));
    if(action==='scan'){
      if(!Array.isArray(data.networks)||data.networks.length>128||data.networks.some(row=>record(row)!==row||wifiSSID(row.ssid,true)===undefined)){
        $('wifi-nearby').replaceChildren();
        $('wifi-progress').textContent='Network scan could not be verified. Check status before retrying; the request was not repeated.';return;
      }
      $('wifi-nearby').replaceChildren(...data.networks.map(network=>{
        const raw=network.signal_dbm;
        const signal=typeof raw==='number'?scalar(raw,-128,0):typeof raw==='string'&&/^-?\d{1,3}(?:\.\d+)?$/.test(raw)?scalar(Number(raw),-128,0):undefined;
        return Object.assign(document.createElement('li'),{textContent:`${network.ssid||'(hidden)'} · ${signal===undefined?'unknown signal':`${signal} dBm`} · ${wifiText(network.security,'security unknown',80)}`});
      }));
    }
    if(action==='connect'){
      for(let attempt=0;attempt<10&&token===session&&generation===wifiActionGeneration;attempt++){
        await new Promise(resolve=>setTimeout(resolve,4000));
        if(token!==session||generation!==wifiActionGeneration)break;
        await refreshWifi();
      }
    }else await refreshWifi();
  }catch(error){if(token!==session||generation!==wifiActionGeneration)return;if(error.message==='ACCESS')requireLogin();else $('wifi-progress').textContent='Wi-Fi request was not confirmed. It was not repeated. Check status before retrying.'}
}
$('wifi-refresh').addEventListener('click',refreshWifi);
$('wifi-scan').addEventListener('click',()=>wifiAction('scan'));
$('wifi-updates').addEventListener('click',()=>{
  if(confirm('Request the approved security-update check? Disconnect flight hardware first. New downloads require trusted Wi-Fi and internet; no automatic reboot.'))wifiAction('updates');
});
$('wifi-connect').addEventListener('click',()=>{
  const ssid=$('wifi-saved').value;
  if(ssid&&confirm(`Switch the board to ${ssid}? Keep USB connected when possible. This is bench-only.`))wifiAction('connect',{ssid});
});
$('wifi-form').addEventListener('submit',event=>{
  event.preventDefault();
  const payload={ssid:$('wifi-ssid').value,password:$('wifi-password').value};
  $('wifi-password').value='';
  wifiAction('save',payload);
});

function renderWeightTraining(training={}){
  const configuration=training.configuration||{};
  const phases={not_reported:'No training run reported',offline_installed_boot_pending:'Installed offline; board boot and training run pending',disabled:'Training disabled',waiting_for_labels:'Waiting for human-reviewed real-flight labels',waiting_for_reviewed_data:'Waiting for reviewed real-flight data',waiting_for_reviewed_data_or_valid_provenance:'Waiting for human-reviewed real-flight data with valid provenance',waiting_for_data_or_review:'Waiting for eligible labels or candidate review',training_data_preparation:'Preparing onboard training data',waiting_for_labels_or_resources:'Waiting for eligible labels or safe resources',waiting_for_resources:'Paused for available memory / temperature',waiting_for_bench:'Paused until safe bench state',training_neural:'Training advisory neural weights',training_qwen:'Training a Qwen adapter candidate',qwen_job_ready:'Qwen data job prepared; training result not yet reported',ready_for_review_or_waiting_for_data:'Pipeline checked; see data / candidate state',awaiting_human_review:'Candidate created; waiting for owner review',validation_failed:'Candidate failed validation; active models unchanged',paused_or_rejected:'Paused by safety, resource, data or integrity guard',neural_weights_approved:'A neural advisory candidate was owner-approved',candidate_created:'Candidate created; not automatically active',completed_or_unchanged:'Checked; completed or no new eligible data'};
  const pipelineDetails=Object.entries(training.pipelines||{}).map(([name,state])=>`${name}: ${state.replaceAll('_',' ')}`).join(' · ');
  $('weight-training-status').textContent=`Onboard training: ${phases[training.state]||'Status unknown'} · neural configured ${configuration.automatic_neural_training?'on':'off'} · Qwen training configured ${configuration.automatic_qwen_training?'on':configuration.automatic_qwen_job_preparation?'data preparation only':'off'}${training.updated_unix?` · last report ${stamp(training.updated_unix*1000)}`:''}${Number.isInteger(training.epoch)?` · epoch ${training.epoch}/${training.total_epochs||'?'}`:''}${pipelineDetails?` · ${pipelineDetails}`:''}. No automatic activation or flight-control authority; a status file is not a live sensor or runtime qualification.`;
  const battery=training.battery_prediction||{},batteryPhases={not_reported:'No training result reported; new boot / telemetry may be pending',offline_installed_boot_pending:'Installed offline; first board training run pending',waiting_actual_battery_telemetry:'Waiting for actual battery measurements',waiting_more_valid_measured_pairs:'Waiting for more valid measured input / target pairs',candidate_training_completed:'Battery training pass completed',diagnostic_candidate_ready:'Diagnostic candidate created',waiting_for_resources:'Paused for safe training resources',paused_or_rejected:'Paused by a safety or integrity check',checking_completed_real_logs:'Checking completed real-flight logs',preparing_measured_voltage_targets:'Preparing actual measured voltage targets',training_candidate_weights:'Training next-voltage diagnostic weights',candidates_ready_for_review:'Diagnostic candidates retained for review',waiting_more_valid_measured_voltage:'Waiting for more valid measured voltage',waiting_completed_analyzer_archive:'Waiting for completed onboard log archive',waiting_model_or_training_lock:'Waiting for shared model or training resources',paused_safety_resource_or_data_integrity:'Paused by safety, resource or data integrity guard',disabled_by_configuration:'Battery training disabled by configuration'};
  $('battery-training-status').textContent=`Onboard battery prediction: ${batteryPhases[battery.state]||'Status unknown'} · configured ${configuration.automatic_battery_prediction_training?'on':'off'} · ${battery.trained_count||0} retained diagnostic candidate(s) with changed weights · ${battery.trained_this_run||0} trained in last reported run${battery.waiting_count?` · ${battery.waiting_count} group(s) waiting for measurements`:''}${Number.isInteger(battery.actual_voltage_rows)?` · ${battery.actual_voltage_rows} measured voltage rows`:''}${Number.isInteger(battery.current_measured_pairs)?` · ${battery.current_measured_pairs} measured-current pairs`:''}${battery.updated_unix?` · last report ${stamp(battery.updated_unix*1000)}`:''}. Next-voltage prediction only; no automatic activation, battery-saving mode, reserve estimate, or flight-control qualification.`;
}
async function refreshLearning(){
  if(!token)return;
  const session=token;
  try{
    const data=await api('/api/insights'),learning=data.learning_review||{};
    if(token!==session)return;
    const root=$('learning-candidates');root.replaceChildren();
    (learning.latest||[]).forEach(item=>{
      const button=Object.assign(document.createElement('button'),{type:'button',textContent:`${item.kind} · ${item.status} · ${item.candidate_id}`});
      button.addEventListener('click',()=>reviewLearning(item));root.append(button);
    });
    if(!(learning.latest||[]).length)root.textContent='No proposals yet. Learning needs completed labelled flight evidence or a staged fast-model settings proposal; simulated data cannot authorize real-flight changes.';
    const audit=learning.offline_code_review||{};
    renderWeightTraining(learning.weight_training||{});
    $('code-review-status').textContent=audit.checked_utc?`Offline code check: ${stamp(audit.checked_utc)} · ${audit.issues} syntax/missing-file issue(s). Report-only; not a full security or firmware certification.`:'Offline code review will run after boot and flight-profile changes.';
  }catch(error){if(token!==session)return;if(error.message==='ACCESS')requireLogin();else $('learning-progress').textContent=error.message}
}
async function reviewLearning(item){
  const session=token;reviewedCandidate=null;$('learning-confirm').checked=false;$('learning-approve').disabled=true;
  try{
    const data=await api('/api/learning/review',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({kind:item.kind,candidate_id:item.candidate_id})});
    if(token!==session)return;
    reviewedCandidate={...data,session};
    $('learning-report').textContent=JSON.stringify({kind:data.kind,candidate_id:data.candidate_id,status:data.status,approval_sha256:data.approval_sha256,proposal:data.proposal,report:data.report},null,2);
    $('learning-progress').textContent='Review the proposal and test report. Only passing, unchanged candidates can be approved; test-only candidates remain blocked.';
  }catch(error){if(token!==session)return;if(error.message==='ACCESS')requireLogin();else $('learning-progress').textContent=error.message}
}
$('learning-refresh').addEventListener('click',refreshLearning);
$('learning-confirm').addEventListener('change',()=>{$('learning-approve').disabled=!$('learning-confirm').checked||!reviewedCandidate||reviewedCandidate.status!=='awaiting_human_review'});
$('learning-approve').addEventListener('click',async()=>{
  const data=reviewedCandidate;
  if(!data||data.session!==token||!$('learning-confirm').checked)return;
  if(!confirm('Approve this exact tested companion-only proposal? H743 settings will not change. Disconnect flight hardware first.'))return;
  reviewedCandidate=null;$('learning-approve').disabled=true;$('learning-confirm').checked=false;
  try{
    const response=await api('/api/learning/approve',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({kind:data.kind,candidate_id:data.candidate_id,approval_sha256:data.approval_sha256,review_ticket:data.review_ticket}),timeoutMs:20000});
    if(token!==data.session)return;
    $('learning-progress').textContent=response.detail;refreshLearning();
  }catch(error){if(token!==data.session)return;if(error.message==='ACCESS')requireLogin();else $('learning-progress').textContent=`${error.message} Approval was not repeated; check its decision before retrying.`}
});

function updateBatteryAssignmentButton(){
  $('battery-assign').disabled=batteryBusy||batteryHistorySession!==token||!token||!$('battery-confirm').checked||!batteryObservations.has($('battery-observation').value)||!$('battery-pack').value;
}
async function refreshBatteries(){
  if(!token||batteryBusy)return;
  const session=token;
  $('battery-confirm').checked=false;$('battery-assign').disabled=true;
  $('battery-progress').textContent='Loading preserved physical battery history…';
  try{
    const data=await api('/api/batteries');
    if(token!==session)return;
    batteryHistorySession=session;batteryObservations.clear();
    const packSelect=$('battery-pack'),recordSelect=$('battery-observation');
    packSelect.replaceChildren(Object.assign(document.createElement('option'),{value:'',textContent:'Choose a saved physical pack'}));
    recordSelect.replaceChildren(Object.assign(document.createElement('option'),{value:'',textContent:'Choose a completed log / BAT monitor'}));
    (data.packs||[]).forEach(pack=>packSelect.append(Object.assign(document.createElement('option'),{value:pack.pack_id,textContent:pack.label})));
    (data.unassigned||[]).forEach(item=>{
      batteryObservations.set(item.observation_id,item);
      recordSelect.append(Object.assign(document.createElement('option'),{value:item.observation_id,textContent:`${String(item.log_sha256).slice(0,12)}… · BAT ${item.instance} · saved ${stamp(item.observed_unix*1000)}`}));
    });
    $('battery-history-count').textContent=`${data.pack_count||0} packs · ${data.observation_count||0} records`;
    const profiles=$('battery-profiles');profiles.replaceChildren();
    (data.packs||[]).forEach(pack=>{
      const card=document.createElement('article');card.className='advisory info';
      const heading=document.createElement('b');heading.textContent=pack.label;
      const summary=pack.summary||{},detail=document.createElement('p');
      detail.textContent=`${pack.observation_count||0} preserved log/monitor record(s) · measured energy ${number(summary.measured_energy_wh,2,' Wh')} · measured average power ${number(summary.mean_measured_power_w,1,' W')} · valid intervals ${number(summary.measured_interval_seconds,1,' s')}`;
      const identity=document.createElement('small');identity.textContent=`Pack ID ${pack.pack_id} · lowest measured voltage ${number(summary.minimum_voltage_v,2,' V')} · peak current ${number(summary.peak_current_a,1,' A')}`;
      const records=document.createElement('p');records.textContent=(pack.observations||[]).map(item=>`${String(item.log_sha256).slice(0,12)}… / BAT ${item.instance}`).join(' · ')||'No flight record is assigned to this physical pack yet.';
      card.append(heading,detail,identity,records);profiles.append(card);
      if(summary.overlapping_monitor_observations){
        const warning=document.createElement('p');warning.textContent='Multiple BAT monitors were assigned to this pack in the same log. Combined energy / power are unknown to prevent double counting. Individual monitor totals follow.';card.append(warning);
        (pack.monitor_summaries||[]).forEach(monitor=>card.append(Object.assign(document.createElement('small'),{textContent:`BAT ${monitor.instance}: measured ${number(monitor.measured_energy_wh,2,' Wh')} · ${number(monitor.mean_measured_power_w,1,' W')}`})));
      }
    });
    if(!(data.packs||[]).length)profiles.textContent='No physical packs registered. Register labelled packs before linking completed flight records.';
    $('battery-progress').textContent=`${data.unassigned_count||0} record(s) still unassigned. New flights never inherit a previous battery assignment.${data.history_truncated?' The latest history window is shown; older immutable records remain stored.':''}${data.pending_record_count?` ${data.pending_record_count} interrupted record(s) need integrity review before assignment.`:''}`;
    updateBatteryAssignmentButton();
  }catch(error){
    if(token!==session)return;
    batteryHistorySession='';batteryObservations.clear();$('battery-confirm').checked=false;
    if(error.message==='ACCESS')requireLogin();else $('battery-progress').textContent=`${error.message} No stored battery records were changed.`;
  }
}
async function batteryAction(action,payload){
  if(!token||batteryBusy)return;
  const session=token;batteryBusy=true;updateBatteryAssignmentButton();$('battery-register').disabled=true;
  $('battery-confirm').checked=false;
  $('battery-progress').textContent=action==='register'?'Saving a new physical pack profile…':'Linking this exact completed record without replacing history…';
  try{
    const data=await api(`/api/batteries/${action}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...payload,confirm:true})});
    if(token!==session)return;
    batteryBusy=false;await refreshBatteries();
    if(token!==session)return;
    $('battery-progress').textContent=data.detail||'Saved; refreshed preserved history.';
    if(action==='register')$('battery-label').value='';
  }catch(error){
    if(token!==session)return;
    if(error.message==='ACCESS')requireLogin();else $('battery-progress').textContent=`${error.message} Refresh history to check the result before retrying; this request was not repeated.`;
  }finally{
    if(token===session){batteryBusy=false;$('battery-register').disabled=false;updateBatteryAssignmentButton()}
  }
}
$('battery-refresh').addEventListener('click',refreshBatteries);
$('battery-observation').addEventListener('change',()=>{$('battery-confirm').checked=false;updateBatteryAssignmentButton()});
$('battery-pack').addEventListener('change',()=>{$('battery-confirm').checked=false;updateBatteryAssignmentButton()});
$('battery-confirm').addEventListener('change',updateBatteryAssignmentButton);
$('battery-register-form').addEventListener('submit',event=>{
  event.preventDefault();const label=$('battery-label').value.trim();
  if(!label||!token)return;
  if(confirm(`Register a NEW physical battery named "${label}"? Use the same saved profile after recharging this pack; do not register it again. Disconnect flight hardware first.`))batteryAction('register',{label});
});
$('battery-assign').addEventListener('click',()=>{
  if(batteryBusy||batteryHistorySession!==token||!$('battery-confirm').checked)return;
  const record=batteryObservations.get($('battery-observation').value),pack=$('battery-pack').selectedOptions[0];
  if(!record||!pack?.value)return;
  if(confirm(`Permanently link completed log ${record.log_sha256}, BAT monitor ${record.instance}, to physical pack "${pack.textContent}"? Confirm ONLY this pack supplied the entire record; leave mixed-pack logs unassigned. This does not identify future batteries or enable a flight mode. Disconnect flight hardware first.`))batteryAction('assign',{flight_log_sha256:record.log_sha256,instance:record.instance,pack_id:pack.value});
});

const deviceLabels={camera:['CAM','Camera','Visual object context'],rplidar:['RP','RPLIDAR','Independent ranging'],matrix_lidar:['8×8','Matrix LiDAR','Forward depth grid'],flight_controller:['H7','H743 controller','Flight authority']};
function renderDevices(sensors={},health={}){
  const entries=Object.entries(deviceLabels);
  // Legacy booleans, serial aliases and old bench markers do not establish
  // current observations. Require the API's explicit fresh-data evidence.
  const fresh=key=>sensors[key]===true&&health[key]?.fresh===true&&health[key]?.status==='fresh_data';
  const state=key=>fresh(key)?'fresh data':health[key]?.device_node_present===true?'port detected · no data':'no data';
  $('devices').innerHTML=entries.map(([key,[abbr,label,detail]])=>`<article class="sensor-card ${fresh(key)?'online':''}"><div class="sensor-top"><span class="sensor-abbr">${abbr}</span><span class="sensor-state"><i class="${fresh(key)?'on':''}"></i>${state(key)}</span></div><h3>${label}</h3><p>${detail}</p></article>`).join('');
  $('device-summary').innerHTML=entries.map(([key,[,label]])=>`<div class="device-mini"><span><i class="${fresh(key)?'on':''}"></i>${fresh(key)?'FRESH DATA':'NO DATA'}</span><b>${label}</b></div>`).join('');
  const count=entries.filter(([key])=>fresh(key)).length,percent=Math.round(count/entries.length*100);
  $('readiness').textContent=`${percent}%`;$('readiness').parentElement.style.setProperty('--progress',`${percent}%`);
  $('readiness').title='Fresh observation coverage, not flight readiness';
  $('matrix-state').textContent=fresh('matrix_lidar')?'Fresh data':'No data';
  $('matrix-source').textContent=fresh('matrix_lidar')?'Verified fresh depth readings':health.matrix_lidar?.device_node_present===true?'Port detected; measurements unverified':'No verified depth readings';
  if(!fresh('matrix_lidar'))renderMatrix([]);
}
function renderMatrix(values){
  const flat=Array.isArray(values)?values.flat().slice(0,64):[];
  $('matrix-grid').innerHTML=Array.from({length:64},(_,index)=>{
    const row=Math.floor(index/8),value=flat[index],valid=typeof value==='number'&&Number.isFinite(value)&&value>=100&&value<4000;
    const range=!valid?'':value<1000?'near':value<3000?'mid':'far';
    return `<span class="matrix-cell ${row>=2&&row<=5?'active-row':''} ${range}" title="${valid?`${Math.round(value)} mm`:'No fresh reading'}">${valid?Math.round(value/10):'—'}</span>`;
  }).join('');
}
function renderFlight(flight={}){
  flight=record(flight);
  // These fields are guaranteed by live_flight_status(), not inferred from
  // node presence or a truthy connected string. A malformed/stale snapshot
  // must not claim LIVE or DISARMED in any browser/iOS client.
  const connected=freshFlight(flight);
  const age=typeof flight.data_age_ms==='number'&&Number.isFinite(flight.data_age_ms)&&flight.data_age_ms>=0?flight.data_age_ms:NaN,ageText=Number.isFinite(age)?milliseconds(age):'no timestamp';
  $('flight-link-badge').textContent=connected?`H743 live · ${ageText} old`:Number.isFinite(age)?`H743 stale · ${ageText} old`:'Waiting for H743';
  if($('data-age'))$('data-age').textContent=connected?`${ageText} old`:Number.isFinite(age)?`Stale · ${ageText}`:'No H743 data';
  $('flight-state-dot').classList.toggle('online',connected);
  $('flight-system-status').textContent=connected?label(flight.system_status,'Connected'):'Disconnected';
  $('flight-transport').textContent=connected?`Read-only via ${label(flight.transport,'MAVLink')}`:'No fresh MAVLink heartbeat';
  if($('h743-link'))$('h743-link').textContent=connected?`Live · ${label(flight.transport,'MAVLink')}`:'Waiting for heartbeat';
  $('flight-mode').textContent=connected?label(flight.mode,'Unknown'):'—';
  $('flight-armed').textContent=connected&&typeof flight.armed==='boolean'?(flight.armed?'ARMED':'Disarmed'):'Unknown';
  $('flight-armed').classList.toggle('bad',connected&&flight.armed===true);
  $('flight-session').textContent=connected?label(flight.flight_session_id,'Not started',13):'Not started';
  const candidate=record(flight.battery),battery=connected&&candidate.fresh===true&&scalar(candidate.data_age_ms,0,5000)!==undefined?candidate:{};
  const gps=connected?record(flight.gps):{},motion=connected?record(flight.motion):{},attitude=connected?record(flight.attitude):{};
  $('flight-battery').textContent=number(scalar(battery.voltage_v,0,1000),1,' V');
  const remaining=scalar(battery.remaining_percent,0,100),satellites=integer(gps.satellites,0,254),fix=integer(gps.fix_type,0,8);
  $('flight-battery-extra').textContent=remaining!==undefined?`${Math.round(remaining)}% remaining`:'No fresh battery data';
  $('flight-gps').textContent=satellites!==undefined?`${satellites} sat`:'—';
  $('flight-gps-extra').textContent=fix!==undefined?`Fix type ${fix}`:'No fresh fix data';
  $('flight-altitude').textContent=number(scalar(gps.relative_altitude_m)??scalar(motion.altitude_m),1);
  $('flight-speed').textContent=number(scalar(motion.groundspeed_mps,0,1000),1);
  const roll=scalar(attitude.roll_deg,-180,180),pitch=scalar(attitude.pitch_deg,-90,90),yaw=scalar(attitude.yaw_deg,-360,360);
  $('flight-roll').textContent=number(roll,1,'°');$('flight-pitch').textContent=number(pitch,1,'°');$('flight-yaw').textContent=number(yaw,1,'°');
  // No fallback level horizon: absent attitude is unknown, not zero degrees.
  const attitudeKnown=roll!==undefined&&pitch!==undefined;
  $('horizon').hidden=!attitudeKnown;
  $('horizon').style.visibility=attitudeKnown?'visible':'hidden';
  $('horizon').style.transform=attitudeKnown?`rotate(${-roll}deg) translateY(${Math.max(-35,Math.min(35,pitch))}px)`:'';
  if($('attitude-state'))$('attitude-state').textContent=attitudeKnown?'Read-only instrument preview':'Attitude unavailable — no verified reading';
  const messages=connected&&Array.isArray(flight.messages)?flight.messages.filter(item=>typeof record(item).text==='string'&&item.text).slice(-100).reverse():[];
  $('message-count').textContent=messages.length;
  if(messages.length){
    $('flight-messages').innerHTML='';
    messages.forEach(item=>{const severity=['emergency','alert','critical','error','warning','notice','info','debug'].includes(item.severity)?item.severity:'info';const p=document.createElement('p');p.className=`flight-message ${severity}`;const level=document.createElement('span');level.textContent=severity;const text=document.createElement('b');text.textContent=item.text.slice(0,1000);p.append(level,text);$('flight-messages').append(p)});
  }else $('flight-messages').innerHTML='<p class="empty-state">No current-flight messages. Previous connection data is not retained here.</p>';
  $('front-source').textContent=connected?'Heartbeat live; front range unverified':'Awaiting H743';
}
async function refreshFlight(){
  if(!token)return false;
  const session=token;
  try{const flight=await api('/api/flight');if(token!==session)return false;renderFlight(flight);return true}
  catch(error){if(token!==session)return false;if(error.message==='ACCESS')requireLogin();else{renderFlight({connected:false,reason:'connection_unavailable',armed:null});setStreamState('Flight stream retrying','bad')}return false}
}
function renderUpdates(update={}){
  const active=['checking','installing_security','verifying'].includes(update.state);
  $('update-progress').classList.toggle('busy',active);
  $('update-progress').querySelector('span').textContent=update.detail||'Waiting for the next safe update check.';
  $('update-detail').textContent=`Last checked: ${stamp(update.checked_utc)}. ${update.kernel_boot_firmware_require_review?'Firmware and kernel updates require review.':''}`;
  $('update-count').textContent=active?'Working…':update.pending_count?`${update.pending_count} available`:update.state==='error'?'Check failed':update.checked_utc?'Up to date':'Not checked';
  $('update-count').classList.toggle('bad',update.state==='error');
  const tags=$('update-packages');tags.replaceChildren();
  (update.pending_packages||[]).forEach(name=>tags.append(Object.assign(document.createElement('span'),{textContent:name})));
}
function renderInsights(data={}){
  renderWeightTraining(data.learning_review?.weight_training||{});
  const processing=data.processing||{},profile=data.profile||{};
  const busy=processing.state!=='idle';
  $('analysis-progress').classList.toggle('busy',busy);
  $('analysis-progress').querySelector('span').textContent=busy?`${processing.queued_bin_files||0} log file(s) safely closing or being analyzed…`:'Analysis is idle and ready for the next completed flight log.';
  $('analysis-state').textContent=busy?'Analyzing':'Idle';
  $('insight-freshness').textContent=`Generated ${stamp(data.generated_utc)}`;
  const advice=$('advisories');advice.replaceChildren();
  (data.advisories||[]).forEach(item=>{const card=document.createElement('article');card.className=`advisory ${item.level||'info'}`;const title=document.createElement('b');title.textContent=item.title||'Advisory';const explanation=document.createElement('p');explanation.textContent=item.explanation||'';const evidence=document.createElement('small');evidence.textContent=`Why: ${item.evidence||'No evidence supplied'}`;const action=document.createElement('em');action.textContent=item.action||'Review only';card.append(title,explanation,evidence,action);advice.append(card)});
  const measurements=$('measurement-list');measurements.replaceChildren();
  (profile.measurements||[]).forEach(item=>{const row=document.createElement('div');const name=document.createElement('b');name.textContent=item.name;const range=document.createElement('span');range.textContent=`min ${item.minimum} · mean ${item.mean} · max ${item.maximum} · ${item.count.toLocaleString()} samples`;row.append(name,range);measurements.append(row)});
  const types=$('message-types');types.replaceChildren();
  (profile.top_message_types||[]).forEach(item=>types.append(Object.assign(document.createElement('span'),{textContent:`${item.name} ${item.count.toLocaleString()}`})));
  $('data-empty').hidden=(profile.measurements||[]).length>0||(profile.top_message_types||[]).length>0;
}
async function refreshInsights(showProgress=false){
  if(!token)return false;
  const session=token;
  if(showProgress)setActivity('Loading updates & flight data',{busy:true});
  try{const [updates,insights]=await Promise.all([api('/api/updates'),api('/api/insights')]);if(token!==session)return false;renderUpdates(updates);renderInsights(insights);if(showProgress)setActivity('Updates & flight data loaded',{state:'good'});return true}
  catch(error){if(token!==session)return false;if(error.message==='ACCESS')requireLogin();else if(showProgress||activeView==='logs'){setActivity('Could not load updates',{state:'bad'});$('analysis-progress').querySelector('span').textContent='Could not load flight analysis. Retrying with backoff.'}return false}
}
async function refresh(showProgress=false){
  if(!token)return false;
  const session=token;
  try{
    if(showProgress){setConnection('Refreshing','warn');setActivity('Loading live board status',{busy:true})}const d=await api('/api/status');
    if(token!==session)return false;
    $('hostname').textContent=d.hostname;$('load').textContent=d.load[0].toFixed(2);$('memory').textContent=bytes(d.memory.available);$('uptime').textContent=duration(d.uptime_seconds);
    const temps=Object.values(d.temperature_c);$('temperature').textContent=temps.length?Math.max(...temps).toFixed(0):'—';
    $('network').textContent=(d.network.addresses||'Offline local mode').replace(/\s+/g,' ');renderDevices(d.sensors,d.sensor_health);renderFlight(d.flight||{});
    const matrixFresh=d.sensors?.matrix_lidar===true&&d.sensor_health?.matrix_lidar?.fresh===true&&d.sensor_health?.matrix_lidar?.status==='fresh_data';
    renderMatrix(matrixFresh&&Array.isArray(d.matrix_distances_mm)?d.matrix_distances_mm:[]);
    const connected=Object.entries(d.display_connectors).filter(([,value])=>value==='connected').map(([key])=>key.replace(/^card\d+-/,''));
    const display=connected.length?connected.join(', '):'No connector';
    const direct=d.network.direct_link?`${d.network.direct_clients} client${d.network.direct_clients===1?'':'s'}`:'Starting';
    const performance=d.performance_guard?.state?(d.performance_guard.state.replaceAll('_',' ')):'Starting';
    const piTransport=location.hostname==='192.0.2.10'?'Private Wi-Fi':location.hostname==='127.0.0.1'||location.hostname==='localhost'?'Encrypted computer tunnel':'Board network';
    $('pi-link').textContent=`Live · ${piTransport}`;$('display').textContent=display;$('direct').textContent=direct;$('performance').textContent=performance;
    const jev=d.jev_advisor||{};$('jev-state').textContent=jev.live_validation_passed?`${jev.live_responses_passed}/${jev.live_requests_tested} live checks passed`:jev.live_api_key_installed?'Live API ready':jev.simulation_passed?`${jev.passed_tests||jev.test_count}/${jev.test_count} offline checks passed`:'Not configured';
    $('sensor-display').textContent=`Display: ${display}. USB-C DisplayPort is preferred when attached.`;
    $('sensor-direct').textContent=`Private link: ${direct}. Client isolation remains enabled.`;
    $('sensor-performance').textContent=`Performance guard: ${performance}. Kernel-approved clocks only.`;
    const remote=d.remote_input||{};
    $('input-link-badge').textContent=remote.available===true?'Desktop input ready':'Desktop unavailable';
    $('pointer-state').textContent=remote.available===true?'Ready':'Offline';
    $('input-status').textContent=remote.available===true?'Secured session · desktop input ready':'Graphical desktop is not available';
    const fusion=d.obstacle_fusion||{};$('fusion-state').textContent=fusion.mavlink_transmit_enabled===true?'Bench-enabled':'Simulation only';
    $('fusion-detail').textContent=fusion.mavlink_transmit_enabled===true?'Bench telemetry output enabled':'MAVLink transmission disabled pending calibration';
    $('files').textContent=(d.flight_profile.files||0).toLocaleString();$('hours').textContent=((d.flight_profile.duration_seconds||0)/3600).toFixed(1);$('messages').textContent=(d.flight_profile.messages||0).toLocaleString();
    const communication=d.communication||{};
    pollRecommendations.status=Math.max(5000,Math.min(30000,Number(communication.status_poll_recommended_ms)||10000));
    pollRecommendations.flight=Math.max(500,Math.min(5000,Number(communication.flight_poll_recommended_ms)||2000));
    pollRecommendations.insights=Math.max(8000,Math.min(60000,Number(communication.insights_poll_recommended_ms)||15000));
    renderUpdates(d.updates||{});$('unlock').hidden=true;$('dashboard').hidden=false;setConnection('Board online');if(showProgress)setActivity('Live data loaded',{state:'good'});return true;
  }catch(error){if(token!==session)return false;if(error.message==='ACCESS')requireLogin();else{renderDevices({});renderFlight({connected:false,reason:'connection_unavailable',armed:null});setConnection('Reconnecting','warn');setActivity('Board link retrying safely',{state:'bad'});setStreamState('Retrying','bad')}return false}
}
function stopPolling(){
  pollingGeneration+=1;
  clearTimeout(statusTimer);clearTimeout(flightTimer);clearTimeout(insightTimer);
  statusTimer=flightTimer=insightTimer=null;
}
function pollDelay(kind){
  let delay=pollRecommendations[kind];
  if(kind==='flight'&&!['flight','control','sensors'].includes(activeView))delay=Math.max(delay,1500);
  if(kind==='insights'&&activeView!=='logs')delay=Math.max(delay,20000);
  if(document.hidden)delay=Math.max(delay,30000);
  delay*=Math.min(4,2**pollFailures[kind]);
  return Math.round(delay*(0.9+Math.random()*0.2));
}
function schedulePoll(kind,operation,generation){
  const run=async()=>{
    if(!token||generation!==pollingGeneration)return;
    const ok=await operation(false);
    pollFailures[kind]=ok?0:Math.min(3,pollFailures[kind]+1);
    if(!token||generation!==pollingGeneration)return;
    const id=setTimeout(run,pollDelay(kind));
    if(kind==='status')statusTimer=id;else if(kind==='flight')flightTimer=id;else insightTimer=id;
  };
  const id=setTimeout(run,pollDelay(kind));
  if(kind==='status')statusTimer=id;else if(kind==='flight')flightTimer=id;else insightTimer=id;
}
function beginPolling(){
  stopPolling();Object.keys(pollFailures).forEach(key=>pollFailures[key]=0);
  const generation=pollingGeneration;
  schedulePoll('status',refresh,generation);schedulePoll('flight',refreshFlight,generation);schedulePoll('insights',refreshInsights,generation);
}
function restartAdaptivePolls(){if(token)beginPolling()}
async function connect(){
  if(loginInFlight)return;
  loginInFlight=true;
  requireLogin();
  const button=$('connect'),progress=$('connect-progress');button.disabled=true;button.textContent='Connecting…';progress.classList.add('busy');progress.querySelector('span').textContent='Opening a fresh secure session…';setActivity('Connecting securely',{busy:true});$('login-error').textContent='';clearTransient();
  const controller=new AbortController(),loginTimeout=setTimeout(()=>controller.abort(),10000);activeRequests.add(controller);const started=performance.now();
  try{
    const response=await fetch('/api/login',{method:'POST',cache:'no-store',signal:controller.signal,headers:{'Content-Type':'application/json'},body:JSON.stringify({username:$('username').value.trim(),password:$('password').value,client_kind:'web'})});
    recordTransport('/api/login',performance.now()-started,Number(response.headers.get('X-OrangePi-Processing-Ms')));
    const data=await response.json();if(!response.ok)throw new Error(data.error||'Login failed');
    if(typeof data.session!=='string'||!data.session)throw new Error('The board did not provide a valid fresh session.');
    token=data.session;$('password').value='';progress.querySelector('span').textContent='Loading live board data…';await Promise.all([refresh(true),refreshInsights(false)]);if(!token)return;showView(location.hash.slice(1)||'overview');beginPolling();
  }catch(error){token='';$('login-error').textContent=error.name==='AbortError'?'Connection timed out. Check the private link and try again.':error.message;setConnection('Login required','bad');setActivity('Connection needs attention',{state:'bad'});progress.querySelector('span').textContent='Connection stopped. Check the message above and try again.'}
  finally{clearTimeout(loginTimeout);activeRequests.delete(controller);loginInFlight=false;button.disabled=false;button.textContent='Connect now';progress.classList.remove('busy')}
}
$('connect').addEventListener('click',connect);$('password').addEventListener('keydown',event=>{if(event.key==='Enter')connect()});$('refresh').addEventListener('click',()=>Promise.all([refresh(true),refreshFlight(),refreshInsights(false)]));
$('forget').addEventListener('click',async()=>{const old=token;if(old)await releaseRemoteInput();if(token!==old)return;requireLogin();if(old){const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),5000);try{await fetch('/api/logout',{method:'POST',headers:{Authorization:`Bearer ${old}`},cache:'no-store',signal:controller.signal})}catch(_){}finally{clearTimeout(timer)}}});
$('logfile').addEventListener('change',event=>{
  const file=event.target.files[0];if(!file)return;
  if(!token){event.target.value='';return}
  const session=token;
  const xhr=new XMLHttpRequest(),started=performance.now();xhr.open('POST','/api/logs');xhr.timeout=10*60*1000;
  activeUploads.add(xhr);
  xhr.setRequestHeader('Authorization',`Bearer ${token}`);xhr.setRequestHeader('Content-Type','application/octet-stream');xhr.setRequestHeader('X-Filename',file.name);
  xhr.upload.onprogress=progress=>{if(token===session&&progress.lengthComputable){const elapsed=Math.max(.001,(performance.now()-started)/1000),percent=Math.round(progress.loaded/progress.total*100),rate=progress.loaded/elapsed,remaining=rate>0?(progress.total-progress.loaded)/rate:0;const speed=rate>1048576?`${(rate/1048576).toFixed(1)} MB/s`:`${Math.round(rate/1024)} KB/s`;$('upload-status').textContent=`Uploading ${file.name}: ${percent}% · ${speed}${remaining>1?` · about ${Math.ceil(remaining)}s left`:''}`;setActivity(`Uploading flight log · ${percent}%`,{busy:true})}};
  xhr.onload=()=>{if(token!==session)return;try{recordTransport('/api/logs',performance.now()-started,Number(xhr.getResponseHeader('X-OrangePi-Processing-Ms')));const data=JSON.parse(xhr.responseText);if(xhr.status===401){requireLogin();return}if(xhr.status<200||xhr.status>=300)throw new Error(data.error||'Upload failed');$('upload-status').textContent=`Uploaded and verified ${data.name} (${data.sha256.slice(0,12)}…). Analysis is queued.`;setActivity('Flight log queued for analysis',{busy:true});refreshInsights(true)}catch(error){$('upload-status').textContent=error.message;setActivity('Upload needs attention',{state:'bad'})}event.target.value=''};
  xhr.onloadend=()=>activeUploads.delete(xhr);
  const failed=message=>{if(token!==session)return;$('upload-status').textContent=message;setActivity('Upload connection failed',{state:'bad'});event.target.value=''};
  xhr.onerror=()=>failed('Upload connection failed. The original file is unchanged; it was not replayed.');xhr.ontimeout=()=>failed('Upload timed out. The original file is unchanged; choose it again to retry.');
  $('upload-status').textContent=`Starting ${file.name}…`;setActivity('Starting flight-log upload',{busy:true});xhr.send(file)
});
$('chat-form').addEventListener('submit',async event=>{
  event.preventDefault();const session=token,input=$('message'),message=input.value.trim();if(!message||!session)return;const user=document.createElement('p');user.className='user';user.textContent=message;$('chat').append(user);input.value='';const wait=document.createElement('p');wait.className='assistant';wait.textContent='Thinking locally · 0s';$('chat').append(wait);wait.scrollIntoView({behavior:'smooth'});const started=performance.now(),progress=setInterval(()=>{if(token!==session){clearInterval(progress);return}const seconds=Math.floor((performance.now()-started)/1000);wait.textContent=`Thinking locally · ${seconds}s · safety review stays active`;setActivity(`Onboard AI working · ${seconds}s`,{busy:true})},1000);
  try{const data=await api('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message,history:chatHistory.slice(-6)})});if(token!==session)return;wait.textContent=`${data.answer}\n\nResponse time: ${milliseconds(data.__transport?.rttMs)} · ${data.model}`;chatHistory.push({role:'user',content:message.slice(0,800)},{role:'assistant',content:String(data.answer).slice(0,800)});chatHistory=chatHistory.slice(-6);setActivity('AI answer received',{state:'good'})}
  catch(error){if(token!==session)return;if(error.message==='ACCESS'){requireLogin();return}wait.textContent=`Could not reach the onboard AI: ${error.message}`;setActivity('AI response needs attention',{state:'bad'})}
  finally{clearInterval(progress)}
});

const touchpad=$('touchpad');
touchpad.addEventListener('contextmenu',event=>event.preventDefault());
touchpad.addEventListener('wheel',event=>{event.preventDefault();queueScroll(Math.sign(event.deltaX),Math.sign(event.deltaY))},{passive:false});
touchpad.addEventListener('pointerdown',event=>{
  event.preventDefault();touchpad.setPointerCapture(event.pointerId);
  pointers.set(event.pointerId,{x:event.clientX,y:event.clientY,startX:event.clientX,startY:event.clientY,time:performance.now(),moved:0});
  touchpad.classList.add('tracking');
});
touchpad.addEventListener('pointermove',event=>{
  const point=pointers.get(event.pointerId);if(!point)return;event.preventDefault();
  const dx=event.clientX-point.x,dy=event.clientY-point.y;point.x=event.clientX;point.y=event.clientY;point.moved+=Math.abs(dx)+Math.abs(dy);
  const speed=Number($('pointer-speed').value)||1.25;
  if(pointers.size===1)queuePointerMove(dx*speed,dy*speed);
  else if(Math.abs(dy)>1.5)queueScroll(0,Math.sign(dy));
});
function endPointer(event){
  const point=pointers.get(event.pointerId);if(!point)return;
  const wasTwo=pointers.size>1,elapsed=performance.now()-point.time;pointers.delete(event.pointerId);
  if(!pointers.size)touchpad.classList.remove('tracking');
  if(event.type==='pointercancel'){releaseRemoteInput();return}
  if(!wasTwo&&point.moved<10&&elapsed<350)sendInput({action:'click',button:'left'});
}
touchpad.addEventListener('pointerup',endPointer);touchpad.addEventListener('pointercancel',endPointer);
$('left-click').addEventListener('click',()=>sendInput({action:'click',button:'left'}));
$('right-click').addEventListener('click',()=>sendInput({action:'click',button:'right'}));
$('drag-lock').addEventListener('click',async()=>{
  const session=token;
  dragLocked=!dragLocked;
  const accepted=await sendInput({action:'button',button:'left',state:dragLocked?'down':'up'});
  if(token!==session)return;
  if(!accepted)dragLocked=false;
  $('drag-lock').classList.toggle('active',dragLocked);$('drag-lock').setAttribute('aria-pressed',String(dragLocked));
});
$('pointer-speed').addEventListener('input',event=>$('pointer-speed-value').textContent=`${Number(event.target.value).toFixed(2)}×`);
document.querySelectorAll('[data-key]').forEach(button=>button.addEventListener('click',()=>sendInput({action:'key',key:button.dataset.key,modifiers:(button.dataset.modifiers||'').split(',').filter(Boolean)})));
const remoteType=$('remote-type');
remoteType.addEventListener('beforeinput',event=>{
  if(event.inputType==='insertText'&&event.data){event.preventDefault();sendInput({action:'text',text:event.data});remoteType.value=''}
  else if(event.inputType==='insertLineBreak'){event.preventDefault();sendInput({action:'key',key:'Enter'});remoteType.value=''}
  else if(event.inputType.startsWith('delete')){event.preventDefault();sendInput({action:'key',key:'Backspace'});remoteType.value=''}
});
remoteType.addEventListener('keydown',event=>{
  if(['Tab','Escape','ArrowUp','ArrowDown','ArrowLeft','ArrowRight'].includes(event.key)){event.preventDefault();sendInput({action:'key',key:event.key})}
});
$('release-input').addEventListener('click',releaseRemoteInput);
document.addEventListener('visibilitychange',()=>{
  if(!token)return;
  if(document.hidden){releaseRemoteInput();restartAdaptivePolls()}
  else{Promise.all([refresh(false),refreshFlight(),activeView==='logs'?refreshInsights(false):Promise.resolve(true)]).finally(restartAdaptivePolls)}
});
window.addEventListener('offline',()=>{if(token)releaseRemoteInput();renderDevices({});renderFlight({connected:false,reason:'device_offline',armed:null});setConnection('Device offline','bad');setStreamState('Paused offline','bad');stopPolling()});
window.addEventListener('online',()=>{if(token){setConnection('Reconnecting','warn');Promise.all([refresh(false),refreshFlight()]).finally(restartAdaptivePolls)}});
window.addEventListener('pagehide',()=>{if(!token)return;const old=token,eventId=++inputSequence;token='';fetch('/api/input',{method:'POST',headers:{Authorization:`Bearer ${old}`,'Content-Type':'application/json'},body:JSON.stringify({action:'release_all',event_id:eventId}),cache:'no-store',keepalive:true}).finally(()=>fetch('/api/logout',{method:'POST',headers:{Authorization:`Bearer ${old}`},cache:'no-store',keepalive:true}).catch(()=>{}))});
if('serviceWorker'in navigator)navigator.serviceWorker.register('/service-worker.js').catch(()=>{});
const hour=new Date().getHours();$('daypart').textContent=hour<12?'morning':hour<18?'afternoon':'evening';renderMatrix([]);requireLogin();showView(location.hash.slice(1)||'overview');
