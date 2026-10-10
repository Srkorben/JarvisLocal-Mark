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
  <title>Mark Scout</title>
  <style nonce="{safe_nonce}">
    :root {{ color-scheme:dark; --cyan:#69e6ff; --white:#eefaff; --muted:#79929c;
      --line:#183b48; --bad:#ff6e6e; }}
    * {{ box-sizing:border-box; }}
    html,body {{ width:100%; height:100%; margin:0; overflow:hidden; background:#010508;
      color:var(--white); font-family:"Segoe UI Variable","Segoe UI",sans-serif; }}
    button {{ font:inherit; }}
    #space {{ position:fixed; inset:0; width:100%; height:100%; }}
    .vignette {{ position:fixed; inset:0; pointer-events:none;
      background:radial-gradient(circle at 50% 48%,transparent 0 24%,#0004 58%,#000d 100%); }}
    .grain {{ position:fixed; inset:0; pointer-events:none; opacity:.055;
      background-image:url("data:image/svg+xml,%3Csvg viewBox='0 0 180 180' xmlns='http://www.w3.org/2000/svg%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='.95' numOctaves='3' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='.8'/%3E%3C/svg%3E"); }}
    .app {{ position:relative; z-index:2; height:100%; display:grid; grid-template-rows:auto 1fr auto;
      padding:clamp(18px,3vw,38px); }}
    header {{ display:flex; align-items:center; justify-content:space-between; gap:18px; }}
    .brand {{ display:flex; align-items:center; gap:12px; text-transform:uppercase; letter-spacing:.22em;
      font-size:12px; font-weight:650; }}
    .sigil {{ width:31px; height:31px; border:1px solid #69e6ff88; display:grid; place-items:center;
      clip-path:polygon(50% 0,93% 25%,93% 75%,50% 100%,7% 75%,7% 25%); color:var(--cyan);
      background:#071a22; box-shadow:0 0 24px #19bce555; }}
    .privacy {{ display:flex; align-items:center; gap:8px; color:#8aa0a9; font-size:11px;
      text-transform:uppercase; letter-spacing:.12em; }}
    .dot {{ width:6px; height:6px; border-radius:50%; background:var(--cyan); box-shadow:0 0 12px var(--cyan); }}
    .menu {{ border:1px solid #1b4452; background:#061117aa; color:#a8c6d0; padding:9px 13px;
      border-radius:3px; cursor:pointer; text-transform:uppercase; font-size:11px; letter-spacing:.12em; }}
    .menu:hover,.menu:focus-visible {{ color:white; border-color:var(--cyan); outline:none; }}
    .stage {{ min-height:0; display:grid; grid-template-columns:minmax(230px,1fr) minmax(360px,640px) minmax(230px,1fr);
      align-items:center; gap:clamp(16px,4vw,70px); }}
    .telemetry {{ align-self:center; color:#75909a; font-size:11px; letter-spacing:.11em;
      text-transform:uppercase; line-height:2; }}
    .telemetry strong {{ display:block; color:#c6eef7; font-size:17px; font-weight:400; letter-spacing:.03em;
      text-transform:none; line-height:1.25; }}
    .telemetry .rule {{ width:100%; max-width:210px; height:1px; margin:13px 0;
      background:linear-gradient(90deg,#35ccec88,transparent); }}
    .right {{ text-align:right; }} .right .rule {{ margin-left:auto;
      background:linear-gradient(270deg,#35ccec88,transparent); }}
    .module-link {{ display:block; width:100%; padding:8px 7px; margin:0 -7px; border:1px solid transparent;
      background:transparent; color:inherit; text-align:left; cursor:pointer; transition:.18s; }}
    .module-link span {{ display:block; }} .right .module-link {{ text-align:right; }}
    .module-link:hover,.module-link:focus-visible {{ outline:none; border-color:#27667888;
      background:#071b2355; color:#9dc2cd; transform:translateX(4px); }}
    .right .module-link:hover,.right .module-link:focus-visible {{ transform:translateX(-4px); }}
    .core-wrap {{ position:relative; aspect-ratio:1; display:grid; place-items:center; }}
    .core-glow {{ position:absolute; width:54%; aspect-ratio:1; border-radius:50%;
      background:radial-gradient(circle,#dfffff 0 2%,#76edff 3% 7%,#18b9dc55 12% 31%,transparent 64%);
      filter:blur(1px); opacity:.72; transition:.35s; }}
    .ring {{ position:absolute; border-radius:50%; border:1px solid #36c7e855; box-shadow:inset 0 0 25px #27c7e516,0 0 22px #27c7e512; }}
    .r1 {{ width:71%; height:71%; border-style:dashed; animation:spin 19s linear infinite; }}
    .r2 {{ width:56%; height:56%; border-width:2px; border-color:#79efff44; animation:spin-rev 12s linear infinite; }}
    .r3 {{ width:39%; height:39%; border-style:dotted; animation:spin 7s linear infinite; }}
    .ticks {{ position:absolute; width:84%; height:84%; border-radius:50%; opacity:.55;
      background:repeating-conic-gradient(from 0deg,#70eaff 0 1deg,transparent 1deg 5deg);
      -webkit-mask:radial-gradient(transparent 0 47%,#000 48% 50%,transparent 51%); }}
    .core-label {{ z-index:2; text-align:center; pointer-events:none; width:62%; }}
    #stateTitle {{ font-size:clamp(13px,1.5vw,18px); text-transform:uppercase; letter-spacing:.28em;
      color:#d8f9ff; text-shadow:0 0 18px #64e6ff; }}
    #stateHint {{ margin-top:9px; color:#6e929d; font-size:11px; letter-spacing:.08em; line-height:1.5; }}
    body[data-state="recording"] .core-glow {{ transform:scale(1.14); opacity:1; filter:hue-rotate(130deg); }}
    body[data-state="speaking"] .core-glow {{ opacity:1; animation:breathe .7s ease-in-out infinite alternate; }}
    body[data-state="processing"] .r2 {{ animation-duration:2s; }}
    body[data-state="error"] .ring {{ border-color:#ff686877; }}
    .conversation {{ position:absolute; left:50%; bottom:clamp(100px,14vh,155px); transform:translateX(-50%);
      width:min(760px,calc(100vw - 48px)); text-align:center; pointer-events:none; }}
    .line {{ min-height:22px; margin:7px 0; opacity:0; transform:translateY(5px); transition:.3s; }}
    .line.visible {{ opacity:1; transform:none; }}
    .who {{ color:#527984; font-size:10px; text-transform:uppercase; letter-spacing:.2em; margin-right:8px; }}
    #transcript {{ color:#9fb5bc; font-size:clamp(13px,1.4vw,16px); }}
    #response {{ color:#effdff; font-size:clamp(16px,1.8vw,22px); text-shadow:0 0 16px #32bee733; }}
    footer {{ display:flex; align-items:flex-end; justify-content:space-between; gap:18px; }}
    .keys {{ color:#58747e; font-size:10px; letter-spacing:.1em; text-transform:uppercase; line-height:1.8; }}
    kbd {{ color:#a8d5de; border:1px solid #204753; border-bottom-color:#317083; border-radius:3px;
      padding:2px 6px; background:#071116; font-family:inherit; }}
    .controls {{ display:flex; align-items:center; gap:10px; }}
    .primary,.stop {{ border:1px solid #23849c; background:#06232cdd; color:#cbf7ff; padding:12px 18px;
      border-radius:3px; cursor:pointer; text-transform:uppercase; font-size:11px; letter-spacing:.13em; }}
    .primary:hover {{ border-color:#61e7ff; box-shadow:0 0 24px #28cce52b; }}
    .stop {{ border-color:#613636; background:#211010cc; color:#f0b3b3; }}
    .stop:disabled,.primary:disabled {{ opacity:.35; cursor:not-allowed; }}
    .version {{ color:#36535c; font-size:10px; letter-spacing:.1em; text-transform:uppercase; text-align:right; }}
    #drawer {{ position:fixed; z-index:8; inset:0 0 0 auto; width:min(520px,100%); padding:26px;
      background:#040a0def; border-left:1px solid #1b4553; backdrop-filter:blur(22px); transform:translateX(102%);
      transition:transform .28s ease; overflow:auto; box-shadow:-30px 0 80px #000a; }}
    #drawer.open {{ transform:none; }}
    .drawer-head {{ display:flex; justify-content:space-between; align-items:center; border-bottom:1px solid #15343e;
      padding-bottom:18px; margin-bottom:20px; }}
    .drawer-head h2 {{ margin:0; text-transform:uppercase; letter-spacing:.18em; font-size:14px; }}
    .close {{ border:0; background:transparent; color:#8cb0bb; font-size:22px; cursor:pointer; }}
    .category {{ margin:24px 0 9px; color:#4e7985; text-transform:uppercase; letter-spacing:.17em; font-size:10px; }}
    .tool {{ border:1px solid #143641; background:#071116; padding:14px; margin:8px 0; }}
    .tool-head {{ display:flex; justify-content:space-between; gap:12px; }}
    .tool h3 {{ margin:0; font-size:14px; font-weight:500; }}
    .tool p {{ color:#718a93; margin:8px 0; font-size:12px; line-height:1.45; }}
    .status {{ color:#5f8793; text-transform:uppercase; letter-spacing:.1em; font-size:9px; }}
    .status.running {{ color:var(--cyan); }} .status.error,.status.unavailable {{ color:#d78383; }}
    .tool-actions {{ display:flex; gap:7px; margin-top:10px; }}
    .tool-actions button {{ border:1px solid #235363; background:#0a1a20; color:#a9cbd5; padding:7px 10px;
      border-radius:2px; cursor:pointer; font-size:10px; text-transform:uppercase; letter-spacing:.08em; }}
    .tool-actions button:disabled {{ opacity:.3; cursor:not-allowed; }}
    .voice-note {{ color:#526f78; flex-basis:100%; font-size:10px; line-height:1.45; margin-top:2px; }}
    #notice {{ position:fixed; z-index:12; left:50%; bottom:24px; transform:translate(-50%,15px); opacity:0;
      background:#dff9ff; color:#031015; padding:11px 16px; font-size:12px; letter-spacing:.03em;
      box-shadow:0 10px 40px #000; transition:.2s; pointer-events:none; }}
    #notice.show {{ opacity:1; transform:translate(-50%,0); }}
    #modulePanel {{ position:fixed; z-index:10; inset:0; display:grid; place-items:center; padding:34px;
      background:#010508e8; backdrop-filter:blur(18px); opacity:0; pointer-events:none; transition:.22s; }}
    #modulePanel.open {{ opacity:1; pointer-events:auto; }}
    .module-shell {{ width:min(980px,96vw); max-height:88vh; overflow:auto; border:1px solid #245b69;
      background:#040b0fef; box-shadow:0 28px 100px #000,0 0 70px #1fcbe615; padding:clamp(22px,4vw,48px); }}
    .module-top {{ display:flex; align-items:flex-start; justify-content:space-between; gap:24px;
      padding-bottom:22px; border-bottom:1px solid #163a45; }}
    .module-eyebrow {{ color:#55bed3; font-size:10px; letter-spacing:.2em; text-transform:uppercase; }}
    #moduleTitle {{ margin:8px 0 0; font-size:clamp(30px,5vw,58px); font-weight:300; letter-spacing:.04em; }}
    #moduleStatus {{ display:inline-block; margin-top:12px; border:1px solid #2a6574; color:#9ddce8;
      padding:5px 8px; font-size:9px; letter-spacing:.13em; text-transform:uppercase; }}
    #moduleSummary {{ color:#d8f5fa; font-size:clamp(16px,2vw,22px); line-height:1.45; margin:26px 0 8px; }}
    #moduleDescription {{ color:#7897a0; line-height:1.65; max-width:820px; }}
    .module-columns {{ display:grid; grid-template-columns:1.1fr .9fr; gap:34px; margin-top:30px; }}
    .module-section.spaced {{ margin-top:25px; }}
    .module-section h3 {{ color:#4f7e8b; text-transform:uppercase; font-size:10px; letter-spacing:.18em;
      margin:0 0 13px; }}
    .facts {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:8px; }}
    .fact {{ padding:12px; border:1px solid #133641; background:#061116; min-height:70px; }}
    .fact span {{ display:block; color:#50717a; font-size:9px; letter-spacing:.12em; text-transform:uppercase; }}
    .fact strong {{ display:block; color:#c9edf4; font-size:13px; font-weight:450; margin-top:7px; word-break:break-word; }}
    .module-list {{ margin:0; padding:0; list-style:none; }}
    .module-list li {{ color:#89a5ad; font-size:12px; line-height:1.5; padding:7px 0 7px 18px; position:relative; }}
    .module-list li::before {{ content:'+'; position:absolute; left:0; color:#4ccde7; }}
    .module-list.limits li::before {{ content:'–'; color:#b17878; }}
    .quality {{ display:flex; flex-wrap:wrap; gap:8px; margin-top:12px; }}
    .quality button {{ border:1px solid #22515e; color:#84aab4; background:#07151a; padding:8px 12px;
      text-transform:uppercase; font-size:9px; letter-spacing:.1em; cursor:pointer; }}
    .quality button.active {{ border-color:#63dff5; color:#e7fbff; box-shadow:0 0 18px #3bd7ef22; }}
    .quality-note {{ color:#536e76; font-size:11px; line-height:1.5; margin-top:10px; }}
    body[data-quality="eco"] .grain,body[data-quality="paused"] .grain {{ display:none; }}
    body[data-quality="eco"] .ticks {{ opacity:.22; }}
    #chat {{ position:fixed; z-index:5; left:clamp(12px,2vw,32px); top:clamp(70px,9vh,92px);
      bottom:clamp(86px,12vh,118px); width:min(430px,calc(100vw - 24px)); display:none; flex-direction:column;
      border:1px solid #1d4b59; background:#040b0fe6; backdrop-filter:blur(16px);
      box-shadow:0 24px 70px #000b,0 0 40px #1fcbe60f; }}
    body.chat-open #chat {{ display:flex; }}
    body.chat-open .conversation {{ display:none; }}
    .chat-head {{ display:flex; align-items:center; gap:10px; padding:12px 14px; border-bottom:1px solid #15343e; }}
    .chat-head h2 {{ margin:0; flex:1; text-transform:uppercase; letter-spacing:.18em; font-size:12px; font-weight:600; }}
    #chatRuntime {{ color:#5f8793; text-transform:uppercase; letter-spacing:.1em; font-size:9px; }}
    #chatRuntime.on {{ color:var(--cyan); }}
    .chat-log {{ flex:1; min-height:0; overflow-y:auto; padding:14px; display:flex; flex-direction:column; gap:10px; }}
    .chat-empty {{ color:#557580; font-size:12px; line-height:1.6; margin:auto 0; text-align:center; }}
    .msg {{ max-width:92%; padding:10px 12px; border:1px solid #163a45; background:#071419; font-size:14px;
      line-height:1.5; white-space:pre-wrap; overflow-wrap:anywhere; }}
    .msg .who {{ display:block; margin:0 0 4px; }}
    .msg.user {{ align-self:flex-end; border-color:#23667a; background:#0a2029; color:#dff8ff; }}
    .msg.mark {{ align-self:flex-start; color:#effdff; }}
    .msg.pending .body:empty::after,.msg.pending .body > :last-child::after {{ content:'▍'; color:var(--cyan); animation:blink 1s steps(1) infinite; }}
    .msg.failed {{ border-color:#6b3434; background:#1c0c0c; color:#f3c0c0; }}
    .msg .meta {{ display:block; margin-top:6px; color:#5d7f89; font-size:10px; letter-spacing:.06em; }}
    .chat-status {{ min-height:20px; padding:0 14px; color:#7fb6c3; font-size:11px; letter-spacing:.04em; }}
    .chat-status.bad {{ color:#ff9b9b; }}
    #chatForm {{ border-top:1px solid #15343e; padding:12px 14px; display:grid; gap:9px; }}
    #chatInput {{ width:100%; resize:none; min-height:58px; max-height:160px; padding:10px; font:inherit; font-size:14px;
      color:var(--white); background:#061117; border:1px solid #1d4b59; border-radius:3px; }}
    #chatInput:focus {{ outline:none; border-color:var(--cyan); box-shadow:0 0 0 1px #69e6ff44; }}
    .chat-row {{ display:flex; align-items:center; gap:8px; }}
    .chat-row label {{ flex:1; color:#86a9b3; font-size:11px; display:flex; align-items:center; gap:6px; cursor:pointer; }}
    .chat-row .primary,.chat-row .stop {{ padding:9px 13px; }}
    @keyframes blink {{ 50% {{ opacity:0; }} }}
    body.chat-open .stage > .telemetry:first-child {{ visibility:hidden; }}
    body.chat-wide #chat {{ width:min(980px,calc(100vw - 24px)); }}
    body.chat-wide .core-wrap {{ opacity:.3; }}
    #chatWide {{ border:1px solid #1b4452; background:transparent; color:#8cb0bb; cursor:pointer;
      font-size:10px; letter-spacing:.1em; text-transform:uppercase; padding:5px 8px; border-radius:2px; }}
    #chatWide:hover,#chatWide:focus-visible {{ color:white; border-color:var(--cyan); outline:none; }}
    .msg.mark .body {{ display:block; white-space:normal; }}
    .msg.mark .body p {{ margin:0 0 .6em; }}
    .msg.mark .body > :last-child {{ margin-bottom:0; }}
    .msg.mark .body ul,.msg.mark .body ol {{ margin:.2em 0 .6em; padding-left:1.35em; }}
    .msg.mark .body li {{ margin:.18em 0; }}
    .msg.mark .body strong {{ color:#ffffff; font-weight:600; }}
    .msg.mark .body .md-h {{ color:#9eeeff; font-weight:600; letter-spacing:.02em; }}
    .msg.mark .body code {{ font-family:Consolas,"Cascadia Mono",monospace; font-size:.92em; background:#0b2530;
      border:1px solid #17404d; padding:0 4px; border-radius:2px; }}
    .msg.mark .body pre {{ margin:.3em 0 .7em; padding:9px 10px; overflow-x:auto; background:#030b0f;
      border:1px solid #17404d; white-space:pre; }}
    .msg.mark .body pre code {{ background:transparent; border:0; padding:0; }}
    @keyframes spin {{ to {{ transform:rotate(360deg); }} }}
    @keyframes spin-rev {{ to {{ transform:rotate(-360deg); }} }}
    @keyframes breathe {{ to {{ transform:scale(1.1); }} }}
    @media (max-width:950px) {{ .stage {{ grid-template-columns:1fr; }} .telemetry {{ display:none; }}
      .core-wrap {{ width:min(70vh,84vw); margin:auto; }} .module-columns {{ grid-template-columns:1fr; }} }}
    @media (max-width:620px) {{ #modulePanel {{ padding:10px; }} .facts {{ grid-template-columns:1fr; }} }}
    @media (max-height:690px) {{ .conversation {{ bottom:86px; }} .core-wrap {{ max-height:62vh; }} }}
    @media (prefers-reduced-motion:reduce) {{ *,*::before,*::after {{ animation-duration:.001ms!important;
      animation-iteration-count:1!important; scroll-behavior:auto!important; }} }}
  </style>
</head>
<body data-state="offline">
<canvas id="space" aria-hidden="true"></canvas><div class="vignette"></div><div class="grain"></div>
<div class="app">
  <header>
    <div class="brand"><div class="sigil">M</div><span>Mark Scout</span></div>
    <div class="privacy"><span class="dot"></span><span>núcleo local · 127.0.0.1</span></div>
    <div class="controls"><button id="chatToggle" class="menu" type="button" aria-controls="chat" aria-expanded="false">Chat</button>
      <button id="menu" class="menu" type="button">Sistemas</button></div>
  </header>
  <main class="stage">
    <aside class="telemetry" aria-label="Módulos principales">
      <button class="module-link" data-module="interface" type="button"><span>Interfaz</span><strong>Experiencia adaptativa</strong></button><div class="rule"></div>
      <button class="module-link" data-module="authority" type="button"><span>Autoridad</span><strong>Control de acciones</strong></button><div class="rule"></div>
      <button class="module-link" data-module="audio" type="button"><span>Audio</span><strong>Pulsar para hablar</strong></button>
    </aside>
    <section class="core-wrap" aria-live="polite">
      <div class="ticks"></div><div class="ring r1"></div><div class="ring r2"></div><div class="ring r3"></div>
      <div class="core-glow"></div><div class="core-label"><div id="stateTitle">Sistema desconectado</div>
      <div id="stateHint">Inicia el núcleo de voz para comenzar</div></div>
    </section>
    <aside class="telemetry right" aria-label="Módulos del núcleo">
      <button class="module-link" data-module="model" type="button"><span>Modelo</span><strong>Qwen3 · Local</strong></button><div class="rule"></div>
      <button class="module-link" data-module="memory" type="button"><span>Memoria</span><strong>Proyecto aislado</strong></button><div class="rule"></div>
      <button class="module-link" data-module="security" type="button"><span>Seguridad</span><strong>Auditoría activa</strong></button>
    </aside>
  </main>
  <div class="conversation">
    <div id="userLine" class="line"><span class="who">Tú</span><span id="transcript"></span></div>
    <div id="jarvisLine" class="line"><span class="who">Mark</span><span id="response"></span></div>
  </div>
  <footer>
    <div class="keys">Mantén <kbd>Ctrl</kbd> + <kbd>Alt</kbd> + <kbd>M</kbd> para hablar<br>
      <kbd>Ctrl</kbd> + <kbd>Alt</kbd> + <kbd>Pause</kbd> cancela el turno</div>
    <div class="controls"><button id="voiceStart" class="primary" type="button">Iniciar voz</button>
      <button id="voiceStop" class="stop" type="button" disabled>Detener núcleo</button></div>
    <div class="version">{safe_version}<br>Privado por diseño</div>
  </footer>
</div>
<section id="chat" aria-label="Conversación escrita con Mark">
  <div class="chat-head"><h2>Conversación</h2><span id="chatRuntime">Núcleo apagado</span>
    <button id="chatWide" type="button" aria-pressed="false" title="Ampliar o reducir el área de conversación">Ampliar</button>
    <button id="chatClose" class="close" type="button" aria-label="Cerrar chat">×</button></div>
  <div id="chatLog" class="chat-log" aria-live="polite"><p class="chat-empty">Escribe una instrucción para Mark.
    El núcleo de texto se inicia al enviar el primer mensaje.<br>La conversación de esta ventana no se guarda en el navegador.</p></div>
  <div id="chatStatus" class="chat-status" role="status"></div>
  <form id="chatForm" autocomplete="off">
    <textarea id="chatInput" maxlength="4000" rows="2" placeholder="Escribe a Mark… (Enter envía, Mayús+Enter salto de línea)" aria-label="Mensaje para Mark"></textarea>
    <div class="chat-row"><label><input id="chatSpeak" type="checkbox"> Responder también con voz</label>
      <button id="chatCancel" class="stop" type="button" disabled>Cancelar</button>
      <button id="chatSend" class="primary" type="submit">Enviar</button></div>
  </form>
</section>
<aside id="drawer" aria-label="Sistemas y herramientas"><div class="drawer-head"><h2>Sistemas</h2>
  <button id="closeDrawer" class="close" type="button" aria-label="Cerrar">×</button></div><div id="tools"></div></aside>
<section id="modulePanel" aria-label="Detalle del módulo" aria-hidden="true" inert>
  <article class="module-shell">
    <div class="module-top"><div><div class="module-eyebrow">Subsistema de Mark Scout</div>
      <h2 id="moduleTitle">Módulo</h2><span id="moduleStatus"></span></div>
      <button id="closeModule" class="close" type="button" aria-label="Regresar a la pantalla principal">×</button>
    </div>
    <div id="moduleSummary"></div><div id="moduleDescription"></div>
    <div class="module-columns">
      <section class="module-section"><h3>Estado y configuración actual</h3><div id="moduleFacts" class="facts"></div>
        <div id="moduleControls"></div></section>
      <section><div class="module-section"><h3>Capacidades disponibles</h3><ul id="moduleCapabilities" class="module-list"></ul></div>
        <div class="module-section spaced"><h3>Límites actuales</h3><ul id="moduleLimits" class="module-list limits"></ul></div></section>
    </div>
  </article>
</section>
<input id="voiceFileInput" type="file" hidden
  accept=".wav,.mp3,.m4a,.flac,.ogg,.opus,.aac,.wma,audio/*">
<div id="notice" role="status"></div>
<script nonce="{safe_nonce}">
const csrf="{csrf}";
const stateText={{offline:["Sistema desconectado","Escribe en el chat o inicia la voz para comenzar"],loading:["Inicializando","Cargando modelos locales de voz"],idle:["En espera","Escribe en el chat o usa la voz si está activa"],queued:["En cola","Preparando el núcleo local"],
recording:["Escuchando","Suelta la combinación para enviar"],transcribing:["Interpretando voz","Transcripción local en curso"],
processing:["Procesando","Consultando el núcleo local"],speaking:["Respondiendo","Síntesis de voz activa"],
cancelling:["Cancelando","Interrumpiendo el turno actual"],error:["Incidencia detectada","Consulta el detalle en pantalla"]}};
const labels={{available:"Disponible",running:"Activo",unavailable:"No disponible",error:"Error"}};
let currentState="offline",toolsCache=[],modulesCache=[],visualQuality="auto",lastFrame=0;
try{{visualQuality=localStorage.getItem("mark.visualQuality")||"auto";}}catch(_){{}}
if(!["auto","balanced","eco"].includes(visualQuality))visualQuality="auto";
const $=id=>document.getElementById(id),notice=$("notice"),drawer=$("drawer"),modulePanel=$("modulePanel");
function esc(value){{const node=document.createElement("span");node.textContent=String(value??"");return node.innerHTML;}}
function tell(message){{notice.textContent=message;notice.classList.add("show");setTimeout(()=>notice.classList.remove("show"),3600);}}
async function request(url,options={{}}){{const response=await fetch(url,{{credentials:"same-origin",...options,
headers:{{"X-CSRF-Token":csrf,"Content-Type":"application/json",...(options.headers||{{}})}}}});
const data=await response.json().catch(()=>({{error:{{message:"Respuesta local inválida."}}}}));
if(!response.ok)throw new Error(data.error?.message||"La acción falló.");return data;}}
function effectiveQuality(){{if(document.hidden)return "paused";if(visualQuality!=="auto")return visualQuality;
return ["processing","transcribing","loading"].includes(currentState)?"eco":"balanced";}}
function applyVisualQuality(){{document.body.dataset.quality=effectiveQuality();}}
let lastPresenceRevision=-1;
function setPresence(p){{if(typeof p.revision==="number")lastPresenceRevision=p.revision;const before=effectiveQuality();currentState=p.state||"offline";document.body.dataset.state=currentState;applyVisualQuality();if(before!==effectiveQuality())resize();
const copy=stateText[currentState]||stateText.offline;$("stateTitle").textContent=copy[0];$("stateHint").textContent=p.error||copy[1];
$("transcript").textContent=p.transcript||"";$("response").textContent=p.response||"";
$("userLine").classList.toggle("visible",Boolean(p.transcript));$("jarvisLine").classList.toggle("visible",Boolean(p.response));chatPresence(p);}}
let presenceFailures=0;
async function loadPresence(){{try{{const data=await request("/api/voice/presence");presenceFailures=0;setPresence(data.presence);}}
catch(_){{presenceFailures++;if(presenceFailures>=8)chatDisconnected();else return;setPresence({{state:"offline"}});}}}}
async function loadTools(){{try{{const data=await request("/api/tools");toolsCache=data.tools;renderTools();
const voice=toolsCache.find(t=>t.id==="voice"),running=voice?.status==="running";
$("voiceStart").disabled=!voice||running||voice.status==="unavailable";$("voiceStop").disabled=!running;chatRuntimeLabel();}}
catch(error){{tell(error.message);}}}}
async function loadModules(){{try{{const data=await request("/api/modules");modulesCache=data.modules||[];
document.title=data.identity?.display_name||"Mark Scout";}}catch(error){{tell(error.message);}}}}
function renderTools(){{const groups={{}};for(const tool of toolsCache)(groups[tool.category]??=[]).push(tool);
$("tools").innerHTML=Object.entries(groups).map(([category,items])=>`<div class="category">${{esc(category)}}</div>${{items.map(toolCard).join("")}}`).join("");}}
function toolCard(t){{const canStart=t.status==="available"||t.status==="error";
const actions=t.id==="enroll_voice"?`<button data-start="${{esc(t.id)}}" data-confirm="${{t.confirmation_required}}" ${{canStart?"":"disabled"}}>Grabar 20 s</button>
<button data-upload-voice ${{canStart?"":"disabled"}}>Subir audio</button><button data-stop="${{esc(t.id)}}" ${{t.stoppable?"":"disabled"}}>Detener</button>
<div class="voice-note">WAV, MP3, M4A, FLAC, OGG, OPUS, AAC o WMA · 15–30 s · máximo 24 MiB. La muestra permanece local y sustituye la referencia activa con respaldo.</div>`:
`<button data-start="${{esc(t.id)}}" data-confirm="${{t.confirmation_required}}" ${{canStart?"":"disabled"}}>Iniciar</button>
<button data-stop="${{esc(t.id)}}" ${{t.stoppable?"":"disabled"}}>Detener</button>`;
return `<article class="tool"><div class="tool-head"><h3>${{esc(t.name)}}</h3>
<span class="status ${{esc(t.status)}}">${{esc(labels[t.status]||t.status)}}</span></div><p>${{esc(t.description)}}</p>
<div class="tool-actions">${{actions}}</div></article>`;}}
function openModule(id){{const m=modulesCache.find(item=>item.id===id);if(!m){{tell("El módulo aún no está disponible.");return;}}
$("moduleTitle").textContent=m.label;$("moduleStatus").textContent=m.status_label;$("moduleSummary").textContent=m.summary;
$("moduleDescription").textContent=m.description;$("moduleFacts").innerHTML=(m.facts||[]).map(f=>`<div class="fact"><span>${{esc(f[0])}}</span><strong>${{esc(f[1])}}</strong></div>`).join("");
$("moduleCapabilities").innerHTML=(m.capabilities||[]).map(v=>`<li>${{esc(v)}}</li>`).join("");
$("moduleLimits").innerHTML=(m.limitations||[]).map(v=>`<li>${{esc(v)}}</li>`).join("");
$("moduleControls").innerHTML=(m.controls||[]).includes("visual_quality")?`<div class="module-section spaced"><h3>Calidad visual operativa</h3>
<div class="quality"><button data-quality="auto">Auto</button><button data-quality="balanced">Equilibrado</button><button data-quality="eco">Eco</button></div>
<p class="quality-note">Auto reduce resolución, partículas y FPS durante inferencia; Eco minimiza uso gráfico. Esta preferencia solo afecta la interfaz.</p></div>`:"";
modulePanel.classList.add("open");modulePanel.removeAttribute("inert");modulePanel.setAttribute("aria-hidden","false");refreshQualityButtons();}}
function closeModule(){{modulePanel.classList.remove("open");modulePanel.setAttribute("inert","");modulePanel.setAttribute("aria-hidden","true");}}
function refreshQualityButtons(){{document.querySelectorAll("[data-quality]").forEach(b=>b.classList.toggle("active",b.dataset.quality===visualQuality));}}
function setVisualQuality(value){{if(!["auto","balanced","eco"].includes(value))return;visualQuality=value;
try{{localStorage.setItem("mark.visualQuality",value);}}catch(_){{}}applyVisualQuality();resize();refreshQualityButtons();}}
async function toolAction(id,action,confirmed=false){{const data=await request(`/api/tools/${{encodeURIComponent(id)}}/${{action}}`,
{{method:"POST",body:JSON.stringify({{confirmed}})}});await loadTools();return data.result;}}
$("voiceStart").addEventListener("click",async()=>{{try{{await toolAction("voice","start");tell("Núcleo de voz iniciado.");}}catch(e){{tell(e.message);}}}});
$("voiceStop").addEventListener("click",async()=>{{try{{await toolAction("voice","stop");setPresence({{state:"offline"}});tell("Núcleo de voz detenido.");}}catch(e){{tell(e.message);}}}});
$("menu").addEventListener("click",()=>drawer.classList.add("open"));$("closeDrawer").addEventListener("click",()=>drawer.classList.remove("open"));
document.querySelectorAll("[data-module]").forEach(button=>button.addEventListener("click",()=>openModule(button.dataset.module)));
$("closeModule").addEventListener("click",closeModule);modulePanel.addEventListener("click",event=>{{if(event.target===modulePanel)closeModule();}});
modulePanel.addEventListener("click",event=>{{const button=event.target.closest("[data-quality]");if(button)setVisualQuality(button.dataset.quality);}});
addEventListener("keydown",event=>{{if(event.key==="Escape"){{closeModule();drawer.classList.remove("open");}}}});
function bytesToBase64(buffer){{const bytes=new Uint8Array(buffer);let binary="";for(let offset=0;offset<bytes.length;offset+=32768){{
binary+=String.fromCharCode(...bytes.subarray(offset,Math.min(offset+32768,bytes.length)));}}return btoa(binary);}}
async function importVoiceFile(file){{if(file.size>24*1024*1024)throw new Error("El audio supera 24 MiB.");
const extension=(file.name.match(/\\.[^.]+$/)||[""])[0].toLowerCase();
if(![".wav",".mp3",".m4a",".flac",".ogg",".opus",".aac",".wma"].includes(extension))throw new Error("Formato de audio no admitido.");
const authorized=window.confirm("La muestra permanecerá en este PC y reemplazará la referencia activa conservando un respaldo. Confirma que eres titular de la voz o que tienes autorización del titular para usarla en síntesis local.");
if(!authorized)return;const buffer=await file.arrayBuffer();tell("Validando e importando la muestra local…");
const data=await request("/api/voice/reference/import",{{method:"POST",body:JSON.stringify({{filename:file.name,audio_base64:bytesToBase64(buffer),authorization_confirmed:true,replace_existing:true}})}});
await loadTools();tell(`Muestra importada: ${{Number(data.result.duration_seconds).toFixed(1)}} s. No se entrenaron pesos; se actualizó la referencia local.`);}}
$("tools").addEventListener("click",async event=>{{const upload=event.target.closest("[data-upload-voice]");
if(upload){{$("voiceFileInput").click();return;}}const start=event.target.closest("[data-start]"),stop=event.target.closest("[data-stop]");if(!start&&!stop)return;
const button=start||stop;button.disabled=true;try{{const id=start?start.dataset.start:stop.dataset.stop;let confirmed=false;
if(start&&start.dataset.confirm==="true"){{confirmed=window.confirm("Esta acción requiere confirmación local explícita. ¿Deseas continuar?");if(!confirmed)return;}}
await toolAction(id,start?"start":"stop",confirmed);tell("Acción procesada.");}}catch(e){{tell(e.message);}}finally{{button.disabled=false;}}}});
$("voiceFileInput").addEventListener("change",async event=>{{const file=event.target.files?.[0];event.target.value="";if(!file)return;
try{{await importVoiceFile(file);}}catch(error){{tell(error.message);}}}});
// --- Chat escrito: /api/chat encola; la presencia trae la respuesta progresiva ---
const CHAT_MAX=4000,CHAT_STALL_MS=150000,chatLog=$("chatLog"),chatInput=$("chatInput");
let turn=null;
function chatNormalize(text){{return text.trim().split(/\\s+/).join(" ");}}
function chatStatus(text,bad=false){{const node=$("chatStatus");node.textContent=text;node.classList.toggle("bad",bad);}}
function chatAdd(role,text,extra=""){{chatLog.querySelector(".chat-empty")?.remove();const msg=document.createElement("div");
msg.className=`msg ${{role}} ${{extra}}`.trim();const who=document.createElement("span");who.className="who";who.textContent=role==="user"?"Tú":"Mark";
const body=document.createElement("span");body.className="body";body.textContent=text;msg.append(who,body);chatLog.append(msg);
chatLog.scrollTop=chatLog.scrollHeight;return msg;}}
function chatMeta(msg,text){{const meta=document.createElement("span");meta.className="meta";meta.textContent=text;msg.append(meta);}}
function chatButtons(){{$("chatSend").disabled=Boolean(turn);$("chatCancel").disabled=!turn||turn.cancelRequested;}}
// Markdown mínimo y seguro: solo crea nodos con textContent; nunca innerHTML.
function mdInline(text,parent){{const re=/(\\*\\*([^*]+)\\*\\*|`([^`]+)`|\\*([^*\\s][^*]*)\\*)/g;let last=0,m;
while((m=re.exec(text))){{if(m.index>last)parent.append(document.createTextNode(text.slice(last,m.index)));let node;
if(m[2]!==undefined){{node=document.createElement("strong");mdInline(m[2],node);}}
else if(m[3]!==undefined){{node=document.createElement("code");node.textContent=m[3];}}
else{{node=document.createElement("em");mdInline(m[4],node);}}parent.append(node);last=re.lastIndex;}}
if(last<text.length)parent.append(document.createTextNode(text.slice(last)));}}
function mdRender(text,target){{target.replaceChildren();const lines=String(text).replace(/\\r\\n?/g,"\\n").split("\\n");let i=0,para=[],list=null;
const flush=()=>{{if(para.length){{const p=document.createElement("p");mdInline(para.join(" "),p);target.append(p);para=[];}}}};
while(i<lines.length){{const line=lines[i];
if(/^\\s*```/.test(line)){{flush();list=null;const code=[];i++;while(i<lines.length&&!/^\\s*```/.test(lines[i])){{code.push(lines[i]);i++;}}i++;
const pre=document.createElement("pre"),c=document.createElement("code");c.textContent=code.join("\\n");pre.append(c);target.append(pre);continue;}}
const heading=line.match(/^\\s*#{{1,6}}\\s+(.*)$/);
if(heading){{flush();list=null;const h=document.createElement("p");h.className="md-h";mdInline(heading[1],h);target.append(h);i++;continue;}}
const item=line.match(/^\\s*([-*+•]|\\d+[.)])\\s+(.*)$/);
if(item){{flush();const ordered=/\\d/.test(item[1]);if(!list||list.ordered!==ordered){{const el=document.createElement(ordered?"ol":"ul");
if(ordered){{const start=parseInt(item[1],10);if(start>1)el.start=start;}}target.append(el);list={{el,ordered}};}}
const li=document.createElement("li");mdInline(item[2],li);list.el.append(li);i++;continue;}}
if(!line.trim()){{flush();list=null;i++;continue;}}
if(list&&/^\\s{{2,}}\\S/.test(line)){{const li=list.el.lastElementChild;li.append(document.createTextNode(" "));mdInline(line.trim(),li);i++;continue;}}
list=null;para.push(line.trim());i++;}}flush();}}
function chatSetText(text){{if(!turn||!text)return;const near=chatLog.scrollHeight-chatLog.scrollTop-chatLog.clientHeight<60;
mdRender(text,turn.bubble.querySelector(".body"));turn.rendered=text;if(near)chatLog.scrollTop=chatLog.scrollHeight;}}
function chatFinish(kind,detail=""){{if(!turn)return;const t=turn;turn=null;t.bubble.classList.remove("pending");
const seconds=((Date.now()-t.startedAt)/1000).toFixed(1);
if(kind==="error"){{t.bubble.classList.add("failed");if(!t.bubble.querySelector(".body").textContent)chatSetTextOn(t,detail);chatMeta(t.bubble,`Error · ${{seconds}} s`);chatStatus(detail,true);}}
else if(kind==="cancelled"){{chatMeta(t.bubble,`Cancelado · ${{seconds}} s`);chatStatus("Turno cancelado.");}}
else{{if(!t.bubble.querySelector(".body").textContent)chatSetTextOn(t,"(Mark no devolvió texto)");chatMeta(t.bubble,`${{seconds}} s`);chatStatus("");}}
chatButtons();chatInput.focus();}}
function chatSetTextOn(t,text){{t.bubble.querySelector(".body").textContent=text;}}
function chatWide(wide){{document.body.classList.toggle("chat-wide",wide);$("chatWide").setAttribute("aria-pressed",String(wide));
$("chatWide").textContent=wide?"Reducir":"Ampliar";try{{localStorage.setItem("mark.chatWide",wide?"1":"0");}}catch(_){{}}}}
function chatPresence(p){{if(!turn)return;if(typeof p.revision==="number"&&p.revision<=turn.minRevision)return;
const state=p.state||"offline",now=Date.now();
if(p.transcript&&p.transcript!==turn.text&&!["queued","loading"].includes(state))return;
if(state!==turn.lastState){{turn.lastState=state;turn.lastChange=now;}}
if(p.response&&p.response!==turn.lastResponse){{turn.lastResponse=p.response;turn.lastChange=now;}}
if(["processing","speaking","transcribing"].includes(state)){{turn.active=true;if(p.response)chatSetText(p.response);
chatStatus(state==="speaking"?"Mark está hablando…":p.response?"Mark está escribiendo…":"Mark está pensando…");}}
else if(state==="queued")chatStatus("Mensaje en cola…");
else if(state==="loading")chatStatus("Iniciando el núcleo local (la primera vez tarda unos segundos)…");
else if(state==="cancelling")chatStatus("Cancelando…");
else if(state==="error")chatFinish("error",p.error||"El núcleo informó un error.");
else if(state==="idle"&&(turn.active||p.response)){{if(p.response)chatSetText(p.response);chatFinish(turn.cancelRequested?"cancelled":"done");return;}}
else if(state==="offline"&&now-turn.startedAt>4000)chatFinish("error","El núcleo se detuvo antes de responder.");
if(turn&&now-turn.lastChange>CHAT_STALL_MS)chatFinish("error","Sin respuesta del núcleo local. Puedes reintentar.");}}
function chatDisconnected(){{chatStatus("Sin conexión con el panel local. Reintentando…",true);
if(turn&&Date.now()-turn.lastChange>15000)chatFinish("error","Se perdió la conexión con el panel local.");}}
function chatRuntimeLabel(){{const byId=id=>toolsCache.find(t=>t.id===id);const voice=byId("voice"),chat=byId("chat_runtime"),node=$("chatRuntime");
const on=voice?.status==="running"?"Núcleo de voz activo":chat?.status==="running"?"Núcleo de texto activo":"";
node.textContent=on||"Núcleo apagado";node.classList.toggle("on",Boolean(on));}}
async function chatSend(){{if(turn)return;const text=chatNormalize(chatInput.value);
if(!text){{chatStatus("Escribe un mensaje antes de enviarlo.",true);return;}}
if(text.length>CHAT_MAX){{chatStatus(`El mensaje supera ${{CHAT_MAX}} caracteres.`,true);return;}}
const speak=$("chatSpeak").checked,minRevision=lastPresenceRevision;$("chatSend").disabled=true;chatStatus("Enviando…");
try{{await request("/api/chat",{{method:"POST",body:JSON.stringify({{text,speak}})}});}}
catch(error){{chatStatus(error.message,true);$("chatSend").disabled=false;return;}}
chatInput.value="";chatAdd("user",text);const now=Date.now();
turn={{text,bubble:chatAdd("mark","","pending"),startedAt:now,lastChange:now,lastState:"",lastResponse:"",active:false,cancelRequested:false,minRevision,rendered:""}};
chatStatus("Mensaje en cola…");chatButtons();loadTools();}}
async function chatCancel(){{if(!turn||turn.cancelRequested)return;turn.cancelRequested=true;chatButtons();chatStatus("Cancelando…");
try{{await request("/api/chat/cancel",{{method:"POST",body:"{{}}"}});}}catch(error){{chatStatus(error.message,true);}}}}
function chatOpen(open){{document.body.classList.toggle("chat-open",open);if(!open)document.body.classList.remove("chat-wide");
else{{let wide=false;try{{wide=localStorage.getItem("mark.chatWide")==="1";}}catch(_){{}}if(wide&&typeof chatWide==="function")document.body.classList.add("chat-wide");}}$("chatToggle").setAttribute("aria-expanded",String(open));
try{{localStorage.setItem("mark.chatOpen",open?"1":"0");}}catch(_){{}}if(open)chatInput.focus();}}
$("chatForm").addEventListener("submit",event=>{{event.preventDefault();chatSend();}});
chatInput.addEventListener("keydown",event=>{{if(event.key==="Enter"&&!event.shiftKey&&!event.isComposing){{event.preventDefault();chatSend();}}}});
$("chatCancel").addEventListener("click",chatCancel);
$("chatToggle").addEventListener("click",()=>chatOpen(!document.body.classList.contains("chat-open")));
$("chatClose").addEventListener("click",()=>chatOpen(false));
$("chatWide").addEventListener("click",()=>chatWide(!document.body.classList.contains("chat-wide")));
let chatInitiallyOpen=true;try{{chatInitiallyOpen=localStorage.getItem("mark.chatOpen")!=="0";}}catch(_){{}}
chatOpen(chatInitiallyOpen);chatButtons();
let chatInitiallyWide=false;try{{chatInitiallyWide=localStorage.getItem("mark.chatWide")==="1";}}catch(_){{}}chatWide(chatInitiallyWide);
const canvas=$("space"),ctx=canvas.getContext("2d",{{alpha:false}}),particles=Array.from({{length:95}},()=>({{x:Math.random(),y:Math.random(),z:Math.random(),s:.3+Math.random()}}));
function resize(){{const q=effectiveQuality(),cap=q==="eco"?1:1.35,d=Math.min(devicePixelRatio||1,cap);canvas.width=Math.max(1,innerWidth*d);canvas.height=Math.max(1,innerHeight*d);canvas.style.width=innerWidth+"px";canvas.style.height=innerHeight+"px";ctx.setTransform(d,0,0,d,0,0);}}
addEventListener("resize",resize);document.addEventListener("visibilitychange",()=>{{applyVisualQuality();resize();}});applyVisualQuality();resize();
function render(t){{requestAnimationFrame(render);const quality=effectiveQuality();if(quality==="paused")return;const fps=quality==="eco"?20:45;
if(t-lastFrame<1000/fps)return;lastFrame=t;const w=innerWidth,h=innerHeight,cx=w/2,cy=h*.47;ctx.clearRect(0,0,w,h);
const grad=ctx.createRadialGradient(cx,cy,0,cx,cy,Math.max(w,h)*.72);grad.addColorStop(0,"#06202b");grad.addColorStop(.35,"#031015");grad.addColorStop(1,"#010305");ctx.fillStyle=grad;ctx.fillRect(0,0,w,h);
ctx.save();ctx.strokeStyle="#17637822";ctx.lineWidth=1;const horizon=h*.62;for(let i=-14;i<=14;i++){{ctx.beginPath();ctx.moveTo(cx+i*18,horizon);ctx.lineTo(cx+i*95,h);ctx.stroke();}}
for(let j=0;j<10;j++){{const q=j/10,y=horizon+(h-horizon)*q*q;ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(w,y);ctx.stroke();}}ctx.restore();
const particleCount=quality==="eco"?28:72;for(let i=0;i<particleCount;i++){{const p=particles[i];p.z-=quality==="eco"?.0008:.0015;if(p.z<=0)p.z=1;const scale=1/p.z,x=cx+(p.x-.5)*w*scale*.72,y=cy+(p.y-.5)*h*scale*.72;
if(x<0||x>w||y<0||y>h){{p.z=1;continue;}}ctx.fillStyle=`rgba(90,218,245,${{(1-p.z)*.55}})`;ctx.fillRect(x,y,p.s*scale,p.s*scale);}}
const mode={{offline:.05,loading:.28,idle:.12,recording:.65,transcribing:.3,processing:.38,speaking:.85,cancelling:.22,error:.18}}[currentState]||.1;
for(let ring=0;ring<4;ring++){{const phase=t*.002-ring*.74,radius=105+ring*33+Math.sin(phase)*8*mode;ctx.beginPath();
for(let a=0;a<=Math.PI*2+.02;a+=.035){{const wave=Math.sin(a*(8+ring*2)+t*.008)*(5+17*mode)+Math.sin(a*3-t*.004)*4*mode;
const r=radius+wave,x=cx+Math.cos(a)*r,y=cy+Math.sin(a)*r*.42;(a===0?ctx.moveTo(x,y):ctx.lineTo(x,y));}}
ctx.strokeStyle=`rgba(77,221,250,${{.06+mode*.15-ring*.012}})`;ctx.lineWidth=1.2;ctx.stroke();}}}}
requestAnimationFrame(render);loadTools();loadModules();loadPresence();setInterval(loadTools,3000);setInterval(loadPresence,250);
</script>
</body></html>"""
