# Latencia de Mark — Ref 1.0

## Recorrido real de una interacción

**Texto (panel):** `POST /api/chat` → cola efímera de un mensaje (`TextChatRequestStore`) →
`manager.start("voice")` → el bucle de voz consume `/api/chat/next` (espera larga de 5 s) →
`VoiceSessionManager.submit_text` → `Orchestrator.chat` (historial de 30 mensajes, esquemas
de herramientas) → `llama-server` con streaming SSE → deltas publicados a la presencia →
el panel consulta `/api/voice/presence` cada 250 ms y pinta el texto progresivamente.

**Voz:** captura de llamada/PTT → faster-whisper (CPU) → `Orchestrator.chat` → herramientas →
TTS (Chatterbox, worker aislado) → reproducción WASAPI.

**Texto (CLI):** `Orchestrator.chat` con impresión directa de cada delta.

## Cuellos de botella

| # | Problema | Evidencia | Estado |
|---|---|---|---|
| D1 | Con Chatterbox en CUDA, Qwen3-8B baja de ~55 a 5,6–7 tokens/s (comparten 8 GB de VRAM; `--fit` descarga capas a CPU) | Benchmark de Ref 1.0 en la RTX 5060 (ver abajo) | **Decidido**: GPU reservada al LLM; Piper en CPU como voz provisional |
| D2 | El TTS esperaba la respuesta completa y alternaba síntesis y reproducción sin solapar | `audio/session.py` (antes) | **Corregido** |
| D3 | Se ofrecían al modelo herramientas que la política deniega siempre (7 de 19 con los permisos por defecto) | `orchestrator.py` | **Corregido** |
| D4 | La presencia publicaba por HTTP síncrono dentro del bucle de voz (hasta 0,35 s por actualización) | `control_center/presence.py` | **Corregido** |
| D5 | No había trazas por ronda: se descartaban los *timings* de llama-server | `orchestrator.py` | **Corregido** |
| D6 | El chat del panel requiere arrancar el proceso de voz completo (STT, TTS y LLM) | `server.py` `/api/chat` | **Corregido**: runtime de texto `--panel-chat` |

## Cambios de Ref 1.0

- **Habla progresiva** (`audio/speech_stream.py`).
  - Cada frase completa se sintetiza en cuanto llega del LLM.
  - La siguiente frase se sintetiza mientras suena la actual.
  - Las frases largas se parten en una pausa natural.
  - Cancelación por el token del turno.
  - Los mensajes que no pasan por streaming (límite de rondas) también se pronuncian.
- **Trazas de latencia** (`latency.py`) en `data/logs/latency.jsonl`.
  - Etapas: contexto, primer token, fin del LLM, primer audio, STT y total.
  - Rondas con `prompt_n`, `predicted_per_second` y la duración de cada herramienta.
  - **Sin texto, audio ni credenciales.** Rotación al llegar a 5 MB.
- **Esquemas filtrados:** solo se ofrecen las herramientas que el proyecto puede usar. La política sigue evaluando cada solicitud.
- **Presencia no bloqueante:** un hilo emisor envía el estado más reciente. Los estados `error` y `offline` esperan su entrega, con un límite.
- **Benchmark local** (`latency_benchmark.py`).

## Mediciones en Windows 11 (RTX 5060 Laptop, 8 GB)

Ejecutadas por el propietario el 9 de octubre de 2026 con la rama `claude/ref1-latency`
(`f39438f`), 5 repeticiones en caliente. Medianas:

| Medida | Texto, GPU libre | Voz, Chatterbox CUDA cargado |
|---|---|---|
| Velocidad del LLM | 54,8–56,5 tokens/s | 5,6–7,0 tokens/s |
| Primer token, mensaje corto | 0,20 s | 0,86 s |
| Primer token, con herramienta | 1,09 s | 7,45 s |
| Respuesta larga completa | 12,5 s | 127 s |
| Voz corta: primer audio / turno | — | 19,1 s / 33 s |
| Voz larga | — | 5 de 5 turnos cortados a 120 s |
| VRAM ocupada | 7313 MiB | 7679 de 8151 MiB |

Una primera medición de texto con la GPU ya ocupada por otro proceso (7335 MiB antes de
empezar) dio 17–22 tokens/s: el mismo efecto, por otra causa.

## Decisión provisional del propietario (reparto de cómputo)

| Servicio | Dispositivo |
|---|---|
| LLM (Qwen3-8B, llama-server) | GPU, con la VRAM reservada |
| STT (faster-whisper) | CPU, solo en la conversación por voz |
| TTS provisional (Piper) | CPU, cargado solo cuando hay que hablar |
| Embeddings (RAG) | CPU (`gpu_layers = 0`), solo al indexar o consultar |
| Chatterbox (voz propia) | Conservado; en la GPU solo con `voice_clone.allow_gpu = true` |

- `config/jarvis.toml` usa `tts.provider = "piper"`.
- Si se vuelve a elegir `chatterbox` con `device = "cuda"` sin `allow_gpu = true`, Mark usa
  Piper en CPU y lo registra, en lugar de cargar Chatterbox en la GPU.
- El chat escrito del panel arranca `--panel-chat`: solo el LLM. Si pides que hable,
  carga Piper y la salida de audio en ese momento; nunca STT ni micrófono. Si la
  conversación por voz está activa, ella atiende el chat; al iniciar la voz, el runtime
  de texto se detiene para no cargar el modelo dos veces.
- La importación de referencias de voz y el enrolamiento no cambian.

Esta configuración **no se ha medido todavía en el equipo**: la mejora esperada es una
deducción de las mediciones anteriores, no un resultado.

## Prueba A en Windows 11: Piper en CPU (10 de octubre de 2026)

Rama `c9a268b`, 3 repeticiones en caliente (2 en la respuesta larga). Medianas:

| Medida | Chatterbox CUDA (línea base) | Piper CPU |
|---|---|---|
| LLM, mensaje de texto | 7,0 tokens/s | 53,8 tokens/s |
| LLM durante un turno de voz | 2,2 tokens/s | 46,2–46,6 tokens/s |
| Primer audio, voz corta | 19,1 s | 7,2 s |
| Turno de voz corto | 33,1 s | 11,6 s |
| Primer audio, voz larga | — | 9,0 s |
| Turnos largos completados | 0 de 5 | 2 de 2 (103,5 s, casi todo reproducción) |
| Carga del TTS | 105 s | 1,6 s |
| RAM del proceso Python | — | ~650 MiB |
| VRAM total | 7679 MiB | 7134–7519 MiB |

- El nuevo cuello de botella del turno de voz es el **STT**: 5,7 s de los 7,2 s del primer audio.
- **Calidad**: el propietario rechazó la voz Piper `es_MX-ald` ("horrible"). Piper es rápido,
  pero esa voz no sirve ni como provisional, y no admite una referencia importada.
- El límite de 120 s por turno incluye la reproducción: una respuesta hablada muy larga
  puede cortarse aunque todo vaya rápido.

**Pendiente (no ejecutado):** prueba B, Chatterbox en CPU con la referencia autorizada; la
comparación de neutralidad del acento; ajustar el STT (`beam_size`); separar el límite de
generación del de reproducción.

## Evidencia obtenida en la nube (no es hardware real)

| Comprobación | Antes (`bd4a876`) | Después |
|---|---|---|
| Turno de voz simulado (LLM 0,5 s/frase, síntesis 0,4 s, reproducción 0,4 s), mediana de 5: primer audio | 2,40 s | 0,90 s |
| Ídem, turno completo | 5,22 s | 2,81 s |
| 21 actualizaciones de presencia con el panel colgado | 10,53 s bloqueado | < 0,1 s |

Estas cifras validan los mecanismos, **no** la latencia en la RTX 5060.

## Medición en Windows 11

Cierra Mark (panel y voz) antes de medir, para que el benchmark controle `llama-server`.
El benchmark usa una base de datos temporal y no guarda el texto de las respuestas. La
voz de entrada se sintetiza con tu TTS configurado y no sale del equipo. Los resultados
quedan en `data\benchmarks\latency\`.

1. Ve a la carpeta que contiene la instalación:

```cmd
cd /d "%USERPROFILE%\Documents\AI Local"
```

2. Clona la rama en una carpeta aparte (no modifica tu instalación):

```cmd
git clone --branch claude/ref1-latency https://github.com/Srkorben/JarvisLocal-Mark.git JarvisLocal-ref1
```

3. Entra en tu instalación:

```cmd
cd /d "%USERPROFILE%\Documents\AI Local\JarvisLocal"
```

4. Usa el código de la rama solo en esta consola:

```cmd
set "PYTHONPATH=%USERPROFILE%\Documents\AI Local\JarvisLocal-ref1\src"
```

5. Comprueba que se carga la rama (debe mostrar una ruta dentro de `JarvisLocal-ref1`):

```cmd
.venv\Scripts\python.exe -c "import jarvis_local.latency_benchmark as m; print(m.__file__)"
```

6. Perfil A, solo el LLM con la GPU libre:

```cmd
.venv\Scripts\python.exe -m jarvis_local.latency_benchmark --config config\jarvis.toml --profile text --repeat 5
```

7. Perfil de voz con la voz provisional, Piper en CPU (si tu configuración pide Chatterbox
   CUDA sin `allow_gpu`, el benchmark también usará Piper e informará `piper / cpu`):

```cmd
.venv\Scripts\python.exe -m jarvis_local.latency_benchmark --config config\jarvis.toml --profile voice --tts-provider piper --repeat 5
```

8. Opcional, para comparar: Chatterbox en CUDA (la opción autoriza la GPU solo para esta medición):

```cmd
.venv\Scripts\python.exe -m jarvis_local.latency_benchmark --config config\jarvis.toml --profile voice --tts-provider chatterbox --tts-device cuda --repeat 5
```

9. Prueba real con la voz progresiva desde los controles de la interfaz
   (`Ctrl+C` solo termina la CLI de diagnóstico):

```cmd
.venv\Scripts\python.exe -m jarvis_local.cli --config config\jarvis.toml --voice
```

10. Restablece la consola:

```cmd
set PYTHONPATH=
```

### Cómo leer el resultado

- **Primer token** en caliente: es el primer texto visible. Objetivo orientativo: de 1 a 3 s.
- **Primer audio**: objetivo orientativo, menos de 8–10 s. Compáralo con la columna *secuencial estimado*, que es cuando habría empezado a hablar el método anterior.
- **tokens/s**: compara el perfil `text` con el perfil `voice`. Si la diferencia se parece a la medida antes (unas 5 veces), la VRAM compartida domina la latencia y conviene decidir entre las opciones A, B y C con estos datos.
- Comparte los `.json` de `data\benchmarks\latency\`. No contienen conversaciones.

## Limitaciones conocidas

- La voz Piper no es la voz propia: es una solución temporal hasta optimizar Chatterbox.
- Pendiente de comprobar en Windows: latencia real con Piper y el chat del panel con `--panel-chat`.
- En el escenario `text_tool`, el benchmark ejecuta una herramienta de solo lectura (`get_current_time`).
- El benchmark no carga RAG. Las herramientas de RAG no aparecen en sus esquemas.
- Si el LLM incluye texto antes de llamar a una herramienta, ese texto también se pronuncia.
