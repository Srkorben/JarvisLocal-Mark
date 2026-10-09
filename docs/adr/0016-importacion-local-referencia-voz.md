# ADR 0016: importación local autorizada de referencia de voz

Estado: aceptada — 2026-10-09

El enrolamiento por micrófono no cubre audios ya grabados ni referencias de una
voz cuyo titular haya autorizado el uso. Se añade una importación desde la misma
interfaz de Mark, sin crear otro asistente, proveedor TTS o almacén paralelo.

La superficie acepta únicamente bytes Base64 acotados y un nombre base usado para
determinar una extensión de allowlist. Nunca acepta rutas, URLs o comandos. WAV se
decodifica internamente; otros formatos pasan por FFmpeg local con argumentos
fijos, `shell=False`, límite temporal y timeout. La salida canónica es PCM16 mono
a 24 kHz. Se validan 15–30 segundos y un RMS mínimo.

La interfaz exige que el usuario confirme ser titular de la voz o contar con
autorización del titular. El manifiesto v2 registra esa declaración y la liga por
SHA-256 sin afirmar identidad biométrica. El formato v1 de voz propia continúa
siendo válido. La muestra nunca equivale a autenticación o confirmación de una
acción del agente.

Reemplazar la referencia activa crea antes un respaldo bajo
`data/voices/user/history/`. Solo se auditan hash, duración, extensión, resultado
y presencia del respaldo; no se conserva PCM ni nombre original en SQLite. La
operación se rechaza mientras el runtime de voz está activo. Chatterbox usa
condicionamiento zero-shot, por lo que “subir” no significa entrenar pesos.
