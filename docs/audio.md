# Voz local: conversación continua y pulsar para hablar

Estado: infraestructura implementada y probada; referencia propia enrolada e
importación local autorizada disponible. La aceptación de naturalidad sigue
pendiente de evaluación humana.

## Modos y flujo

```text
UI autenticada → canal local tipado → WASAPI compartido → PCM mono 16 kHz
  → detección de inicio/fin + Silero VAD dentro de faster-whisper
  → STTProvider → misma sesión/Orchestrator/política/memoria/tools
  → TTSProvider → WASAPI compartido → altavoces
```

**Conversación** abre una sesión explícita con un clic. Un detector de energía
local confirma el comienzo de voz, conserva 500 ms de preroll y cierra la
intervención tras una pausa configurable; Silero VAD sigue filtrando el audio al
transcribir. Tras hablar, Mark vuelve automáticamente a escuchar hasta **Colgar**.

**Pulsar para hablar** abre la captura solo mientras el usuario mantiene el botón.
Perder foco, visibilidad o captura del puntero finaliza de forma segura el gesto.

La máquina de estados añade `LISTENING`, `VOICE_DETECTED`, `MUTED` y `ENDING` al
ciclo `IDLE → RECORDING → TRANSCRIBING → PROCESSING → SPEAKING → IDLE`, además
de `CANCELLING` y `ERROR`. Un único lock impide turnos concurrentes. La interfaz
es semidúplex: mientras Mark habla no escucha. No existe wake word, full-duplex,
vigilancia permanente ni historial paralelo.

## Uso

```powershell
Set-Location 'C:\Users\andcb\Documents\AI Local\JarvisLocal'

# Inventario y diagnóstico (el segundo exige que la voz configurada esté lista)
.\.venv\Scripts\python.exe -m jarvis_local.cli --list-audio-devices
.\.venv\Scripts\python.exe -m jarvis_local.cli --audio-doctor

# Runtime de voz controlado por la interfaz local
.\.venv\Scripts\python.exe -m jarvis_local.cli --voice
```

La forma normal de uso es abrir **Mark Scout** y elegir uno de los dos modos. En
**Conversación**, **Iniciar llamada** prepara el runtime y comienza a escuchar sin
un segundo clic; **Silenciar** cierra temporalmente la captura y **Colgar** termina
la sesión. En **Pulsar para hablar**, se mantiene el micrófono y se suelta para
enviar. **Interrumpir** cancela captura, generación o TTS y propaga el token a las
herramientas. No existen combinaciones globales de voz ni keylogging. La CLI de
voz exige que el centro de control local esté activo.

## STT

- `faster-whisper` 1.2.1, modelo multilingual `small`, CPU INT8 y ocho threads;
- revisión fijada `536b0662742c02347bc0e980a01041f333bce120`;
- 486.217.556 bytes; `model.bin` SHA-256
  `3e305921506d8872816023e4c273e75d2419fb89b24da97b4fe7bce14170d671`;
- idioma `es`, prompt/hotwords para Mark, Mark Scout, JarvisLocal, Qwen3, Git,
  README y SQLite;
- Silero VAD integrado por `vad_filter`, sin un segundo runtime Torch;
- texto normalizado a NFC y UTF-8 válido antes de entrar al LLM.

La inferencia se ejecuta en un thread. La cancelación se comprueba antes, entre
segmentos y después, pero CTranslate2 no garantiza interrumpir inmediatamente un
kernel CPU ya iniciado. La transcripción ambigua o silenciosa no llega al núcleo.

## Voz activa: Qwen3-TTS Base 0.6B

Después de rechazar Piper, Chatterbox LatAm y XTTS-v2 por timbre robotizado o
interferencias, el propietario aprobó previews de
`Qwen/Qwen3-TTS-12Hz-0.6B-Base`. `config/jarvis.toml` selecciona `qwen3_tts`;
los motores anteriores permanecen disponibles únicamente como fallbacks.

Qwen3-TTS vive en `.venv-qwen3-tts`, usa `qwen-tts==0.1.1`, PyTorch
2.9.1+cu128 y Transformers 4.57.3. El modelo Apache-2.0 está fijado en la
revisión `5d83992436eae1d760afd27aff78a71d676296fc` (~2,52 GB). El worker
JSONL no abre puertos y se ejecuta completamente offline.

La referencia efectiva es el MP3 original autorizado, su transcripción explícita
y un manifiesto SHA-256 independiente. La conversión previa a WAV y el warmup
generativo no reproducían el timbre aprobado. El muestreo queda fijado mediante
`voice_clone.seed = 42`. Los defaults oficiales `0.9/50/1.0` produjeron una
toma robótica reproducible para una frase de control. El perfil aprobado reduce
`temperature` y `subtalker_temperature` a `0.65`, y usa `top_k = 30` y
`top_p = 0.9` en ambos generadores.

Qwen recibe la respuesta completa como una sola unidad prosódica. El texto sigue
apareciendo por streaming en la interfaz, pero no se sintetiza frase por frase:
la fragmentación hacía que una respuesta de dos frases sonara diferente al
preview y duplicaba el trabajo. Piper conserva el streaming por frases.

Prueba real desde la aplicación WPF/centro de control del 12 de octubre de 2026:

- carga del worker: 23,921 s;
- una síntesis para dos frases: 62,125 s;
- reproducción: 6,562 s;
- turno completo: 74,703 s;
- `sentences_spoken = 1`;
- firma acústica redondeada idéntica al candidato 42 aprobado: RMS 0,04186,
  pico 0,38867 y tasa de cruces 0,09961;
- suite: 192 pruebas y 9 subpruebas aprobadas.

La reproducción integrada ya no remuestrea el PCM de Qwen de 24 kHz mediante
interpolación lineal de NumPy. Entrega la señal original a WASAPI compartido con
`auto_convert`, de modo que el motor de audio de Windows realiza la conversión al
formato nativo de 48 kHz del dispositivo. El 12 de octubre se verificó esta ruta
primero con el candidato aprobado y luego con un turno hablado desde WPF; falta
la aceptación auditiva humana de varios turnos distintos antes de declarar
resuelta la variación de calidad.

Prueba de regresión del perfil conservador del 13 de octubre de 2026:

- la toma predeterminada que el usuario rechazó dio RMS `0,04364`, pico
  `0,46875` y ZCR `0,12201`;
- la misma frase con el perfil conservador fue aprobada como natural y dio RMS
  `0,04042`, pico `0,34375` y ZCR `0,06033`;
- Mark completo reprodujo después exactamente esa firma desde WPF: síntesis
  `25,875 s`, reproducción `7,828 s`, turno total `43,016 s`.

El centro de control y el runtime conversacional están además protegidos por
mutex nominales de Windows. Los dos procesos que suelen verse por cada entorno
virtual son el lanzador del `venv` y su intérprete hijo, no dos sintetizadores;
el mutex impide una segunda instancia lógica real.

La calidad tiene prioridad, pero la latencia todavía es inaceptable para una
conversación fluida. FlashAttention no está instalado y no debe añadirse con un
wheel incompatible. Una optimización futura debe mantener la misma salida
acústica y probarse desde Mark, no solo mediante previews aislados.

Instalación reproducible:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\Setup-Qwen3TTS.ps1
```

## Backend anterior: Chatterbox LatAm

Piper y Chatterbox ya no son la voz activa. Chatterbox se conserva como backend
recuperable y sigue fallando cerrado si la muestra o el consentimiento no son válidos.

Chatterbox se aisló en `.venv-chatterbox-cuda`: su stack fija NumPy 1.x y usa
PyTorch 2.9.1+cu128, que incluye `sm_120` para la RTX 5060. No contamina el núcleo.
Un worker JSONL local carga el modelo una vez, devuelve PCM y no expone puertos.
Cancelar una síntesis termina el worker; el turno siguiente puede iniciarlo de
nuevo. El entorno `.venv-chatterbox` CPU se conserva como fallback recuperable.

En modo voz, Mark carga y prima Chatterbox **antes** de iniciar `llama-server`.
Así la voz reserva primero su VRAM y `--fit on` limita automáticamente el offload
de Qwen3-8B a la memoria restante. El orden inverso se midió y produjo paginación
WDDM: una frase llegó a tardar 77,5 s pese a usar CUDA. El modelo no obtiene
autoridad adicional por ejecutarse en GPU.

El PCM16 viaja codificado en base64 en una única respuesta JSONL. El lector IPC
usa un límite explícito de 32 MiB y rechaza PCM mayor de 24 MiB o de longitud
inválida. Esto evita el límite predeterminado de 64 KiB de `StreamReader`, que
interrumpía incluso frases breves, sin convertir el canal en memoria ilimitada.

Artefactos instalados:

- código Chatterbox commit `5de7a54aa4e5e2baadb0182dde554908b48b85c2`;
- base oficial `ResembleAI/chatterbox`, revisión
  `5bb1f6ee58e50c3b8d408bc82a6d3740c2db6e18`;
- pack oficial LatAm `ResembleAI/Chatterbox-Multilingual-es-mx-latam`, revisión
  `27e595bf2fe7be0533ca299d9afafcde08b7cca7`;
- cuatro archivos necesarios, ~3,21 GB, más el tokenizador pkuseg fijado por hash;
- PerTh fijado en commit `ff1c8ac55a976971245cdd53c18d6131ca00d993`;
- código y modelos publicados como MIT; audio generado incorpora la marca de agua
  PerTh del proyecto;
- worker comprobado completamente offline; CUDA se prima durante el arranque;
- smoke conjunto real: carga+priming de voz 21,739 s, carga posterior del LLM
  12,423 s, TTFT 0,515 s, 10,11 tokens/s y 5,681 s para producir 4,4 s de audio;
- VRAM global observada: 1.565 MiB base, 5.268 MiB con voz y 7.533 MiB con voz+LLM.
- reproducción física final: 3,562 s de síntesis para 3,28 s de audio y 3,594 s
  de playback WASAPI, sin error del dispositivo de salida.

Instalación reproducible:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\Setup-VoiceClone.ps1
```

Enrolamiento consciente de una muestra de 10–30 segundos:

```powershell
.\.venv\Scripts\python.exe -m jarvis_local.cli `
  --enroll-own-voice --voice-enroll-seconds 15
```

La CLI exige escribir `MI VOZ`, muestra claramente cuándo el micrófono está
activo y guarda `reference.wav` y `consent.json` dentro de `data/voices/user/`.
El consentimiento contiene el SHA-256 de la muestra; si cambia, el backend se
bloquea. No se almacena audio en auditoría y la voz nunca sirve como confirmación
de una acción sensible.

La aplicación gráfica añade **Sistemas → Enrolar mi voz → Subir audio**. Acepta
WAV, MP3, M4A, FLAC, OGG, OPUS, AAC y WMA, con máximo de 24 MiB y duración
validada de 15–30 segundos. WAV se decodifica en el núcleo; los demás formatos
usan el FFmpeg local mediante argumentos fijos, `shell=False`, timeout y salida
acotada. Toda entrada termina como PCM16 mono a 24 kHz y se rechaza si es silencio.

La importación exige confirmar desde la interfaz autenticada que el usuario es
titular de la voz o posee autorización del titular. Si ya hay una referencia, se
crea primero un respaldo recuperable en `data/voices/user/history/`. El manifiesto
liga la nueva muestra por SHA-256 y registra procedencia/autorización, pero no
afirma la identidad de quien aparece en el audio. La auditoría conserva hash,
duración, formato y resultado; nunca el audio ni su nombre original. No se exponen
rutas ni comandos al navegador. Chatterbox realiza condicionamiento zero-shot:
esta operación cambia la referencia activa, no entrena pesos.

## Medición observada

El benchmark reproducible usa Piper→Whisper solo como señal de regresión; el
usuario rechazó expresamente esa voz y no es la selección final.

| Métrica (2026-10-08) | Resultado |
|---|---:|
| órdenes STT no ambiguas | 5/5 |
| WER medio sintético | 0,437 |
| mediana STT | 5,016 s |
| turno completo con `get_current_time` | aprobado |
| TTFT desde cierre de captura | 7,704 s |
| primer audio generado | 10,829 s |
| total sin reproducir | 11,735 s |
| RAM proceso Python al final | 705,32 MiB |

Estas cifras son peores que el objetivo y no deben presentarse como tiempo real.
La variación térmica/carga fue considerable. `small` reconoció bien SQLite, pero
confundió nombres como Jarvis, README y Git; los hotwords son una mitigación, no
una garantía. No se descargó `medium` para evitar otra variante grande sin una
prueba humana comparativa.

Prueba física ejecutada: WASAPI abrió el micrófono predeterminado a 48 kHz,
capturó 1,98 s (RMS 0,000172, esencialmente silencio), cerró en 47 ms y reprodujo
3,12 s por los auriculares. Esto valida dispositivos, no inteligibilidad humana.
La cancelación de reproducción tiene prueba automática y corrección de carrera;
no se repitió con audio Piper audible después de que el usuario rechazara la voz.

Resultado completo: [benchmark de Fase 2](../benchmarks/results/audio-phase2.md).

La aceleración posterior de la voz clonada se registra por separado en
[benchmark Chatterbox CUDA](../benchmarks/results/chatterbox-cuda-rtx5060.md).

## Privacidad y limitaciones

- audio de turnos no se persiste;
- auditoría conserva estado, latencias, idioma/probabilidades y resultado, no la
  transcripción ni PCM;
- los workers de clonación arrancan con `HF_HUB_OFFLINE=1`,
  `TRANSFORMERS_OFFLINE=1`, telemetría
  deshabilitada y todos los recursos previamente descargados;
- no hay eco acústico avanzado, full-duplex ni barge-in natural;
- durante una llamada, el micrófono solo se abre en la fase de escucha y se
  libera al silenciar, colgar, cerrar la aplicación o detener el runtime;
- una voz clonada puede sonar similar, pero no constituye identidad, autenticación
  ni autorización;
- Qwen3-TTS fue validado desde la aplicación con una respuesta controlada; sigue
  pendiente la aceptación humana de varios turnos libres y reducir su latencia.

