# Mark

**Mark** (Mark Scout) es el asistente personal local de este repositorio: la
app de escritorio de Windows de siempre (`runtime\desktop\JarvisLocal.exe`,
WPF + WebView2), con su modo llamada, pulsar para hablar, panel **Núcleo**,
módulos, **Sistemas**, memoria por proyecto, RAG, herramientas con política y
auditoría, y **su propia voz**. Todo eso vive en `src/jarvis_local/`,
`desktop/JarvisLocal.Desktop/`, `config/jarvis.toml` y `scripts/*.ps1`
(documentación en [docs/mark/](docs/mark/)).

## Upgrade: OpenJarvis

[OpenJarvis](https://github.com/open-jarvis/OpenJarvis) (Apache-2.0) está
instalado completo en este repositorio como upgrade de Mark, no como reemplazo.
Detalle, matriz de capacidades y verificaciones: [docs/mark/openjarvis-integracion.md](docs/mark/openjarvis-integracion.md).

- **Cerebro.** El orquestador de Mark consulta el modelo a través de los motores
  de OpenJarvis (`[llm] provider = "openjarvis"`, Ollama, `qwen3:8b`). La política,
  los presupuestos, la memoria y la auditoría siguen siendo de Mark. Para volver al
  llama-server propio: `provider = "llama_cpp"` (ver `config/jarvis.toml`).
- **Capacidades de Mark.** El botón del encabezado abre, dentro de la misma
  ventana, la interfaz de OpenJarvis: agentes, Deep Research, skills, memoria,
  conectores, automatizaciones, dashboard, logs y ajustes. Se sirve solo en
  `127.0.0.1` (puerto propio desde 8790), sin login, con hogar propio en `data\openjarvis`.
- **La política de Mark manda.** Los agentes de OpenJarvis heredan las
  restricciones de Mark: leen solo en `allowed_roots` y no escriben, no ejecutan
  código, no salen a la red ni envían por canales salvo que `config/jarvis.toml`
  lo permita.
- **Voz y GPU.** OpenJarvis usa la voz enrolada de Mark (`mark_voice`). Ambos
  chats usan el mismo contexto de Ollama, y la voz en CUDA se carga antes que el
  modelo.
- **Siempre Mark.** Prompt, persona, comando `mark` y los textos de la interfaz
  que nombran al asistente dicen Mark.
- **Actualizar OpenJarvis:** `python scripts/update_openjarvis.py`.

## Instalar o actualizar (Windows)

Doble clic en `Crear-Acceso-Directo-Mark.bat`. Localiza o clona el repositorio
en `%USERPROFILE%\Documents\AI Local\JarvisLocal` (variable `MARK_DIR`) y ejecuta
`scripts\Install-Mark.ps1`, que:

1. Cierra solo los procesos de Mark.
2. Instala dependencias con `uv` (Python 3.12), incluido el componente Rust de OpenJarvis. Necesita las MSVC Build Tools y pide permiso para instalarlas.
3. Compila la interfaz de capacidades cuando cambia.
4. Asegura Ollama con `qwen3:8b`.
5. Republica `JarvisLocal.exe` cuando cambia su código (.NET 8 SDK).
6. Crea el icono **Mark** en el escritorio.

El script deja un registro en `data\logs` y no toca `data\`, `models\` ni los entornos de voz.

## Voz de Mark fuera de esta PC

En tu PC la voz ya está enrolada y OpenJarvis la reutiliza. En otro equipo,
`mark_voice` falla cerrado (OpenJarvis cae a Kokoro `em_alex`) hasta instalarla:

Windows (CUDA):

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\mark-voice\Setup-MarkVoice.ps1
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\mark-voice\Enroll-MarkVoice.ps1 -TextFile .\transcripcion.txt
```

Linux/macOS: `scripts/mark-voice/setup-mark-voice.sh` y luego
`uv run python -m openjarvis.speech.mark_voice enroll --reference "voice/mark_modelo_de voz1.mp3" --text-file transcripcion.txt --confirm-own-voice`.

`transcripcion.txt` debe contener el texto literal que se dice en la muestra.
Comprueba el estado con `uv run python -m openjarvis.speech.mark_voice status` y
prueba con `uv run python -m openjarvis.speech.mark_voice say "Hola, soy Mark"`.
Los ajustes viven en `[speech.mark_voice]` de `~/.openjarvis/config.toml`
(`device = "cpu"` si no hay GPU).

---

_Documentación original de OpenJarvis:_

<div align="center">
  <img alt="OpenJarvis" src="assets/OpenJarvis_Horizontal_Logo.png" width="400">

  <p><i>Personal AI, On Personal Devices.</i></p>

  <p>
    <a href="https://arxiv.org/abs/2605.17172"><img src="https://img.shields.io/badge/arXiv-2605.17172-b31b1b.svg" alt="arXiv"></a>
    <a href="https://openjarvis.stanford.edu/"><img src="https://img.shields.io/badge/project-OpenJarvis-blue" alt="Project"></a>
    <a href="https://open-jarvis.github.io/OpenJarvis/"><img src="https://img.shields.io/badge/docs-mkdocs-blue" alt="Docs"></a>
    <img src="https://img.shields.io/badge/python-%3E%3D3.10-blue" alt="Python">
    <img src="https://img.shields.io/badge/license-Apache%202.0-green" alt="License">
    <a href="https://discord.gg/CMVBmDQ5Fj"><img src="https://img.shields.io/badge/discord-join-7289da?logo=discord&logoColor=white" alt="Discord"></a>
    <a href="https://x.com/OpenJarvisAI"><img src="https://img.shields.io/badge/X-@OpenJarvisAI-black?logo=x&logoColor=white" alt="X / Twitter"></a>
  </p>
</div>

---

<div align="center">
  <img alt="OpenJarvis demo reel" src="assets/openjarvis_demo_reel.webp" width="75%">
</div>

---

> **[Documentation](https://open-jarvis.github.io/OpenJarvis/)**
>
> **[Project Site](https://openjarvis.stanford.edu/)**
>
> **[Paper](https://arxiv.org/abs/2605.17172)**
>
> **[Leaderboard](https://open-jarvis.github.io/OpenJarvis/leaderboard/)**
>
> **[Roadmap](https://open-jarvis.github.io/OpenJarvis/development/roadmap/)**

## Why OpenJarvis?

Personal AI agents are exploding in popularity, but nearly all of them still route intelligence through cloud APIs. Your "personal" AI continues to depend on someone else's server. At the same time, our [Intelligence Per Watt](https://www.intelligence-per-watt.ai/) research showed that local language models already handle 88.7% of single-turn chat and reasoning queries, with intelligence efficiency improving 5.3× from 2023 to 2025. The models and hardware are increasingly ready. What has been missing is the software stack to make local-first personal AI practical.

OpenJarvis is that stack. It is a framework for local-first personal AI, built around three core ideas: shared primitives for building on-device agents; evaluations that treat energy, FLOPs, latency, and dollar cost as first-class constraints alongside accuracy; and a learning loop that improves models using local trace data. The goal is simple: make it possible to build personal AI agents that run locally by default, calling the cloud only when truly necessary. OpenJarvis aims to be both a research platform and a production foundation for local AI, in the spirit of PyTorch.

## Installation

Pick your platform and run one command. Each installer handles [uv](https://docs.astral.sh/uv/), the Python venv, Ollama, and a starter model — about 3 minutes on broadband.

| Platform | One-liner |
|---|---|
| **macOS · Linux · WSL2** | `curl -fsSL https://open-jarvis.github.io/OpenJarvis/install.sh \| bash` |
| **Native Windows** | `irm https://open-jarvis.github.io/OpenJarvis/install.ps1 \| iex` |
| **Desktop GUI** | Download `.exe` / `.dmg` / `.deb` / `.rpm` / `.AppImage` from the [latest release](https://github.com/open-jarvis/OpenJarvis/releases) |

Then `jarvis` to start. The Rust extension and larger models continue downloading in the background; `jarvis doctor` shows status.

Platform-specific notes (WSL2 setup, native-Windows scheduled-task service, desktop prerequisites, manual / contributor install): see the [installation docs](https://open-jarvis.github.io/OpenJarvis/getting-started/install/).

## Quick Start

```bash
jarvis                          # start chatting (default: chat-simple)
jarvis gui                      # start the graphical browser interface
jarvis init --preset <name> --force  # replace config with a starter preset
```

`jarvis gui` starts the local API server and frontend, then opens the graphical
chat interface in your default browser. It requires Node.js 22+ and is
available from a source checkout; packaged desktop installers are available
from the [latest release](https://github.com/open-jarvis/OpenJarvis/releases).

> Prefix `jarvis ...` with `uv run`, or `source .venv/bin/activate` first.

| Preset | What it does |
|---|---|
| `morning-digest-mac` / `morning-digest-linux` / `morning-digest-minimal` | Spoken daily briefing from email, calendar, health, news |
| `deep-research` | Multi-hop research across indexed docs with citations |
| `code-assistant` | Agent with code execution, file I/O, and shell access |
| `scheduled-monitor` | Stateful agent on a schedule with memory |
| `chat-simple` | Lightweight conversation, no tools |

Example:

```bash
jarvis init --preset morning-digest-mac --force
jarvis connect gdrive          # one OAuth covers Gmail / Calendar / Tasks
jarvis digest --fresh          # generate and play your first briefing
```

Per-preset deep dives: [morning digest](https://open-jarvis.github.io/OpenJarvis/user-guide/morning-digest/) · [deep research](https://open-jarvis.github.io/OpenJarvis/user-guide/deep-research/) · [code assistant](https://open-jarvis.github.io/OpenJarvis/user-guide/code-assistant/) · [scheduled monitor](https://open-jarvis.github.io/OpenJarvis/user-guide/scheduled-monitor/) · [chat simple](https://open-jarvis.github.io/OpenJarvis/user-guide/chat-simple/) · or the full [quickstart guide](https://open-jarvis.github.io/OpenJarvis/getting-started/quickstart/).

### Skills

Skills teach agents how to better use tools and improve their reasoning. Every skill is a tool — agents discover them from a catalog and invoke them on demand.

```bash
# Install skills from public sources
jarvis skill install hermes:arxiv
jarvis skill sync hermes --category research

# Use skills with any agent
jarvis ask "Use the code-explainer skill to explain this Python code: for i in range(5): print(i*2)"

# Optimize skills from your trace history
jarvis optimize skills --policy dspy

# Benchmark the impact
jarvis bench skills --max-samples 5 --seeds 42
```

Import from [Hermes Agent](https://github.com/NousResearch/hermes-agent) (~150 skills), [OpenClaw](https://github.com/openclaw/skills) (~13,700 community skills), or any GitHub repo. Skills follow the [agentskills.io](https://agentskills.io/specification) open standard.

See the [Skills User Guide](https://open-jarvis.github.io/OpenJarvis/user-guide/skills/) and [Skills Tutorial](https://open-jarvis.github.io/OpenJarvis/tutorials/skills-workflow/) for details.

### Built-in Agents

OpenJarvis ships with eight built-in agents across three execution modes (on-demand, scheduled, continuous):

| Agent | Type | What it does |
|-------|------|-------------|
| `morning_digest` | Scheduled | Daily briefing from email, calendar, health, news — with TTS audio |
| `deep_research` | On-demand | Multi-hop research with citations across web and local docs |
| `monitor_operative` | Continuous | Long-horizon monitoring with memory, compression, and retrieval |
| `orchestrator` | On-demand | Multi-turn reasoning with automatic tool selection |
| `native_react` | On-demand | ReAct (Thought-Action-Observation) loop agent |
| `operative` | Continuous | Persistent autonomous agent with state management |
| `native_openhands` | On-demand | CodeAct — generates and executes Python code |
| `simple` | On-demand | Single-turn chat, no tools |

See the [User Guide](https://open-jarvis.github.io/OpenJarvis/user-guide/morning-digest/) and [Tutorials](https://open-jarvis.github.io/OpenJarvis/tutorials/) for detailed setup instructions.

Full documentation — including Docker deployment, cloud engines, development setup, and tutorials — at **[open-jarvis.github.io/OpenJarvis](https://open-jarvis.github.io/OpenJarvis/)**.

## Community

- **GitHub:** [github.com/open-jarvis/OpenJarvis](https://github.com/open-jarvis/OpenJarvis)
- **Discord:** [discord.gg/CMVBmDQ5Fj](https://discord.gg/CMVBmDQ5Fj)
- **X / Twitter:** [@OpenJarvisAI](https://x.com/OpenJarvisAI)
- **Docs:** [open-jarvis.github.io/OpenJarvis](https://open-jarvis.github.io/OpenJarvis/)

## Contributing

We welcome contributions! See the [Contributing Guide](CONTRIBUTING.md) for incentives, contribution types, and the PR process.

Quick start for contributors:

```bash
git clone https://github.com/open-jarvis/OpenJarvis.git
cd OpenJarvis
uv sync --extra dev
uv run pre-commit install
uv run pytest tests/ -v
```

Browse the [Roadmap](https://open-jarvis.github.io/OpenJarvis/development/roadmap/) for areas where help is needed. Comment **"take"** on any issue to get auto-assigned.

## About

OpenJarvis is part of [Intelligence Per Watt](https://www.intelligence-per-watt.ai/), a research initiative studying the intelligence efficiency of AI systems. The project is developed at [Hazy Research](https://hazyresearch.stanford.edu/) and the [Scaling Intelligence Lab](https://scalingintelligence.stanford.edu/) at [Stanford SAIL](https://ai.stanford.edu/).

## Sponsors

<p>
  <a href="https://www.laude.org/">Laude Institute</a> &bull;
  <a href="https://datascience.stanford.edu/marlowe">Stanford Marlowe</a> &bull;
  <a href="https://cloud.google.com/">Google Cloud Platform</a> &bull;
  <a href="https://lambda.ai/">Lambda Labs</a> &bull;
  <a href="https://ollama.com/">Ollama</a> &bull;
  <a href="https://research.ibm.com/">IBM Research</a> &bull;
  <a href="https://hai.stanford.edu/">Stanford HAI</a>
</p>

## Citation
```bibtex
@misc{saadfalcon2026openjarvispersonalaipersonal,
      title={OpenJarvis: Personal AI, On Personal Devices}, 
      author={Jon Saad-Falcon and Avanika Narayan and Robby Manihani and Tanvir Bhathal and Herumb Shandilya and Hakki Orhun Akengin and Gabriel Bo and Andrew Park and Matthew Hart and Caia Costello and Chuan Li and Christopher Ré and Azalia Mirhoseini},
      year={2026},
      eprint={2605.17172},
      archivePrefix={arXiv},
      primaryClass={cs.LG},
      url={https://arxiv.org/abs/2605.17172}, 
}
```

## License

[Apache 2.0](LICENSE)
