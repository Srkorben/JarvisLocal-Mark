# Latencia de Mark — Ref 1.0

## Recorrido real de una interacción

**Texto (panel):** `POST /api/chat` → cola efímera de un mensaje (`TextChatRequestStore`) →
`manager.start("voice")` → el bucle de voz consume `/api/chat/next` (espera larga de 5 s) →
`VoiceSessionManager.submit_text` → `Orchestrator.chat` (historial de 30 mensajes, esquemas
de herramientas) → `llama-server` con streaming SSE → deltas publicados a la presencia →
el panel consulta `/api/voice/presence` cada 250 ms y pinta el texto progresivamente.

**Voz:** captura PTT → faster-whisper (CPU) → `Orchestrator.chat` → herramientas →
TTS (Chatterbox, worker aislado) → reproducción WASAPI.

**Texto (CLI):** `Orchestrator.chat` con impresión directa de cada delta.

## Cuellos de botella

| # | Problema | Evidencia | Estado |
|---|---|---|---|
| D1 | Con Chatterbox en CUDA, Qwen3-8B baja de 54,85 a 10,11 tokens/s (comparten 8 GB de VRAM; `--fit` descarga capas a CPU) | `benchmarks/results/qwen3-8b-q4_k_m-ctx8192.md`, `chatterbox-cuda-rtx5060.md` | Medido por el propietario. **Sin cambiar en Ref 1.0**: hay que decidirlo con el benchmark |
| D2 | El TTS esperaba la respuesta completa y alternaba síntesis y reproducción sin solapar | `audio/session.py` (antes) | **Corregido** |
| D3 | Se ofrecían al modelo herramientas que la política deniega siempre (7 de 19 con los permisos por defecto) | `orchestrator.py` | **Corregido** |
| D4 | La presencia publicaba por HTTP síncrono dentro del bucle de voz (hasta 0,35 s por actualización) | `control_center/presence.py` | **Corregido** |
| D5 | No había trazas por ronda: se descartaban los *timings* de llama-server | `orchestrator.py` | **Corregido** |
| D6 | El chat del panel requiere arrancar el proceso de voz completo (STT, TTS y LLM) | `server.py` `/api/chat` | Documentado; se abordará en Ref 2.0 |

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

7. Perfil de voz actual, Chatterbox en CUDA junto al LLM:

```cmd
.venv\Scripts\python.exe -m jarvis_local.latency_benchmark --config config\jarvis.toml --profile voice --repeat 5
```

8. Opcional, TTS de clonación en CPU para comparar el reparto de recursos (lento; 3 repeticiones bastan):

```cmd
.venv\Scripts\python.exe -m jarvis_local.latency_benchmark --config config\jarvis.toml --profile voice --tts-device cpu --repeat 3
```

9. Prueba real con la voz progresiva, usando el PTT habitual (Ctrl+C para terminar):

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

- La decisión de reparto GPU/CPU (D1) **no se cambió**: requiere tus mediciones.
- En el escenario `text_tool`, el benchmark ejecuta una herramienta de solo lectura (`get_current_time`).
- El benchmark no carga RAG. Las herramientas de RAG no aparecen en sus esquemas.
- Si el LLM incluye texto antes de llamar a una herramienta, ese texto también se pronuncia.
