# Mark / JarvisLocal: documento de transferencia

Última actualización: 10 de octubre de 2026. Sirve para continuar desde otra sesión de Claude Code sin repetir las investigaciones.

## 1. Estado real

- `master` (`bd4a876`) **no ha cambiado**. Nada de esto está fusionado ni instalado en el PC del propietario.
- Todo el trabajo vive en dos ramas, apiladas una sobre otra:

| Rama | Contenido | Depende de |
|---|---|---|
| `claude/ref1-latency` | Ref 1.0: latencia, reparto de GPU, runtime de texto y benchmark | `master` (`bd4a876`) |
| `claude/ref2-chat-ui` | Ref 2.0: chat escrito en el centro de control | `claude/ref1-latency` (necesita `--panel-chat`) |

- **PR [Srkorben/JarvisLocal-Mark#1](https://github.com/Srkorben/JarvisLocal-Mark/pull/1)**: borrador, `claude/ref1-latency` → `master`. **No fusionar sin aprobación del propietario.**
- `claude/ref2-chat-ui` todavía no tiene PR. Si se abre, conviene basarlo en `claude/ref1-latency` o abrirlo cuando el PR #1 se haya fusionado.
- La rama experimental de voz `claude/jarvislocal-mark-ahioni`, con los ajustes de acento, sigue aislada y **no se incorpora**. La condición `accent_source=model` es defectuosa.

## 2. Ref 1.0: qué se completó

**Código**, en la rama `claude/ref1-latency`:
- **Voz progresiva** (`audio/speech_stream.py`): síntesis frase a frase, solapada con la reproducción.
- **Trazas de latencia sin contenido** (`latency.py`), en `data/logs/latency.jsonl`.
- **Esquemas de herramientas filtrados** por permisos (`orchestrator.py`).
- **Presencia no bloqueante** (`control_center/presence.py`).
- **Benchmark local** (`latency_benchmark.py`). El procedimiento está en `docs/latency.md`.
- **GPU reservada para el LLM.**
  - `tts.provider = "piper"`.
  - Chatterbox solo usa CUDA con `voice_clone.allow_gpu = true`; sin esa opción se usa Piper en CPU.
- **Runtime de texto `cli --panel-chat`**: solo carga el LLM, y el TTS solo si se pide voz. `/api/chat` lo arranca salvo que la voz ya esté activa.

**Mediciones en la RTX 5060** (detalle en `docs/latency.md`):

| Medida | GPU libre | Con Chatterbox CUDA | Con Piper CPU |
|---|---|---|---|
| Velocidad del LLM | ~55 tokens/s | 5,6–7 tokens/s | 46–54 tokens/s |
| Primer audio | — | 19,1 s | 7,2 s |
| Turnos largos | — | se cortan a 120 s | se completan |

- Con Piper en CPU, el STT pasa a ser el mayor coste del turno de voz: 5,7 s.
- **La voz Piper `es_MX-ald` fue rechazada por calidad.**

**No validado todavía en producción.** Pendiente:
1. Prueba B: Chatterbox en CPU con la referencia autorizada. Mide la viabilidad de la voz clonada sin quitarle la GPU al LLM.
2. Comparación de neutralidad del acento. Probablemente requiera descargar otro modelo: hay que explicarlo y pedir autorización antes.
3. Ajuste del STT (`beam_size`, modelo).
4. Separar el límite de generación del de reproducción (hoy son 120 s en total).
5. Decisión definitiva del TTS. **No adoptarla sin esas mediciones.**

El propietario quiere que la importación de la voz de unos 20 s se haga **desde la UI/UX**. El backend ya existe: `/api/voice/reference/import` y el botón "Subir audio" del cajón *Sistemas*.

## 3. Ref 2.0: qué se completó

**Chat escrito integrado** en el centro de control (`control_center/web.py`). El shell WPF/WebView2 solo carga esta página, así que el chat aparece también allí.

| Funcionalidad | Implementada | Probada automáticamente | Pendiente |
|---|---|---|---|
| Área de conversación (burbujas Tú/Mark) | ✅ | ✅ navegador¹ | Validación visual en WPF |
| Campo de texto: Enter envía, Mayús+Enter salto | ✅ | ✅ navegador¹ | — |
| Envío al modelo local (`/api/chat`, cookie + CSRF) | ✅ | ✅ unitario + navegador¹ | Prueba con Qwen real en Windows |
| Respuesta progresiva (presencia cada 250 ms) | ✅ | ✅ navegador¹ | Fluidez real con Qwen |
| Indicador de fase (cola, iniciando, pensando, hablando, cancelando) | ✅ | ✅ navegador¹ | — |
| Errores, núcleo detenido, bloqueo de 150 s, desconexión | ✅ | ✅ error del núcleo¹; desconexión solo por código | Desconexión real |
| Cancelación (`POST /api/chat/cancel` → `/api/chat/next` → `cancel_active`) | ✅ | ✅ unitario + navegador¹ | Con Qwen real |
| "Responder también con voz" | ✅ | Solo la lógica del runtime | Audio real en Windows |
| Diseño coherente y vista móvil | ✅ | Capturas¹ | Revisión del propietario |

¹ Prueba en Chromium (Playwright) contra el servidor real del panel, con su autenticación, y un runtime simulado. **No es la app WPF ni el LLM real.**

**Seguridad:**
- Sin cambios en la autenticación: la página usa cookie, las acciones CSRF y el runtime un token de portador.
- Los mensajes se pintan con `textContent`.
- La conversación no se guarda en el navegador.
- La política de herramientas no cambia: el runtime de texto deniega las confirmaciones interactivas.

## 4. Archivos modificados

- **Ref 1.0**:
  - `src/jarvis_local/`: `latency.py`, `latency_benchmark.py`, `orchestrator.py`, `projects.py`, `tools/registry.py`, `cli.py` y `config.py`.
  - `src/jarvis_local/audio/`: `speech_stream.py`, `session.py`, `lazy.py`, `providers.py` y `__init__.py`.
  - `src/jarvis_local/control_center/`: `presence.py`, `catalog.py`, `launcher.py`, `modules.py` y `server.py`.
  - `config/jarvis.toml`, `docs/latency.md` y `.github/workflows/tests.yml`.
  - Pruebas: `test_latency*.py`, `test_speech_stream.py`, `test_presence_publish.py` y `test_text_runtime.py`.
- **Ref 2.0**:
  - `src/jarvis_local/control_center/`: `web.py`, `server.py`, `text_chat.py` y `presence.py`.
  - `src/jarvis_local/audio/session.py`.
  - `tests/test_control_center.py` y `tests/test_text_runtime.py`.
  - `docs/HANDOFF.md`.

## 5. Pruebas y errores conocidos

- **Linux (nube):** 153 pasan y 1 falla.
- **La que falla:** `CatalogTests::test_catalog_preserves_nine_shortcuts_and_adds_3d_integration`.
  - Exige ejecutables de Windows y Godot. Ya fallaba en `master` y también falla en la CI de Windows.
  - Su corrección pertenece a I-1.1, **no autorizada**. No convertirla en SKIP sin aprobación.
- **CI** (`.github/workflows/tests.yml`): Windows y Linux, solo con esa misma falla.
- **Interfaz local del propietario:** puede tener cambios en su instalación que no están en GitHub. Antes de integrar, comparar su `web.py` local con esta rama.
- **Configuración local:** el `config\jarvis.toml` del propietario sigue pidiendo Chatterbox CUDA. Con este código, sin `allow_gpu`, se usará Piper.

## 6. Riesgos de integración

1. **Instalación local.** Integrar las ramas exige actualizar la instalación de Windows. Hacerlo **solo con autorización**, con copia de seguridad de `config\jarvis.toml` y `data\`.
2. **Voz por defecto.** Piper queda como voz si no se decide otra cosa, y su calidad fue rechazada. Antes de integrar, decidir el TTS (prueba B) o avisar al propietario.
3. **Runtimes exclusivos.** El runtime de texto y la voz no pueden coexistir: al iniciar la voz, el panel detiene `chat_runtime`, y un turno de texto en curso se pierde.
4. **Presencia compartida.** Un turno de voz (PTT) durante un chat escrito también se ve en el panel. El chat ignora transcripciones ajenas, pero no las muestra.

## 7. Cómo continuar desde otra sesión

```bash
git fetch origin claude/ref2-chat-ui claude/ref1-latency
git checkout claude/ref2-chat-ui
pip install -e ".[dev]" numpy
python -m pytest -q
```

- **Para ver el chat sin Windows:** levantar `ControlCenterHTTPServer` con un `ProcessManager` falso y un runtime simulado que consuma `/api/chat/next` con el token de portador y publique la presencia completa, como hace `VoicePresenceClient`. Abrir `/?token=…` en un navegador.
- **Atención:** la presencia **reemplaza** todo el estado en cada `POST`; hay que enviar siempre `state`, `transcript`, `response` y `error`.
- **Instrucciones de terminal para el propietario:** bloques `cmd`, un comando por paso, esperando su resultado.

## 8. Primera tarea concreta de la siguiente sesión

**Validar y pulir el chat en Windows 11, sin benchmarks.**
1. Guiar al propietario para abrir el panel con la rama `claude/ref2-chat-ui` (carpeta `JarvisLocal-ref1` + `PYTHONPATH`), sin tocar su instalación.
2. Enviar 3 mensajes reales a Qwen: corto, largo y con herramienta. Probar Cancelar y comprobar la app WPF.
3. Corregir lo que aparezca.
4. Después, siguiente entrega de Ref 2.0:
   - estado y control del núcleo desde el chat (iniciar y detener texto o voz, uso de VRAM);
   - historial de la sesión recuperable desde el núcleo, no desde el navegador;
   - flujo de importación de la voz de 20 s integrado en la UI.
