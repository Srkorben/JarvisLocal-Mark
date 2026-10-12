# ADR 0019: modos de voz controlados desde la interfaz

- Estado: aceptada
- Fecha: 2026-10-12
- Reemplaza: PTT global de ADR 0014

## Contexto

El antiguo atajo global de PTT era difícil de usar y duplicaba una acción que
pertenece naturalmente a la interfaz gráfica. La parada de emergencia debe seguir
disponible mediante controles explícitos.

## Decisión

- Eliminar la combinación global para comenzar una grabación.
- Ofrecer llamada semidúplex automática y PTT manual desde la misma interfaz.
- Usar controles visibles **Interrumpir**, **Silenciar** y **Colgar**.
- Transportar gestos mediante un canal loopback efímero, autenticado y tipado con
  un catálogo cerrado de eventos de llamada, silencio, PTT y cancelación.
- No transportar texto, confirmaciones, argumentos de herramientas ni cambios de
  autoridad por ese canal.
- Conservar el modo semidúplex: el botón no abre el micrófono mientras Mark está
  transcribiendo, procesando o hablando.

## Consecuencias

La interacción cotidiana no exige memorizar teclas. Una llamada prepara el runtime
y comienza a escuchar automáticamente; el modo PTT conserva control manual. La
interfaz debe estar activa para abrir el micrófono y la cancelación permanece
disponible mediante botones locales confiables.
