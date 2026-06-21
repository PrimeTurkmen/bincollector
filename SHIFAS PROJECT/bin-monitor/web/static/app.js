// AIMS Bin Collection Monitor — dashboard

const COLORS = {
  matched:'#16a34a', near1:'#eab308', near2:'#f97316', not_detected:'#64748b',
};
const BAND_COLOR = {'<=15m':'#16a34a','15-30m':'#eab308','30-50m':'#f97316','>50m':'#ef4444'};
const BAND_PILL = {'<=15m':'b15','15-30m':'b30','30-50m':'b50','>50m':'b50p'};
const TRUCK_PALETTE = ['#3b82f6','#a855f7','#f59e0b','#06b6d4','#ec4899','#84cc16'];
const NOTRUCK = '#3a4452';
const COVERAGE = {serviced:'#16a34a', on_route_unused:'#ef4444', off_pilot:'#3a4452'};
const ACCESS = {good:'#16a34a', permanent:'#f59e0b', dynamic:'#ef4444', single:'#64748b'};
const COLLECTED = {collected:'#16a34a', missed:'#ef4444', off_pilot:'#3a4452',
  every_day:'#16a34a', some_days:'#f59e0b', never:'#ef4444'};
let truckColor = {};   // agent_id -> color
let truckPlate = {};   // agent_id -> plate

const PT_COLOR = {confirmed:'#16a34a', coord_review:'#f59e0b', wheel_out:'#38bdf8', new:'#ef4444'};
const PT_LABEL = {confirmed:'at bin', coord_review:'coordinate review', wheel_out:'wheel-out (bin nearby)', new:'isolated / new'};
let visible = new Set();   // agent_ids currently shown
const FRESH = '#16a34a', STALE = '#ef4444';
const nowSec = () => Date.now() / 1000;
let map, layers = {}, state = {day:'', tab:'bins', color:'last24', pilotOnly:false, routes:false, points:false, opt:false, fleet:false};

const vis = aid => visible.has(aid);

function binColor(b){
  if(state.color === 'last24'){
    if(b.collect_status === 'off_pilot') return NOTRUCK;
    return (b.last_lift_ts && nowSec() - b.last_lift_ts <= 86400) ? FRESH : STALE;
  }
  if(state.color === 'collected')
    return COLLECTED[b.collect_status] || NOTRUCK;
  if(state.color === 'truck')
    return b.serviced_agent ? (truckColor[b.serviced_agent]||NOTRUCK) : NOTRUCK;
  if(state.color === 'coverage')
    return COVERAGE[b.coverage_class] || NOTRUCK;
  if(state.color === 'access')
    return b.access_class ? (ACCESS[b.access_class] || NOTRUCK) : NOTRUCK;
  return COLORS[b.status] || COLORS.not_detected;
}

function initMap(){
  map = L.map('map', {zoomControl:true, attributionControl:false, preferCanvas:true})
        .setView([25.41, 55.50], 12);
  // clean dark basemap (CARTO) — no attribution shown
  L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',
    {maxZoom:20, subdomains:'abcd'}).addTo(map);
  layers.areas  = L.layerGroup().addTo(map);
  layers.routes = L.layerGroup().addTo(map);
  layers.bins   = L.layerGroup().addTo(map);
  layers.lifts  = L.layerGroup().addTo(map);
  layers.fleet  = L.layerGroup().addTo(map);
  layers.opt    = L.layerGroup().addTo(map);
  layers.points = L.layerGroup().addTo(map);
  layers.misses = L.layerGroup().addTo(map);
  layers.trucks = L.layerGroup().addTo(map);
}

async function getJSON(u){ const r = await fetch(u); if(!r.ok) throw new Error(r.status); return r.json(); }

function toast(msg){
  const t = document.getElementById('toast'); t.textContent = msg; t.classList.add('show');
  setTimeout(()=>t.classList.remove('show'), 2600);
}

async function loadBootstrap(){
  const b = await getJSON('/api/bootstrap');
  renderKPIs(b.kpis);
  const dsel = document.getElementById('f-day');
  b.days.forEach(d => dsel.add(new Option(d, d)));
  const box = document.getElementById('truck-toggles');
  box.innerHTML = '';
  b.vehicles.forEach((v,i) => {
    truckColor[v.agent_id] = TRUCK_PALETTE[i % TRUCK_PALETTE.length];
    truckPlate[v.agent_id] = v.plate || v.object_name;
    visible.add(v.agent_id);
    const chip = document.createElement('div');
    chip.className = 'chip';
    chip.dataset.agent = v.agent_id;
    chip.innerHTML = `<span class="dotc" style="background:${truckColor[v.agent_id]}"></span>
                      <span class="eye">👁</span> ${truckPlate[v.agent_id]}`;
    chip.onclick = () => {
      const a = v.agent_id;
      if(visible.has(a)){ visible.delete(a); chip.classList.add('off');
        chip.querySelector('.eye').textContent='🚫'; }
      else { visible.add(a); chip.classList.remove('off');
        chip.querySelector('.eye').textContent='👁'; }
      loadMap();
    };
    box.appendChild(chip);
  });
}

function renderKPIs(k){
  const items = [
    [k.every_day ?? 0, 'Collected daily','matched'],
    [k.some_days ?? 0, 'Inconsistent','near1'],
    [k.never_bins ?? 0, 'Never collected','unmatched'],
    [k.in_area ?? 0, 'Bins in pilot area',''],
    [k.bin_lifts ?? k.total_lifts, 'Bin lifts',''],
    [k.bins, 'Expected bins',''],
  ];
  document.getElementById('kpis').innerHTML = items.map(([val,lab,cls])=>
    `<div class="kpi ${cls}"><div class="v">${val??0}</div><div class="l">${lab}</div></div>`).join('');
}

function renderLegend(){
  let html;
  if(state.color === 'last24'){
    html = `
      <span><i style="background:${FRESH}"></i>Collected in last 24 h</span>
      <span><i style="background:${STALE}"></i>Overdue — not collected in 24 h</span>
      <span><i style="background:${NOTRUCK}"></i>Not in pilot area</span>`;
  } else if(state.color === 'collected'){
    html = state.day ? `
      <span><i style="background:${COLLECTED.collected}"></i>Collected this day</span>
      <span><i style="background:${COLLECTED.missed}"></i>Missed this day (skipped on site)</span>
      <span><i style="background:${COLLECTED.off_pilot}"></i>Not serviced this day</span>` : `
      <span><i style="background:${COLLECTED.every_day}"></i>Collected every day</span>
      <span><i style="background:${COLLECTED.some_days}"></i>Some days only (inconsistent)</span>
      <span><i style="background:${COLLECTED.never}"></i>Never (in area, skipped)</span>
      <span><i style="background:${COLLECTED.off_pilot}"></i>Not in pilot area</span>`;
  } else if(state.color === 'truck'){
    html = Object.keys(truckColor).map(a =>
      `<span><i style="background:${truckColor[a]}"></i>${truckPlate[a]}</span>`).join('')
      + `<span><i style="background:${NOTRUCK}"></i>Unused (no truck)</span>`;
  } else if(state.color === 'coverage'){
    html = `
      <span><i style="background:${COVERAGE.serviced}"></i>Serviced (collected)</span>
      <span><i style="background:${COVERAGE.on_route_unused}"></i>On route, never lifted (unused)</span>
      <span><i style="background:${COVERAGE.off_pilot}"></i>Off pilot (other trucks)</span>`;
  } else if(state.color === 'access'){
    html = `
      <span><i style="background:${ACCESS.good}"></i>Good access (reached every day)</span>
      <span><i style="background:${ACCESS.permanent}"></i>Permanent obstruction (always far)</span>
      <span><i style="background:${ACCESS.dynamic}"></i>Dynamic — parked cars / traffic</span>
      <span><i style="background:${ACCESS.single}"></i>One day only</span>`;
  } else {
    html = `
      <span><i style="background:${COLORS.matched}"></i>Collected ≤15m</span>
      <span><i style="background:${COLORS.near1}"></i>Near 15–30m</span>
      <span><i style="background:${COLORS.near2}"></i>Near 30–50m</span>
      <span><i style="background:#ef4444"></i>Unmatched lift >50m (review)</span>
      <span><i style="background:${COLORS.not_detected}"></i>Not detected</span>
      <span>✖ Disposal site (not a bin)</span>`;
  }
  document.getElementById('legend').innerHTML = html;
}

function qs(){ const p=new URLSearchParams(); if(state.day)p.set('day',state.day); return p.toString(); }

async function loadMap(){
  const d = await getJSON('/api/map?'+qs());
  Object.values(layers).forEach(l=>l.clearLayers());

  // areas (admin polygons)
  d.areas.forEach(a=>{
    let pts; try{ pts = typeof a.points==='string'?JSON.parse(a.points):a.points; }catch{ pts=[]; }
    if(pts && pts.length>2)
      L.polygon(pts, {color:a.color||'#3b82f6',weight:1,fill:false,opacity:.35,dashArray:'4'})
       .addTo(layers.areas);
  });

  // fleet plan — all routes that hit the coverage target, each a distinct colour
  const covSel = document.getElementById('fleet-cov');
  if(state.fleet){
    covSel.classList.remove('hidden');
    const fp = await getJSON('/api/fleet-plan?coverage='+covSel.value);
    fp.routes.forEach((rt,i)=>{
      let pts; try{ pts = typeof rt.points==='string'?JSON.parse(rt.points):rt.points; }catch{ pts=[]; }
      const hue = Math.round(i*360/Math.max(1,fp.routes.length));
      const col = `hsl(${hue},75%,55%)`;
      // drop the depot legs (first & last point) so it reads as a coverage blob, not a starburst
      const body = pts.slice(1,-1);
      if(body.length>1)
        L.polyline(body, {color:col, weight:2, opacity:.8})
         .bindPopup(`<b>Route ${rt.route_no}</b> · ${rt.bins} bins · ${rt.km} km`).addTo(layers.fleet);
    });
    // bins left uncovered at this target — marked with a red ring so the gap is explicit
    (fp.uncovered||[]).forEach(p=>{
      L.circleMarker(p, {radius:3, color:'#ef4444', weight:1, fill:false, opacity:.6})
       .addTo(layers.fleet);
    });
    document.getElementById('opt-summary').textContent =
      `▶ ${fp.trucks} trucks cover ${fp.pct_actual}% (${fp.bins_covered}/${fp.total_bins}) · ${fp.bins_uncovered} bins NOT covered (red rings) · ${fp.total_km} km/day`;
  } else { covSel.classList.add('hidden'); }

  // optimized routes (OR-Tools) — ONE route at a time, optionally road-snapped
  const optSum = document.getElementById('opt-summary');
  const optSel = document.getElementById('opt-route');
  const snapWrap = document.getElementById('opt-snap-wrap');
  if(state.opt){
    const o = await getJSON('/api/optimized');
    const s = o.summary;
    const cap = s.assumptions ? ` (≤${s.assumptions.trip_capacity_cbm} CBM/trip, ${s.assumptions.trips_per_day} trips/day)` : '';
    optSum.textContent = `▶ ${s.trucks} trucks · ${s.trips||s.trucks} trips · ${s.total_km} km/day${cap}`;
    optSel.classList.remove('hidden'); snapWrap.classList.remove('hidden');
    if(optSel.options.length !== o.routes.length){
      optSel.innerHTML = o.routes.map(r=>`<option value="${r.route_no}">Route ${r.route_no} · ${r.bins} bins</option>`).join('');
    }
    const n = optSel.value || (o.routes[0] && o.routes[0].route_no) || 1;
    const snap = document.getElementById('opt-snap').checked ? 1 : 0;
    const rt = await getJSON(`/api/optimized/route?n=${n}&snap=${snap}`);
    if(rt.points){
      L.polyline(rt.points, {color:'#a3e635', weight:3, opacity:.9}).addTo(layers.opt);
      (rt.stops||[]).slice(1,-1).forEach((p,i)=>L.circleMarker(p,{radius:4,color:'#a3e635',
        weight:1,fillColor:'#0c1118',fillOpacity:1}).bindTooltip(String(i+1)).addTo(layers.opt));
      const km = rt.road_km ? `${rt.road_km} km by road` : `${rt.straight_km} km (straight)`;
      optSum.textContent = `▶ Route ${n}: ${rt.bins} bins · ${km}  |  fleet: ${s.trucks} trucks · ${s.total_km} km/day`;
    }
  } else { if(!state.fleet) optSum.textContent=''; optSel.classList.add('hidden'); snapWrap.classList.add('hidden'); }

  // routes — the REAL driven GPS path per truck/day
  if(state.routes){
    const tracks = await getJSON('/api/track?'+qs());
    tracks.filter(rt=>vis(rt.agent_id)).forEach(rt=>{
      const c = truckColor[rt.agent_id] || '#38bdf8';
      L.polyline(rt.points, {color:c, weight:2.5, opacity:.75})
       .bindPopup(`<b>${truckPlate[rt.agent_id]||rt.agent_id}</b> · ${rt.day}<br>driven GPS path`)
       .addTo(layers.routes);
    });
  }

  // bins — respect pilot-only + per-truck visibility (unused bins always shown)
  let bins = d.bins;
  if(state.pilotOnly) bins = bins.filter(b => b.serviced_agent);
  bins = bins.filter(b => !b.serviced_agent || vis(b.serviced_agent));
  bins.forEach(b=>{
    const c = binColor(b);
    const svc = b.serviced_agent ? (truckPlate[b.serviced_agent]||b.serviced_agent) : 'none (unused)';
    L.circleMarker([b.lat,b.lon], {radius:4, color:c, weight:1, fillColor:c, fillOpacity:.85})
     .bindPopup(`<b>${b.unique_id}</b><br>${b.area_name||''} · ${b.bin_size||''}<br>
        Collection: <b style="color:${COLLECTED[b.collect_status]||'#999'}">${(b.collect_status||'—').replace('_',' ')}</b>
        ${b.collected_m!=null?`(lift ${b.collected_m}m away)`:''}
        ${b.service_days?`<br>collected ${b.days_collected}/${b.service_days} serviced days`:''}<br>
        Serviced by: <b>${svc}</b><br>
        Nearby lifts: ${b.nearby_lifts} · nearest ${b.nearest_m?b.nearest_m.toFixed(1)+'m':'—'}
        ${b.access_class?`<br>Access: <b style="color:${ACCESS[b.access_class]||'#999'}">${b.access_class}</b> — daily nearest: ${b.access_detail}`:''}`)
     .addTo(layers.bins);
  });

  // unmatched lift points (>50m) — validated against the collection-point cluster
  d.lifts.filter(l=>l.distance_band==='>50m' && vis(l.agent_id)).forEach(l=>{
    const validated = (l.cp_lifts>=3 || l.cp_days>=2);
    const color = validated ? '#38bdf8' : '#ef4444';   // cyan = validated recurring stop
    let verdict;
    if(l.cp_status==='wheel_out')
      verdict = `<b>Validated recurring stop</b> — collected from distance (wheel-out).<br>Known bin ${l.distance_m?l.distance_m.toFixed(0):'?'}m away; truck couldn't get closer.`;
    else if(validated)
      verdict = `<b>Validated recurring stop</b> — no bin registered here.<br><i>Add a bin at this location.</i>`;
    else
      verdict = `<i>One-off — possible GPS noise or a new/relocated bin (review).</i>`;
    L.circleMarker([l.lat,l.lon], {radius:5, color, weight:1.5, fillColor:color, fillOpacity:.7})
     .bindPopup(`<b>Far lift</b> · agent ${l.agent_id} · lift #${l.lift_no}<br>
        nearest bin ${l.distance_m?l.distance_m.toFixed(0):'?'}m · this spot: ${l.cp_lifts||1} lifts / ${l.cp_days||1} day(s)<br>
        ${verdict}`)
     .addTo(layers.lifts);
  });
  // disposal-site (dump) events — not bin collections
  d.lifts.filter(l=>l.distance_band==='dump' && vis(l.agent_id)).forEach(l=>{
    L.marker([l.lat,l.lon], {icon:L.divIcon({className:'',iconSize:[16,16],
      html:`<div style="color:#94a3b8;font-size:14px;line-height:16px;text-align:center">✖</div>`})})
     .bindPopup(`<b>Disposal site</b><br>truck tipped its load here — not a bin lift`)
     .addTo(layers.lifts);
  });

  // collection points (sensor-derived ground truth)
  if(state.points){
    const pts = await getJSON('/api/points');
    pts.filter(p=>vis(p.primary_agent)).forEach(p=>{
      const c = PT_COLOR[p.status] || '#94a3b8';
      L.circleMarker([p.lat,p.lon], {radius:3+Math.min(8,p.lifts), color:c, weight:1.5,
        fillColor:c, fillOpacity:.25})
       .bindPopup(`<b>Collection point</b> — ${PT_LABEL[p.status]||p.status}<br>
          ${p.lifts} lifts over ${p.days} day(s) · ${truckPlate[p.primary_agent]||p.primary_agent}<br>
          nearest known bin: ${p.nearest_bin||'—'} ${p.nearest_m!=null?'('+p.nearest_m+'m)':''}<br>
          bins within 150m (wheel-out): ${p.bins_150}`)
       .addTo(layers.points);
    });
  }

  // missed-bin highlights (shown when the Missed-bins tab is active)
  if(state.tab==='misses'){
    const misses = await getJSON('/api/service-check');
    misses.forEach(m=>{
      L.circleMarker([m.lat,m.lon], {radius:7+2*m.missed, color:'#ef4444', weight:2.5,
        fill:false, dashArray:'3'})
       .bindPopup(`<b>Missed collection</b> — ${m.area||''}<br>
          ${m.day}: ${m.expected} bins here, only ${m.done} lifted → <b>${m.missed} skipped</b>`)
       .addTo(layers.misses);
    });
  }

  // trucks (live position) — ring colored to match the truck's bin color
  d.vehicles.filter(v=>vis(v.agent_id)).forEach(v=>{
    if(v.last_lat==null) return;
    const tc = truckColor[v.agent_id] || '#38bdf8';
    const ic = L.divIcon({className:'', iconSize:[26,26],
      html:`<div class="truck-ico" style="border:2px solid ${tc};border-radius:50%;
            width:26px;height:26px;background:#0c1118cc">🚛</div>`});
    L.marker([v.last_lat,v.last_lon], {icon:ic})
     .bindPopup(`<b>${v.plate||v.object_name}</b><br>speed ${v.last_speed??0} km/h<br>
        ${v.last_seen_ts?new Date(v.last_seen_ts*1000).toLocaleString():''}`)
     .addTo(layers.trucks);
  });
}

// ---- tables ----
function statusPill(s){
  const c = COLLECTED[s] || '#64748b';
  return `<span class="pill" style="background:${c}33;color:${c}">${(s||'—').replace('_',' ')}</span>`;
}

const TABS = {
  bins: { url:()=>'/api/bins-table',
    cols:[['unique_id','Bin name'],['area_name','Area'],['bin_size','Size'],
      ['pickups','Pickups'],['last_collected','Last collected'],['collect_status','Status']],
    row:r=>[`<b>${r.unique_id}</b>`, r.area_name||'—', r.bin_size||'—',
      `<b>${r.pickups}×</b>`, r.last_collected||'—', statusPill(r.collect_status)] },
  viol3: { url:()=>'/api/violations?days=3',
    cols:[['unique_id','Bin name'],['area_name','Area'],['bin_size','Size'],
      ['last_collected','Last collected'],['days_overdue','Days overdue'],['pickups','Pickups']],
    row:r=>[`<b>${r.unique_id}</b>`, r.area_name||'—', r.bin_size||'—',
      r.last_collected||'never', `<span class="pill b50p">${r.days_overdue!=null?r.days_overdue+'d':'never'}</span>`, r.pickups+'×'] },
  viol7: { url:()=>'/api/violations?days=7',
    cols:[['unique_id','Bin name'],['area_name','Area'],['bin_size','Size'],
      ['last_collected','Last collected'],['days_overdue','Days overdue'],['pickups','Pickups']],
    row:r=>[`<b>${r.unique_id}</b>`, r.area_name||'—', r.bin_size||'—',
      r.last_collected||'never', `<span class="pill b50p">${r.days_overdue!=null?r.days_overdue+'d':'never'}</span>`, r.pickups+'×'] },
  lifts: { url:()=>'/api/lifts?'+qs(),
    cols:[['plate','Plate'],['day','Day'],['lift_no','#'],['start_time','Start'],
      ['matched_bin_id','Bin'],['area_name','Area'],['distance_m','Dist m'],['band','Band']],
    row:r=>[r.plate,r.day,r.lift_no,r.start_time,r.matched_bin_id||'—',r.area_name||'—',
      r.distance_m??'—', pill(r.distance_band)] },
  misses:{ url:()=>'/api/service-check',
    cols:[['area','Area'],['day','Day'],['expected','Bins here'],['done','Lifted'],['missed','Skipped']],
    row:r=>[r.area||'—', r.day, r.expected, r.done, `<span class="pill b50p">${r.missed}</span>`] },
  coverage:{ url:()=>'/api/summary/truck-coverage',
    cols:[['plate','Truck'],['bins_serviced','Bins serviced'],['lifts','Total lifts'],['matched','Confirmed ≤15m']],
    row:r=>[`<span style="color:${r.agent_id?truckColor[r.agent_id]:NOTRUCK};font-weight:700">●</span> ${r.plate}`,
      r.bins_serviced, r.lifts??'—', r.matched??'—'] },
  vday:{ url:()=>'/api/summary/vehicle-day',
    cols:[['plate','Plate'],['day','Day'],['valid_lifts','Lifts'],['matched','≤15m'],
      ['unique_bins','Bins'],['near1','15-30'],['near2','30-50'],['unmatched','>50']],
    row:r=>[r.plate,r.day,r.valid_lifts,r.matched,r.unique_bins,r.near1,r.near2,r.unmatched] },
  area:{ url:()=>'/api/summary/area',
    cols:[['area_name','Area'],['expected_bins','Bins'],['nearby_lifts','Lifts'],
      ['matched','≤15m'],['near1','15-30'],['near2','30-50']],
    row:r=>[r.area_name,r.expected_bins,r.nearby_lifts,r.matched,r.near1,r.near2] },
};
function pill(band){ return `<span class="pill ${BAND_PILL[band]||''}">${band||'—'}</span>`; }

let _tableData = [];
async function loadTable(){
  const t = TABS[state.tab];
  const data = await getJSON(t.url());
  _tableData = data;
  document.querySelector('#tbl thead').innerHTML = '<tr>'+t.cols.map(c=>`<th>${c[1]}</th>`).join('')+'</tr>';
  document.querySelector('#tbl tbody').innerHTML =
    data.map((r,i)=>`<tr onclick="focusRow(${i})">`+t.row(r).map(c=>`<td>${c}</td>`).join('')+'</tr>').join('')
    || '<tr><td>No rows</td></tr>';
}

function rowDetail(r){
  if(r.unique_id) return `<b>${r.unique_id}</b><br>${r.area_name||''} · ${r.bin_size||''}<br>
    picked up <b>${r.pickups||0}×</b>, last ${r.last_collected||'—'}<br>
    status: <b>${(r.collect_status||'—').replace('_',' ')}</b>`;
  if(r.plate) return `<b>${r.plate}</b> · lift #${r.lift_no||''}<br>${r.start_time||r.day||''}<br>
    bin: ${r.matched_bin_id||'—'} · ${r.area_name||''} · ${r.distance_m??'?'}m`;
  if(r.area) return `<b>${r.area}</b> · ${r.day}<br>${r.expected} bins, ${r.done} lifted, ${r.missed} skipped`;
  return '';
}
function focusRow(i){
  const r = _tableData[i];
  if(!r || r.lat==null || r.lon==null) return;
  map.setView([r.lat, r.lon], 18);
  L.popup({maxWidth:280}).setLatLng([r.lat, r.lon]).setContent(rowDetail(r)).openOn(map);
}

// ---- events ----
function wire(){
  document.getElementById('f-color').onchange = e=>{ state.color=e.target.value; renderLegend(); loadMap(); };
  document.getElementById('f-pilot').onchange = e=>{ state.pilotOnly=e.target.checked; loadMap(); };
  document.getElementById('f-routes').onchange = e=>{ state.routes=e.target.checked; loadMap(); };
  document.getElementById('f-day').onchange = e=>{ state.day=e.target.value; renderLegend(); loadMap(); loadTable(); };
  document.getElementById('f-points').onchange = e=>{ state.points=e.target.checked; loadMap(); };
  document.getElementById('f-fleet').onchange = e=>{ state.fleet=e.target.checked; loadMap(); };
  document.getElementById('fleet-cov').onchange = ()=> loadMap();
  document.getElementById('f-opt').onchange = e=>{ state.opt=e.target.checked; loadMap(); };
  document.getElementById('opt-route').onchange = ()=> loadMap();
  document.getElementById('opt-snap').onchange = ()=> loadMap();
  document.querySelectorAll('.tab').forEach(b=>b.onclick=()=>{
    document.querySelectorAll('.tab').forEach(x=>x.classList.remove('active'));
    b.classList.add('active'); state.tab=b.dataset.tab; loadTable(); loadMap();
  });
  // draggable sidebar resizer
  const rz = document.getElementById('resizer');
  if(rz){
    let dragging = false;
    rz.addEventListener('mousedown', e=>{ dragging=true; e.preventDefault(); document.body.style.cursor='col-resize'; });
    window.addEventListener('mousemove', e=>{
      if(!dragging) return;
      const w = Math.min(900, Math.max(300, window.innerWidth - e.clientX));
      document.documentElement.style.setProperty('--panelw', w+'px');
    });
    window.addEventListener('mouseup', ()=>{ if(dragging){ dragging=false; document.body.style.cursor='';
      if(map) map.invalidateSize(); } });
  }
  document.getElementById('btn-refresh').onclick = async ()=>{
    toast('Pulling live positions from Pilot…');
    try{ const r = await (await fetch('/api/refresh',{method:'POST'})).json();
      toast(r.ok?`Updated ${r.updated} vehicle position(s)`:'Refresh failed'); loadMap(); }
    catch{ toast('Refresh failed'); }
  };
}

async function refreshKpis(){
  try{ const b = await getJSON('/api/bootstrap'); renderKPIs(b.kpis); }catch{}
}

(async function(){
  initMap(); renderLegend(); wire();
  await loadBootstrap(); await loadMap(); await loadTable();
  // live auto-refresh: reds flip to green as the scheduler ingests new collections
  setInterval(()=>{ loadMap(); refreshKpis(); }, 120000);
})();
