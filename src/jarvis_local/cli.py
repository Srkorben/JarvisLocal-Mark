from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

from .budgets import ActionBudget
from .cancellation import CancellationController
from .config import Settings
from .database import Database
from .execution import ActionExecutor
from .logging_json import configure_logging
from .memory import DecisionSource, EpisodicKind, MemoryRepository
from .model_providers import ModelProvider, ModelProviderError, create_model_provider
from .models import (
    ActionRequest,
    ConfirmationReceipt,
    ConfirmationSource,
    PolicyDecision,
)
from .latency import default_latency_log
from .orchestrator import Orchestrator
from .policy import PolicyEngine
from .projects import ProjectService
from .rag import (
    EmbeddingProvider,
    EmbeddingProviderError,
    ProjectIndexer,
    RagRepository,
    RagService,
    create_embedding_provider,
)
from .tools import build_default_registry


def default_config_path() -> Path:
    return Path(__file__).resolve().parents[2] / "config" / "jarvis.toml"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Asistente personal local para Windows")
    parser.add_argument("--config", type=Path, default=default_config_path())
    parser.add_argument("--model", help="Sobrescribe temporalmente el modelo configurado")
    parser.add_argument("--once", help="Ejecuta una sola instrucción y termina")
    parser.add_argument("--doctor", action="store_true", help="Comprueba seguridad, datos y modelo local")
    parser.add_argument("--audio-doctor", action="store_true", help="Comprueba dispositivos y modelos de voz locales")
    parser.add_argument("--list-audio-devices", action="store_true", help="Lista dispositivos PortAudio/WASAPI")
    parser.add_argument("--voice", action="store_true", help="Inicia conversación push-to-talk global")
    parser.add_argument(
        "--enroll-own-voice",
        action="store_true",
        help="Graba localmente una muestra para clonación de la voz propia",
    )
    parser.add_argument(
        "--voice-enroll-seconds",
        type=float,
        default=15.0,
        help="Duración de la muestra propia (10–30 s)",
    )
    parser.add_argument(
        "--start-model-server",
        action="store_true",
        help="Permite iniciar llama-server aunque auto_start esté deshabilitado",
    )
    parser.add_argument("--verify-audit", action="store_true", help="Verifica la cadena hash de auditoría")
    parser.add_argument("--list-projects", action="store_true", help="Lista proyectos registrados")
    parser.add_argument("--register-project", metavar="NAME", help="Registra un proyecto autorizado")
    parser.add_argument("--project-path", type=Path, help="Ruta usada por --register-project")
    parser.add_argument("--activate-project", metavar="PROJECT_ID", help="Activa un proyecto registrado")
    parser.add_argument(
        "--set-project-permission",
        metavar="PERMISSION=BOOL",
        help="Edita un permiso del proyecto activo desde esta CLI local",
    )
    parser.add_argument("--index-project", action="store_true", help="Indexa incrementalmente el proyecto activo")
    parser.add_argument("--rag-query", help="Consulta el índice del proyecto activo")
    parser.add_argument(
        "--rag-mode", choices=("hybrid", "lexical", "semantic"), default="hybrid"
    )
    parser.add_argument("--record-decision", help="Registra una decisión explícitamente confirmada")
    parser.add_argument("--decision-topic", help="Tema estable usado por --record-decision")
    parser.add_argument("--decision-reason", help="Motivo del cambio usado por --record-decision")
    parser.add_argument("--decision-history", metavar="TOPIC", help="Consulta la cadena temporal de una decisión")
    parser.add_argument("--forget-decision", metavar="TOPIC", help="Olvida toda la cadena de un tema confirmado")
    parser.add_argument("--record-pending", help="Registra un pendiente explícitamente confirmado")
    parser.add_argument(
        "--record-session-summary",
        help="Registra un resumen de sesión suministrado explícitamente",
    )
    parser.add_argument("--profile-set", metavar="KEY=VALUE", help="Crea o edita una preferencia explícita")
    parser.add_argument("--profile-delete", metavar="KEY", help="Elimina una preferencia")
    parser.add_argument("--profile-list", action="store_true", help="Muestra preferencias explícitas")
    parser.add_argument("--simulate-tool", help="Evalúa una herramienta sin producir efectos")
    parser.add_argument("--arguments", default="{}", help="JSON de argumentos para --simulate-tool")
    parser.add_argument(
        "--expected-result",
        default="La simulación valida la acción sin producir efectos.",
        help="Resultado esperado para --simulate-tool",
    )
    return parser.parse_args(argv)


def confirm_action(request: ActionRequest, decision: PolicyDecision) -> ConfirmationReceipt:
    print("\nAcción que requiere confirmación local:")
    print(f"  Herramienta: {request.tool}")
    print(f"  Riesgo calculado: {int(decision.calculated_risk)}")
    print(f"  Argumentos: {json.dumps(request.arguments, ensure_ascii=False)}")
    print(f"  Resultado esperado: {request.expected_result}")
    print(f"  Política: {' '.join(decision.reasons)}")
    answer = input("Autorizar una vez [s/N]: ").strip().casefold()
    approved = answer in {"s", "si", "sí", "y", "yes"}
    return ConfirmationReceipt(
        approved=approved,
        source=ConfirmationSource.TRUSTED_LOCAL_UI,
        request_id=request.request_id,
        summary="Confirmación explícita desde la CLI local." if approved else "El usuario rechazó la acción.",
    )


def deny_noninteractive_confirmation(
    request: ActionRequest, decision: PolicyDecision
) -> ConfirmationReceipt:
    """La voz y el chat web no pueden autorizar acciones sensibles por texto."""

    return ConfirmationReceipt(
        approved=False,
        source=ConfirmationSource.TRUSTED_LOCAL_UI,
        request_id=request.request_id,
        summary="No existe una confirmación interactiva confiable para este turno.",
    )


async def run_doctor(
    settings: Settings,
    database: Database,
    provider: ModelProvider,
    embeddings: EmbeddingProvider,
) -> int:
    failures = 0
    print(f"Python: {sys.version.split()[0]} (objetivo 3.12; compatible 3.12–3.13)")
    print(f"Configuración: OK ({settings.project_dir})")
    print(f"Base de datos: OK ({settings.database_path})")
    print(f"Registros: {database.counts()}")

    valid_chain, errors = database.verify_audit_chain()
    print(f"Auditoría: {'OK' if valid_chain else 'ERROR'}")
    if not valid_chain:
        failures += 1
        for error in errors:
            print(f"  - {error}")

    health = await provider.health()
    print(f"Proveedor: {health.provider}")
    print(f"Servidor: {'OK' if health.available else 'NO DISPONIBLE'}")
    print(f"Modelo: {'OK' if health.ready else 'NO LISTO'} ({health.model})")
    if health.version:
        print(f"Versión del proveedor: {health.version}")
    if health.detail:
        print(f"Detalle: {health.detail}")
    if not health.available or not health.ready:
        failures += 1
    if settings.model_provider == "llama_cpp":
        executable_ok = bool(
            settings.llama_server_executable and settings.llama_server_executable.is_file()
        )
        model_ok = bool(settings.llama_model_path and settings.llama_model_path.is_file())
        print(f"llama-server: {'OK' if executable_ok else 'NO ENCONTRADO'}")
        print(f"GGUF: {'OK' if model_ok else 'NO ENCONTRADO'}")
        failures += int(not executable_ok) + int(not model_ok)

    embedding_health = await embeddings.health()
    print(f"Embeddings: {'OK' if embedding_health.ready else 'NO LISTO'} ({embedding_health.model})")
    if embedding_health.detail:
        print(f"Detalle embeddings: {embedding_health.detail}")
    if not embedding_health.available or not embedding_health.ready:
        failures += 1
    embedding_model_ok = bool(
        settings.embedding_model_path and settings.embedding_model_path.is_file()
    )
    print(f"GGUF embeddings: {'OK' if embedding_model_ok else 'NO ENCONTRADO'}")
    failures += int(not embedding_model_ok)

    print("Raíces autorizadas:")
    for root in settings.allowed_roots:
        exists = root.exists()
        failures += int(not exists)
        print(f"  - [{'OK' if exists else 'NO EXISTE'}] {root}")
    print(f"Herramientas autorizadas: {', '.join(sorted(settings.allowed_tools))}")
    print(f"Acciones privilegiadas: {'habilitadas' if settings.privileged_tools_enabled else 'deshabilitadas'}")
    print(f"IA remota: {'habilitada' if settings.remote_ai_enabled else 'deshabilitada'}")
    print(f"Automatización visual: {'habilitada' if settings.visual_automation_enabled else 'deshabilitada'}")
    return 1 if failures else 0


async def async_main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    settings = Settings.load(args.config)
    if args.model:
        settings = settings.model_copy(update={"model": args.model})

    settings.data_dir.mkdir(parents=True, exist_ok=True)
    configure_logging(settings.data_dir / "logs", settings.log_level)
    database = Database(settings.database_path)
    policy = PolicyEngine(settings)
    projects = ProjectService(database, policy)
    project = projects.ensure_bootstrap_project("JarvisLocal", settings.project_dir)
    memory = MemoryRepository(database)
    controller = CancellationController()

    if args.list_audio_devices:
        from .audio import SoundDeviceCatalog

        print(
            json.dumps(
                [item.model_dump(mode="json") for item in SoundDeviceCatalog.list_devices()],
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if args.audio_doctor:
        from .audio import AudioError, audio_diagnostics

        try:
            report = await audio_diagnostics(settings)
        except AudioError as exc:
            print(json.dumps(exc.as_dict(), ensure_ascii=False, indent=2), file=sys.stderr)
            return 1
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    if args.enroll_own_voice:
        from .audio import AudioError, SoundDeviceRecorder
        from .audio.enrollment import create_own_voice_consent, write_reference_wav

        seconds = args.voice_enroll_seconds
        if not 10 <= seconds <= 30:
            print("--voice-enroll-seconds debe estar entre 10 y 30.", file=sys.stderr)
            return 2
        reference = settings.tts_clone_reference_path
        consent = settings.tts_clone_consent_path
        if reference is None or consent is None:
            print("voice_clone.reference_path/consent_path no están configurados.", file=sys.stderr)
            return 2
        try:
            reference.resolve().relative_to(settings.data_dir.resolve())
            consent.resolve().relative_to(settings.data_dir.resolve())
        except ValueError:
            print("La muestra y el consentimiento deben quedar dentro de data_dir.", file=sys.stderr)
            return 2
        if reference.exists() or consent.exists():
            print(
                "Ya existe un enrolamiento. No se sobrescribe automáticamente; "
                "elimina explícitamente ambos archivos si deseas repetirlo.",
                file=sys.stderr,
            )
            return 2
        print(
            "Esta función es únicamente para tu propia voz. La muestra permanecerá "
            "local y no autoriza confirmaciones de seguridad."
        )
        confirmation = input("Escribe exactamente MI VOZ para continuar: ").strip()
        if confirmation != "MI VOZ":
            print("Enrolamiento cancelado.")
            return 1
        print(
            "Lee con voz natural: 'Mark es mi asistente personal local. Hoy voy a "
            "organizar mis proyectos, revisar documentos y consultar el estado de Git.'"
        )
        input("Pulsa Enter cuando estés listo; la grabación será visible: ")
        recorder = SoundDeviceRecorder(
            selector=settings.audio_input_device,
            target_sample_rate=settings.audio_sample_rate,
            max_seconds=seconds + 1,
        )
        try:
            print("[MICRÓFONO ACTIVO — grabando muestra propia]", flush=True)
            recorder.start()
            await asyncio.sleep(seconds)
            audio = recorder.stop()
        except (KeyboardInterrupt, asyncio.CancelledError):
            recorder.abort()
            print("[MICRÓFONO INACTIVO — enrolamiento cancelado]")
            return 1
        except AudioError as exc:
            recorder.abort()
            print(json.dumps(exc.as_dict(), ensure_ascii=False), file=sys.stderr)
            return 1
        print("[MICRÓFONO INACTIVO]", flush=True)
        if audio.rms < settings.audio_min_rms:
            print("La muestra parece silenciosa y no se guardó.", file=sys.stderr)
            return 1
        write_reference_wav(reference, audio)
        record = create_own_voice_consent(
            reference_path=reference,
            consent_path=consent,
            duration_seconds=audio.duration_seconds,
        )
        database.record_audit(
            session_id=None,
            project_id=project.id,
            event_type="voice_enrollment",
            outcome="success",
            detail={
                "reference_sha256": record["reference_sha256"],
                "duration_seconds": record["duration_seconds"],
                "source": record["source"],
                "audio_content_stored_in_audit": False,
            },
        )
        print(f"Muestra local guardada: {reference}")
        print(
            "La voz Chatterbox ya está seleccionada. Ejecuta --audio-doctor y luego "
            "--voice para validarla."
        )
        return 0

    if args.verify_audit:
        valid, errors = database.verify_audit_chain()
        print("Cadena de auditoría válida." if valid else "Cadena de auditoría inválida.")
        for error in errors:
            print(f"- {error}")
        return 0 if valid else 1

    if args.list_projects:
        for item in projects.list():
            marker = "*" if item.is_active else " "
            print(
                f"{marker} {item.id}  {item.status.value}  {item.name}  {item.root_path}  "
                f"permissions={json.dumps(item.permissions, ensure_ascii=False, sort_keys=True)}"
            )
        return 0

    if args.register_project:
        if args.project_path is None:
            print("--register-project requiere --project-path.", file=sys.stderr)
            return 2
        created = projects.create(args.register_project, args.project_path)
        database.record_audit(
            session_id=None,
            project_id=created.id,
            event_type="project_registered",
            outcome="success",
            detail={"name": created.name, "root_path": created.root_path},
        )
        print(json.dumps(created.model_dump(mode="json"), ensure_ascii=False, indent=2))
        return 0

    if args.activate_project:
        project = projects.activate(args.activate_project)
        database.record_audit(
            session_id=None,
            project_id=project.id,
            event_type="project_activated",
            outcome="success",
        )
        print(f"Proyecto activo: {project.name} ({project.root_path})")
        return 0

    if args.set_project_permission:
        permission, separator, raw_enabled = args.set_project_permission.partition("=")
        values = {"true": True, "1": True, "yes": True, "si": True, "sí": True,
                  "false": False, "0": False, "no": False}
        normalized_enabled = raw_enabled.strip().casefold()
        if not separator or normalized_enabled not in values:
            print(
                "--set-project-permission requiere PERMISSION=true|false.",
                file=sys.stderr,
            )
            return 2
        project = projects.set_permission(
            project.id, permission, values[normalized_enabled]
        )
        database.record_audit(
            session_id=None,
            project_id=project.id,
            event_type="project_permission_changed",
            outcome="success",
            detail={
                "permission": permission.strip().casefold(),
                "enabled": values[normalized_enabled],
                "source": "trusted_local_cli",
            },
        )
        print(json.dumps(project.model_dump(mode="json"), ensure_ascii=False, indent=2))
        return 0

    if args.profile_list:
        print(json.dumps([item.model_dump(mode="json") for item in memory.list_profile()], ensure_ascii=False, indent=2))
        return 0

    if args.profile_set:
        key, separator, value = args.profile_set.partition("=")
        if not separator or not key.strip():
            print("--profile-set requiere KEY=VALUE.", file=sys.stderr)
            return 2
        entry = memory.set_profile(key, value, explicit=True)
        database.record_audit(
            session_id=None,
            project_id=project.id,
            event_type="profile_updated",
            outcome="success",
            detail={"key": entry.key, "source": entry.source},
        )
        print(json.dumps(entry.model_dump(mode="json"), ensure_ascii=False, indent=2))
        return 0

    if args.profile_delete:
        removed = memory.delete_profile(args.profile_delete)
        database.record_audit(
            session_id=None,
            project_id=project.id,
            event_type="profile_deleted",
            outcome="success" if removed else "not_found",
            detail={"key": args.profile_delete.casefold()},
        )
        print("Preferencia eliminada." if removed else "Preferencia no encontrada.")
        return 0 if removed else 1

    if args.decision_history:
        projects.require_permission(project, "memory")
        state = memory.get_decision_state(
            project_id=project.id, topic=args.decision_history
        )
        database.record_audit(
            session_id=None,
            project_id=project.id,
            event_type="temporal_decision_read",
            outcome="success" if state.current else "not_found",
            detail={"topic": state.topic, "history_count": len(state.history)},
        )
        print(json.dumps(state.model_dump(mode="json"), ensure_ascii=False, indent=2))
        return 0 if state.current else 1

    if args.forget_decision:
        projects.require_permission(project, "memory")
        removed = memory.forget_decision_topic(
            project_id=project.id, topic=args.forget_decision, explicit=True
        )
        database.record_audit(
            session_id=None,
            project_id=project.id,
            event_type="temporal_decision_forgotten",
            outcome="success" if removed else "not_found",
            # No se registra el texto, motivo ni procedencia eliminados.
            detail={"topic": args.forget_decision.strip(), "records_removed": removed},
        )
        print(f"Cadena eliminada ({removed} registro(s)).")
        return 0 if removed else 1

    if args.record_decision or args.record_pending or args.record_session_summary:
        projects.require_permission(project, "memory")
        if args.record_decision:
            if not args.decision_topic or not args.decision_reason:
                print(
                    "--record-decision requiere --decision-topic y --decision-reason.",
                    file=sys.stderr,
                )
                return 2
            state = memory.set_decision(
                project_id=project.id,
                topic=args.decision_topic,
                statement=args.record_decision,
                rationale=args.decision_reason,
                source=DecisionSource(
                    kind="explicit_user", reference="trusted_local_cli"
                ),
                confirmed=True,
            )
            database.record_audit(
                session_id=None,
                project_id=project.id,
                event_type="temporal_decision_changed",
                outcome="success",
                detail={
                    "decision_id": state.current.id,
                    "topic": state.topic,
                    "supersedes_id": state.current.supersedes_id,
                    "source_kind": state.current.source.kind,
                },
            )
            print(json.dumps(state.model_dump(mode="json"), ensure_ascii=False, indent=2))
            return 0
        elif args.record_pending:
            kind = EpisodicKind.PENDING_TASK
            summary = args.record_pending
        else:
            kind = EpisodicKind.SESSION_SUMMARY
            summary = args.record_session_summary
        event = memory.add_episode(
            project_id=project.id,
            kind=kind,
            summary=summary,
            source="trusted_local_cli",
            confirmed=True,
        )
        database.record_audit(
            session_id=None,
            project_id=project.id,
            event_type="episodic_memory_added",
            outcome="success",
            detail={"event_id": event.id, "kind": event.kind.value, "confirmed": True},
        )
        print(json.dumps(event.model_dump(mode="json"), ensure_ascii=False, indent=2))
        return 0

    try:
        embeddings = await create_embedding_provider(
            settings,
            allow_start=bool(args.doctor or args.index_project or args.rag_query),
        )
    except EmbeddingProviderError as exc:
        print(f"Error de embeddings [{exc.code}]: {exc}", file=sys.stderr)
        return 1

    rag_repository = RagRepository(database)
    rag_service = RagService(
        settings=settings,
        projects=projects,
        repository=rag_repository,
        embeddings=embeddings,
    )
    indexer = ProjectIndexer(
        settings=settings,
        database=database,
        policy=policy,
        projects=projects,
        repository=rag_repository,
        embeddings=embeddings,
    )
    registry = build_default_registry(
        settings, policy, rag_service=rag_service, memory=memory, projects=projects
    )
    executor = ActionExecutor(
        settings=settings,
        database=database,
        registry=registry,
        policy=policy,
        projects=projects,
        memory=memory,
    )

    if args.doctor:
        provider = await create_model_provider(
            settings,
            allow_start=args.start_model_server or settings.llama_auto_start,
        )
        try:
            return await run_doctor(settings, database, provider, embeddings)
        finally:
            await provider.aclose()
            await embeddings.aclose()

    if args.index_project:
        try:
            stats = await indexer.index_project(project, controller.begin_turn())
            print(json.dumps(stats.model_dump(mode="json"), ensure_ascii=False, indent=2))
            return 0 if not stats.errors else 1
        finally:
            await embeddings.aclose()

    if args.rag_query:
        try:
            result = await rag_service.search(
                project=project,
                query=args.rag_query,
                mode=args.rag_mode,
                cancellation=controller.begin_turn(),
            )
            payload = result.model_dump(mode="json")
            for item, evidence in zip(payload["evidence"], result.evidence, strict=True):
                item["citation"] = evidence.citation
            database.record_audit(
                session_id=None,
                project_id=project.id,
                event_type="rag_query",
                outcome="success" if result.sufficient_evidence else "insufficient_evidence",
                intent=args.rag_query,
                detail={
                    "mode": args.rag_mode,
                    "citations": [item.citation for item in result.evidence],
                    "source_hashes": [item.source_hash for item in result.evidence],
                    "elapsed_seconds": result.elapsed_seconds,
                },
            )
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0 if result.sufficient_evidence else 1
        finally:
            await embeddings.aclose()

    if args.simulate_tool:
        try:
            arguments = json.loads(args.arguments)
            if not isinstance(arguments, dict):
                raise ValueError("--arguments debe ser un objeto JSON.")
        except (json.JSONDecodeError, ValueError) as exc:
            print(f"Argumentos inválidos: {exc}", file=sys.stderr)
            return 2
        request = ActionRequest(
            tool=args.simulate_tool,
            arguments=arguments,
            expected_result=args.expected_result,
            intent="Simulación solicitada desde la CLI local.",
            project_id=project.id,
        )
        result = await executor.execute(
            request,
            cancellation=controller.begin_turn(),
            budget=ActionBudget(settings.budget_limits()),
            confirmation_callback=confirm_action,
            dry_run=True,
        )
        print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
        await embeddings.aclose()
        return 0 if result.ok else 1

    # En voz CUDA, Chatterbox debe reservar su memoria antes de que
    # llama-server calcule el offload automático. El orden inverso deja poca
    # memoria contigua y provoca paginación WDDM, multiplicando la latencia TTS.
    voice_stt = None
    voice_tts = None
    voice_presence = None
    if args.voice:
        from .audio import create_stt_provider, create_tts_provider
        from .control_center.presence import VoicePresenceClient

        voice_presence = VoicePresenceClient.discover(settings.project_dir)
        print("Cargando STT y TTS locales…", flush=True)
        if voice_presence is not None:
            voice_presence.set_state("loading")
        try:
            voice_stt = create_stt_provider(settings)
            voice_tts = create_tts_provider(settings)
            await asyncio.gather(voice_stt.warmup(), voice_tts.warmup())
        except BaseException as exc:
            if voice_presence is not None:
                voice_presence.set_error(str(exc))
                voice_presence.set_state("error")
            if voice_stt is not None:
                await voice_stt.aclose()
            if voice_tts is not None:
                await voice_tts.aclose()
            await embeddings.aclose()
            raise

    try:
        provider = await create_model_provider(
            settings,
            allow_start=args.start_model_server or settings.llama_auto_start,
        )
    except BaseException as exc:
        if voice_presence is not None:
            voice_presence.set_error(str(exc))
            voice_presence.set_state("error")
            voice_presence.close()
        if voice_stt is not None:
            await voice_stt.aclose()
        if voice_tts is not None:
            await voice_tts.aclose()
        await embeddings.aclose()
        raise
    orchestrator = Orchestrator(
        settings=settings,
        database=database,
        provider=provider,
        registry=registry,
        executor=executor,
        approval_callback=(deny_noninteractive_confirmation if args.voice else confirm_action),
        latency_log=default_latency_log(settings.data_dir),
    )
    session_id = database.create_session(project_id=project.id)

    def write_delta(delta: str) -> None:
        print(delta, end="", flush=True)

    try:
        if args.voice:
            from .audio import (
                SoundDevicePlayer,
                SoundDeviceRecorder,
                VoiceSessionManager,
                VoiceState,
                WindowsKeyChord,
                run_push_to_talk_loop,
            )
            presence = voice_presence

            def voice_state(state: VoiceState) -> None:
                labels = {
                    VoiceState.IDLE: "[LISTO]",
                    VoiceState.RECORDING: "[MICRÓFONO ACTIVO — habla ahora]",
                    VoiceState.TRANSCRIBING: "[TRANSCRIBIENDO]",
                    VoiceState.PROCESSING: "[PROCESANDO]",
                    VoiceState.SPEAKING: "[REPRODUCIENDO VOZ]",
                    VoiceState.CANCELLING: "[CANCELANDO]",
                    VoiceState.ERROR: "[ERROR EN EL TURNO DE VOZ]",
                }
                print(f"\n{labels[state]}", flush=True)
                if presence is not None:
                    presence.set_state(state.value)

            def voice_transcript(text: str) -> None:
                print(f"\nTú (transcripción)> {text}", flush=True)
                print(f"\n{settings.assistant_name}> ", end="", flush=True)
                if presence is not None:
                    presence.response = ""
                    presence.error = ""
                    presence.set_transcript(text)

            def voice_delta(delta: str) -> None:
                print(delta, end="", flush=True)
                if presence is not None:
                    presence.append_response(delta)

            def voice_error(message: str) -> None:
                print(f"\nDetalle: {message}", flush=True)
                if presence is not None:
                    presence.set_error(message)

            recorder = SoundDeviceRecorder(
                selector=settings.audio_input_device,
                target_sample_rate=settings.audio_sample_rate,
                max_seconds=settings.audio_max_record_seconds,
            )
            player = SoundDevicePlayer(selector=settings.audio_output_device)
            manager = VoiceSessionManager(
                database=database,
                orchestrator=orchestrator,
                project=project,
                session_id=session_id,
                cancellation=controller,
                recorder=recorder,
                player=player,
                stt=voice_stt,
                tts=voice_tts,
                min_record_seconds=settings.audio_min_record_seconds,
                min_rms=settings.audio_min_rms,
                max_turn_seconds=settings.max_runtime_seconds,
                max_record_seconds=settings.audio_max_record_seconds,
                on_state=voice_state,
                on_transcript=voice_transcript,
                on_text_delta=voice_delta,
                on_error=voice_error,
            )
            try:
                if presence is not None:
                    # VoiceSessionManager nace en IDLE, por lo que no emite una
                    # transición hasta el primer turno. La interfaz gráfica sí
                    # necesita conocer que el calentamiento ya terminó.
                    presence.set_state("idle")
                print(
                    f"Voz local lista — proyecto: {project.name}\n"
                    f"Mantén {settings.audio_ptt_hotkey} para hablar; suelta para enviar.\n"
                    f"Cancela el turno con {settings.audio_cancel_hotkey}. Ctrl+C termina Mark."
                )
                await run_push_to_talk_loop(
                    manager,
                    ptt=WindowsKeyChord.parse(settings.audio_ptt_hotkey),
                    cancel=WindowsKeyChord.parse(settings.audio_cancel_hotkey),
                    text_request_source=(
                        None
                        if presence is None
                        else lambda: asyncio.to_thread(
                            presence.fetch_text_request, wait_seconds=5.0
                        )
                    ),
                )
            except Exception as exc:
                if presence is not None:
                    presence.set_error(str(exc))
                    presence.set_state("error")
                # Si el fallo ocurrió durante warmup, el bucle PTT todavía no
                # tuvo oportunidad de cerrar los proveedores y su worker.
                await manager.close()
                raise
            finally:
                if presence is not None and presence.state != "error":
                    presence.close()
            return 0

        if args.once:
            try:
                await orchestrator.chat(
                    session_id,
                    project,
                    args.once,
                    controller.begin_turn(),
                    on_text_delta=write_delta,
                )
                print()
                return 0
            except ModelProviderError as exc:
                print(f"\nError de modelo [{exc.code}]: {exc}", file=sys.stderr)
                return 1

        print(f"{settings.assistant_name} local — {provider.name} / {settings.model}")
        print(f"Proyecto activo: {project.name} ({project.root_path})")
        print("Comandos: :new, :status, :projects, :audit, :quit. Ctrl+C detiene la sesión.")
        while True:
            active_project = projects.active()
            if active_project is not None and active_project.id != project.id:
                project = active_project
                session_id = database.create_session(project_id=project.id)
                print(
                    f"\nContexto cambiado al proyecto activo: {project.name} "
                    f"({project.root_path}). Nueva conversación creada."
                )
            try:
                text = input("\nTú> ").strip()
            except (EOFError, KeyboardInterrupt):
                controller.cancel_current("Interrupción desde la consola.")
                print("\nSesión terminada.")
                return 0
            if not text:
                continue
            command = text.casefold()
            if command in {":quit", ":exit", "salir"}:
                controller.cancel_current("Sesión terminada por el usuario.")
                return 0
            if command == ":new":
                session_id = database.create_session(project_id=project.id)
                print("Nueva conversación creada.")
                continue
            if command == ":status":
                print(json.dumps(database.counts(), ensure_ascii=False, indent=2))
                continue
            if command == ":projects":
                for item in projects.list():
                    marker = "*" if item.is_active else " "
                    print(f"{marker} {item.id}  {item.name}  {item.root_path}")
                continue
            if command == ":audit":
                valid, errors = database.verify_audit_chain()
                print("Cadena de auditoría válida." if valid else "Cadena inválida: " + "; ".join(errors))
                continue
            try:
                print(f"\n{settings.assistant_name}> ", end="", flush=True)
                await orchestrator.chat(
                    session_id,
                    project,
                    text,
                    controller.begin_turn(),
                    on_text_delta=write_delta,
                )
                print()
            except ModelProviderError as exc:
                print(f"\nError de modelo [{exc.code}]: {exc}")
            except KeyboardInterrupt:
                controller.cancel_current("Interrupción desde la consola.")
                print("\nTurno cancelado.")
    finally:
        await provider.aclose()
        await embeddings.aclose()


def main(argv: list[str] | None = None) -> int:
    if os.name == "nt":
        for stream in (sys.stdout, sys.stderr):
            if hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8")
    try:
        return asyncio.run(async_main(argv))
    except KeyboardInterrupt:
        print("\nCancelado por el usuario.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())

