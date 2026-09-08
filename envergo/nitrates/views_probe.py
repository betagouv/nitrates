"""Endpoint d'observabilite infrastructure (carte #111).

Deux vues, toutes deux protegees par le jeton `NITRATES_PROBE_TOKEN` :

- `probe_now`   : instantane JSON des metriques du container qui sert la requete
- `probe_dash`  : page HTML autonome qui interroge `probe_now` en boucle et
                  trace les series (aucune dependance externe, CSP-compatible)

Ces vues n'existent que si `NITRATES_PROBE_TOKEN` est defini : sur un
environnement ou la variable est absente, les routes ne sont pas montees.

Note sur la lecture des chiffres : chaque requete peut tomber sur un container
different (2 web sur staging). Le champ `container` permet de les distinguer,
et le dashboard trace une serie par container.
"""

import hmac
import json

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt

from envergo.nitrates.probe import collect


def _authorized(request):
    expected = getattr(settings, "NITRATES_PROBE_TOKEN", "") or ""
    if not expected:
        return False
    given = request.GET.get("token") or request.headers.get("X-Probe-Token") or ""
    # compare_digest : evite de fuir la longueur du jeton par le temps de reponse
    return hmac.compare_digest(given, expected)


@csrf_exempt
@never_cache
def probe_now(request):
    if not _authorized(request):
        # 404 et pas 403 : on ne revele pas l'existence de l'endpoint.
        return HttpResponse(status=404)
    return JsonResponse(collect())


@never_cache
def probe_dash(request):
    if not _authorized(request):
        return HttpResponse(status=404)
    # Le dashboard s'interroge lui-meme en AJAX (meme URL + json=1) pour eviter
    # d'exposer deux routes et de dupliquer le controle du jeton.
    if request.GET.get("json"):
        return JsonResponse(collect())
    token = request.GET.get("token", "")
    html = _DASH_HTML.replace("__TOKEN__", json.dumps(token))
    return HttpResponse(html, content_type="text/html; charset=utf-8")


# Page autonome : pas de CDN, pas de lib externe (la CSP de l'app interdit les
# hotes tiers). Canvas + fetch suffisent largement pour ce qu'on veut voir.
_DASH_HTML = """<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<title>Sonde infra staging</title>
<style>
 body{font-family:system-ui,sans-serif;margin:1.5rem;background:#0d1117;color:#c9d1d9}
 h1{font-size:1.1rem;margin:0 0 .3rem}
 p.sub{color:#8b949e;margin:.2rem 0 1.2rem;font-size:.85rem}
 .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(330px,1fr));gap:1rem}
 .card{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:.8rem}
 .card h2{font-size:.8rem;margin:0 0 .5rem;color:#8b949e;font-weight:600;
          text-transform:uppercase;letter-spacing:.04em}
 canvas{width:100%;height:130px;display:block}
 .val{font-variant-numeric:tabular-nums;font-size:1.5rem;font-weight:600}
 .unit{font-size:.75rem;color:#8b949e;font-weight:400}
 .warn{color:#f85149}.ok{color:#3fb950}
 table{border-collapse:collapse;width:100%;font-size:.8rem;margin-top:.4rem}
 td{padding:.15rem .3rem;border-bottom:1px solid #21262d}
 td:last-child{text-align:right;font-variant-numeric:tabular-nums}
 #err{color:#f85149;font-size:.8rem}
</style></head><body>
<h1>Sonde infrastructure &mdash; nitrates staging</h1>
<p class="sub">Mesures lues dans le container (cgroup v2 + PSI), rafraichies
toutes les 2 s. Une serie par container. Carte #111.</p>
<p id="err"></p>
<div class="grid">
  <div class="card"><h2>Fautes de page majeures (cumul)</h2>
    <div class="val" id="v-majflt">&mdash;</div>
    <canvas id="c-majflt"></canvas></div>
  <div class="card"><h2>Pression memoire PSI (% temps bloque)</h2>
    <div class="val" id="v-psimem">&mdash;<span class="unit"> %</span></div>
    <canvas id="c-psimem"></canvas></div>
  <div class="card"><h2>Pression I/O PSI (% temps bloque)</h2>
    <div class="val" id="v-psiio">&mdash;<span class="unit"> %</span></div>
    <canvas id="c-psiio"></canvas></div>
  <div class="card"><h2>Latence lecture disque</h2>
    <div class="val" id="v-disk">&mdash;<span class="unit"> ms</span></div>
    <canvas id="c-disk"></canvas></div>
  <div class="card"><h2>Latence aller-retour SQL</h2>
    <div class="val" id="v-db">&mdash;<span class="unit"> ms</span></div>
    <canvas id="c-db"></canvas></div>
  <div class="card"><h2>Etat courant</h2><table id="tbl"></table></div>
</div>
<script>
const TOKEN = __TOKEN__;
const N = 150;
const series = {majflt:[], psimem:[], psiio:[], disk:[], db:[]};
let prev = null;

function draw(id, data, color){
  const cv = document.getElementById(id);
  const dpr = window.devicePixelRatio || 1;
  cv.width = cv.clientWidth * dpr; cv.height = cv.clientHeight * dpr;
  const ctx = cv.getContext('2d'); ctx.scale(dpr, dpr);
  const w = cv.clientWidth, h = cv.clientHeight;
  ctx.clearRect(0,0,w,h);
  if (!data.length) return;
  const max = Math.max(...data, 0.0001), min = 0;
  ctx.strokeStyle = color; ctx.lineWidth = 1.5; ctx.beginPath();
  data.forEach((v,i)=>{
    const x = (i/(N-1))*w, y = h - ((v-min)/(max-min||1))*(h-4) - 2;
    i ? ctx.lineTo(x,y) : ctx.moveTo(x,y);
  });
  ctx.stroke();
  ctx.fillStyle = '#8b949e'; ctx.font = '10px system-ui';
  ctx.fillText(max.toFixed(max<10?2:0), 3, 11);
}

function push(k,v){ series[k].push(v); if(series[k].length>N) series[k].shift(); }

async function tick(){
  try{
    const r = await fetch('?token='+encodeURIComponent(TOKEN)+'&json=1',
                          {headers:{'Accept':'application/json'}});
    if(!r.ok) throw new Error('HTTP '+r.status);
    const d = await r.json();
    document.getElementById('err').textContent = '';

    const majflt = d.memory.pgmajfault ?? 0;
    // PSI total est cumulatif en microsecondes : on derive le % de temps
    // bloque sur l'intervalle ecoule entre deux echantillons.
    let psimem = 0, psiio = 0;
    if (prev){
      const dt = (d.ts - prev.ts) * 1e6;
      if (dt > 0){
        const dm = (d.pressure.memory?.some?.total ?? 0) - (prev.pressure.memory?.some?.total ?? 0);
        const di = (d.pressure.io?.some?.total ?? 0) - (prev.pressure.io?.some?.total ?? 0);
        psimem = Math.max(0, Math.min(100, dm/dt*100));
        psiio  = Math.max(0, Math.min(100, di/dt*100));
      }
    }
    push('majflt', majflt); push('psimem', psimem); push('psiio', psiio);
    push('disk', d.latency_ms.disk_read ?? 0); push('db', d.latency_ms.db_roundtrip ?? 0);

    document.getElementById('v-majflt').textContent = majflt.toLocaleString('fr-FR');
    const fmt = (el,v,warn)=>{ const e=document.getElementById(el);
      e.innerHTML = v.toFixed(2)+' <span class="unit">'+(el.includes('psi')?'%':'ms')+'</span>';
      e.className = 'val ' + (v>warn?'warn':'ok'); };
    fmt('v-psimem', psimem, 5); fmt('v-psiio', psiio, 5);
    fmt('v-disk', d.latency_ms.disk_read ?? 0, 5);
    fmt('v-db', d.latency_ms.db_roundtrip ?? 0, 20);

    draw('c-majflt', series.majflt, '#f0883e');
    draw('c-psimem', series.psimem, '#f85149');
    draw('c-psiio',  series.psiio,  '#a371f7');
    draw('c-disk',   series.disk,   '#58a6ff');
    draw('c-db',     series.db,     '#3fb950');

    const MB = x => x==null ? '&mdash;' : (x/1048576).toFixed(0)+' MiB';
    document.getElementById('tbl').innerHTML =
      '<tr><td>container</td><td>'+(d.container||'?')+'</td></tr>'+
      '<tr><td>memory.current</td><td>'+MB(d.memory.current)+'</td></tr>'+
      '<tr><td>memory.max</td><td>'+MB(d.memory.max)+'</td></tr>'+
      '<tr><td>swap.current</td><td>'+MB(d.memory.swap_current)+'</td></tr>'+
      '<tr><td>anon / file</td><td>'+MB(d.memory.anon)+' / '+MB(d.memory.file)+'</td></tr>'+
      '<tr><td>refault anon</td><td>'+(d.memory.workingset_refault_anon??'&mdash;')+'</td></tr>'+
      '<tr><td>cpu throttled</td><td>'+(d.cpu.nr_throttled??'&mdash;')+' / '+(d.cpu.nr_periods??'&mdash;')+'</td></tr>'+
      '<tr><td>swap de ce process</td><td>'+(d.process.vm_swap_kb??'&mdash;')+' kB</td></tr>';
    prev = d;
  }catch(e){
    document.getElementById('err').textContent = 'Erreur de collecte : '+e.message;
  }
}
tick(); setInterval(tick, 2000);
</script></body></html>
"""
