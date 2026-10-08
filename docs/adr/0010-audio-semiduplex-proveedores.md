# ADR 0010: audio semidúplex y proveedores sustituibles

Estado: aceptada — 2026-10-08

La primera interfaz de voz usa una sola máquina de estados y un lock de turno.
Captura, STT, TTS y reproducción dependen de contratos separados. Voz comparte el
mismo `Orchestrator`, sesión, memoria, políticas, herramientas y auditoría que
texto; no existe un segundo asistente ni una vía de autorización oral.

Se eligió `sounddevice` sobre PortAudio/WASAPI compartido para selección y
recuperación de dispositivos, con resampling explícito entre los 48 kHz nativos y
los 16/22,05/24 kHz de modelos. `faster-whisper small` usa CPU INT8 y su VAD
Silero integrado. La tecla global se implementa consultando únicamente el acorde
configurado mediante `GetAsyncKeyState`; no captura caracteres.

El diseño es semidúplex. Full-duplex, cancelación de eco y wake word se difieren:
añadirlos ahora elevaría el riesgo de que Jarvis se transcriba a sí mismo y haría
menos observable el uso del micrófono. Cancelar detiene reproducción, stream del
LLM y tareas cooperativas; no revierte acciones ya completadas.

