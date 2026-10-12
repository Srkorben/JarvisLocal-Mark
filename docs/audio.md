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

## Voz activa: XTTS-v2

Después de comparar audiblemente Piper, Chatterbox LatAm y XTTS-v2 con la misma
referencia autorizada, el propietario aceptó XTTS-v2 por una mejora clara de
semejanza y naturalidad. `config/jarvis.toml` selecciona `xtts`; los otros dos
motores permanecen disponibles como fallbacks.

XTTS vive en `.venv-xtts`, usa `coqui-tts 0.27.5`, PyTorch 2.9.1+cu128 y el
modelo oficial `coqui/XTTS-v2` fijado en la revisión
`6c2b0d75eae4b7047358e3b6bd9325f857d43f77` (~2,09 GB). La licencia del modelo
es Coqui Public Model License. El worker local no abre puertos y conserva en
memoria los latentes de la referencia. Cancelar termina el proceso.

PyTorch 2.9 deriva la lectura de audio a TorchCodec, que en Windows requiere una
distribución FFmpeg compartida. El worker no instala otro FFmpeg: lee únicamente
el WAV PCM ya validado mediante `soundfile` y entrega un tensor local a XTTS.

Medición integrada del 12 de octubre de 2026:

- carga, condicionamiento y priming CUDA: 110,891 s;
- síntesis posterior: 2,281 s para 5,387 s de audio a 24 kHz;
- reproducción WASAPI: 5,672 s;
- prueba humana comparativa: mejora clara frente a Chatterbox.

Instalación reproducible:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\Setup-XTTS.ps1
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
- XTTS-v2 recibió aceptación comparativa inicial; sigue pendiente validar varios
  turnos completos dentro de una llamada real.

