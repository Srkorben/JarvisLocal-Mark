from __future__ import annotations

import html


def render_dashboard(*, csrf_token: str, nonce: str, version: str) -> str:
    csrf = html.escape(csrf_token, quote=True)
    safe_nonce = html.escape(nonce, quote=True)
    safe_version = html.escape(version, quote=True)
    return f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="color-scheme" content="dark">
  <title>JarvisLocal · Centro de control</title>
  <style nonce="{safe_nonce}">
    :root {{ color-scheme: dark; --bg:#0b0d0f; --panel:#121518; --line:#292e33;
      --muted:#949ba3; --text:#f2f4f5; --soft:#1a1e22; --ok:#d5d9dc; --bad:#d7a3a3; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; min-height:100vh; background:var(--bg); color:var(--text);
      font-family:Segoe UI,Inter,system-ui,sans-serif; }}
    main {{ width:min(1180px,calc(100% - 32px)); margin:0 auto; padding:32px 0 56px; }}
    header {{ display:flex; align-items:flex-start; justify-content:space-between; gap:24px;
      padding-bottom:24px; border-bottom:1px solid var(--line); }}
    .identity {{ display:flex; gap:16px; align-items:center; }}
    .mark {{ width:48px; height:48px; border:1px solid #555d65; border-radius:12px;
      display:grid; place-items:center; background:#101316; font-weight:700; font-size:22px; }}
    h1 {{ font-size:clamp(22px,3vw,32px); margin:0 0 5px; letter-spacing:-.03em; }}
    p {{ margin:0; color:var(--muted); line-height:1.55; }}
    .local {{ border:1px solid var(--line); border-radius:999px; padding:7px 11px;
      font-size:12px; color:#c8cdd1; white-space:nowrap; }}
    .toolbar {{ display:flex; justify-content:space-between; align-items:center; gap:16px;
      margin:24px 0; }}
    .summary {{ color:var(--muted); font-size:14px; }}
    button {{ appearance:none; border:1px solid #3a4148; background:#1b2025; color:var(--text);
      border-radius:8px; padding:9px 13px; font:inherit; font-size:13px; cursor:pointer; }}
    button:hover:not(:disabled) {{ background:#252b31; border-color:#59616a; }}
    button:focus-visible {{ outline:2px solid #d6dadd; outline-offset:2px; }}
    button:disabled {{ opacity:.42; cursor:not-allowed; }}
    button.secondary {{ background:transparent; }}
    section {{ margin-top:28px; }}
    h2 {{ margin:0 0 12px; font-size:13px; color:#adb3b9; text-transform:uppercase;
      letter-spacing:.12em; font-weight:600; }}
    .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(270px,1fr)); gap:12px; }}
    article {{ min-height:190px; display:flex; flex-direction:column; background:var(--panel);
      border:1px solid var(--line); border-radius:12px; padding:17px; }}
    .card-head {{ display:flex; justify-content:space-between; gap:12px; align-items:flex-start; }}
    h3 {{ margin:0; font-size:16px; letter-spacing:-.01em; }}
    .status {{ font-size:11px; border:1px solid #394047; border-radius:999px; padding:4px 7px;
      color:#c2c7cc; white-space:nowrap; text-transform:uppercase; letter-spacing:.05em; }}
    .status.running {{ background:#e4e7e9; color:#101214; border-color:#e4e7e9; }}
    .status.error,.status.unavailable {{ color:var(--bad); border-color:#664747; }}
    .desc {{ margin-top:12px; font-size:13px; flex:1; }}
    .meta {{ margin-top:12px; font-size:11px; color:#747c84; overflow-wrap:anywhere; }}
    .missing {{ color:#cba4a4; margin-top:8px; font-size:11px; }}
    .actions {{ display:flex; gap:8px; margin-top:16px; }}
    .actions button {{ flex:1; }}
    #notice {{ position:fixed; right:18px; bottom:18px; max-width:min(420px,calc(100% - 36px));
      background:#eef0f1; color:#121416; border-radius:9px; padding:12px 14px; box-shadow:0 8px 28px #0008;
      opacity:0; transform:translateY(8px); pointer-events:none; transition:.16s ease; font-size:13px; }}
    #notice.show {{ opacity:1; transform:none; }}
    footer {{ margin-top:42px; border-top:1px solid var(--line); padding-top:18px;
      color:#6f777f; font-size:12px; }}
    @media (max-width:640px) {{ main {{ width:min(100% - 20px,1180px); padding-top:20px; }}
      header {{ flex-direction:column; }} .toolbar {{ align-items:flex-start; }} }}
  </style>
</head>
<body>
<main>
  <header>
    <div class="identity"><div class="mark" aria-hidden="true">J</div><div>
      <h1>Centro de control</h1>
      <p>Herramientas locales de JarvisLocal, reunidas en una sola interfaz.</p>
    </div></div>
    <div class="local">● Solo 127.0.0.1</div>
  </header>
  <div class="toolbar"><div id="summary" class="summary">Comprobando herramientas…</div>
    <button id="refresh" class="secondary" type="button">Actualizar</button></div>
  <div id="content" aria-live="polite"></div>
  <footer>JarvisLocal {safe_version} · Sin ejecución arbitraria · Las acciones sensibles requieren confirmación.</footer>
</main>
<div id="notice" role="status"></div>
<script nonce="{safe_nonce}">
const csrf = "{csrf}";
const labels = {{available:"Disponible",running:"En ejecución",unavailable:"No disponible",error:"Con error"}};
const content = document.getElementById("content");
const summary = document.getElementById("summary");
const notice = document.getElementById("notice");
function esc(value) {{ const node=document.createElement("span"); node.textContent=String(value??""); return node.innerHTML; }}
function tell(message) {{ notice.textContent=message; notice.classList.add("show"); setTimeout(()=>notice.classList.remove("show"),4200); }}
async function request(url, options={{}}) {{
  const response=await fetch(url,{{credentials:"same-origin",...options,headers:{{"X-CSRF-Token":csrf,"Content-Type":"application/json",...(options.headers||{{}})}}}});
  const data=await response.json().catch(()=>({{error:{{message:"Respuesta local inválida."}}}}));
  if(!response.ok) throw new Error(data.error?.message||"La acción falló.");
  return data;
}}
async function load() {{
  try {{
    const data=await request("/api/tools");
    const tools=data.tools;
    const groups={{}};
    for(const tool of tools) (groups[tool.category]??=[]).push(tool);
    content.innerHTML=Object.entries(groups).map(([category,items])=>`<section><h2>${{esc(category)}}</h2><div class="grid">${{items.map(card).join("")}}</div></section>`).join("");
    const running=tools.filter(t=>t.status==="running").length;
    const ready=tools.filter(t=>t.status==="available").length;
    summary.textContent=`${{ready}} disponibles · ${{running}} en ejecución · ${{tools.length}} funciones`;
  }} catch(error) {{ content.innerHTML=""; summary.textContent="No se pudo consultar el servicio."; tell(error.message); }}
}}
function card(tool) {{
  const canStart=tool.status==="available"||tool.status==="error";
  const missing=tool.missing?.length?`<div class="missing">${{esc(tool.missing.join(" · "))}}</div>`:"";
  return `<article><div class="card-head"><h3>${{esc(tool.name)}}</h3><span class="status ${{esc(tool.status)}}">${{esc(labels[tool.status]||tool.status)}}</span></div>
    <p class="desc">${{esc(tool.description)}}</p>${{missing}}<div class="meta">Origen: ${{esc(tool.source)}}${{tool.pid?` · PID ${{esc(tool.pid)}}`:""}}</div>
    <div class="actions"><button type="button" data-start="${{esc(tool.id)}}" data-confirm="${{tool.confirmation_required}}" ${{canStart?"":"disabled"}}>Iniciar</button>
    <button type="button" class="secondary" data-stop="${{esc(tool.id)}}" ${{tool.stoppable?"":"disabled"}}>Detener</button></div></article>`;
}}
content.addEventListener("click",async event=>{{
  const start=event.target.closest("[data-start]"); const stop=event.target.closest("[data-stop]");
  if(!start&&!stop) return;
  const button=start||stop; button.disabled=true;
  try {{
    const id=start?start.dataset.start:stop.dataset.stop;
    let confirmed=false;
    if(start&&start.dataset.confirm==="true") {{ confirmed=window.confirm("Esta acción instala, repara o captura una muestra local. ¿Deseas continuar?"); if(!confirmed) return; }}
    const action=start?"start":"stop";
    const data=await request(`/api/tools/${{encodeURIComponent(id)}}/${{action}}`,{{method:"POST",body:JSON.stringify({{confirmed}})}});
    tell(data.result.outcome==="already_running"?"La herramienta ya estaba en ejecución.":"Acción procesada correctamente.");
  }} catch(error) {{ tell(error.message); }} finally {{ await load(); }}
}});
document.getElementById("refresh").addEventListener("click",load);
load(); setInterval(load,3000);
</script>
</body></html>"""
