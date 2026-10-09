# ADR 0011: clonación de voz propia en proceso aislado

Estado: aceptada — 2026-10-08. La importación autorizada posterior se regula en
el ADR 0016 sin cambiar el aislamiento del proveedor. La selección CPU/GPU fue
sustituida por ADR 0017; se conservan la frontera, consentimiento y modo offline.

El requisito inicial excluía clonación, pero el usuario solicitó explícitamente
usar su propia voz después de escuchar y rechazar la voz Piper. Se admite solo
para la voz del propio usuario, con enrolamiento local consciente, muestra ligada
por SHA-256 y sin usar voz como autenticación o confirmación.

Se seleccionó Chatterbox Multilingual V3 con el pack oficial español LatAm. Frente
a OpenVoice/XTTS, ofrece una ruta oficial actual para español, código/pesos MIT,
clonación zero-shot y marca de agua integrada. La contrapartida es importante:
~3,21 GB de pesos mínimos, dependencias de investigación y carga CPU observada de
~50 s. Por ello no reemplaza el contrato `TTSProvider` ni entra al entorno core.

Un worker hijo usa JSONL sobre stdin/stdout, comando cerrado y sin puertos. Vive en
`.venv-chatterbox`, se ejecuta con recursos Hugging Face/Transformers en modo
offline y CPU por defecto. Cancelar termina el proceso, una frontera más realista
que fingir cancelación cooperativa dentro de una inferencia Torch. GPU queda
deshabilitada para no coexistir con Qwen3-8B en 8 GB de VRAM.

Piper permanece instalado como fallback técnico, pero no está activo. Chatterbox
falla cerrado hasta que existan la muestra y el manifiesto de consentimiento. La
decisión debe reevaluarse si la latencia con la voz real impide conversación útil;
no se promete clonación natural ni de baja latencia.

