"""Mark desktop app: a native chat window (no browser, no port, no login).

Launched by ``mark-desktop.exe`` (a GUI entry point, so no console window
opens) or ``python -m openjarvis.mark_desktop``. Everything runs in this
process: the chat talks to the local engine directly, replies can be spoken
with Mark's own voice and the microphone button transcribes speech locally.
"""

from __future__ import annotations

import logging
import queue
import sys
import threading
from pathlib import Path
from typing import Any, Callable, Optional

from openjarvis.mark_desktop.session import MarkChatSession, _StatusConsole

logger = logging.getLogger(__name__)

APP_ID = "Mark.Desktop"
_ASSETS = Path(__file__).resolve().parents[3] / "assets"

# Palette: dark, low-glare, one accent.
BG = "#0f1419"
PANEL = "#171d24"
TEXT = "#e6e9ee"
MUTED = "#8b95a3"
ACCENT = "#4fb3ff"
USER = "#9ad17a"
ERROR = "#ff7b72"


def _prepare_windows_process() -> None:
    """Own taskbar identity (Mark icon) and crisp text on high-DPI screens."""
    if sys.platform != "win32":
        return
    import ctypes

    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass


class MarkWindow:
    def __init__(self, root: Any, session: Optional[MarkChatSession] = None) -> None:
        import tkinter as tk
        from tkinter import font as tkfont

        self.tk = tk
        self.root = root
        self.session = session or MarkChatSession()
        self.ready = False
        self.busy = False
        self._events: "queue.Queue[Callable[[], None]]" = queue.Queue()
        self._voice: Any = None
        self._reply_start = None

        root.title("Mark")
        root.geometry("860x680")
        root.minsize(520, 420)
        root.configure(bg=BG)
        self._set_icon()

        base = tkfont.nametofont("TkDefaultFont").actual("family")
        self.font = (base, 11)
        self.font_bold = (base, 11, "bold")

        header = tk.Frame(root, bg=BG)
        header.pack(fill="x", padx=16, pady=(14, 6))
        tk.Label(header, text="Mark", bg=BG, fg=TEXT, font=(base, 18, "bold")).pack(
            side="left"
        )
        self.status = tk.Label(
            header, text="Conectando…", bg=BG, fg=MUTED, font=self.font
        )
        self.status.pack(side="right")
        self.speak_var = tk.BooleanVar(value=True)
        tk.Checkbutton(
            header,
            text="Voz",
            variable=self.speak_var,
            bg=BG,
            fg=TEXT,
            selectcolor=PANEL,
            activebackground=BG,
            activeforeground=TEXT,
            font=self.font,
        ).pack(side="right", padx=(0, 14))
        self._button(header, "Nueva conversación", self.new_conversation).pack(
            side="right", padx=(0, 14)
        )

        body = tk.Frame(root, bg=PANEL)
        body.pack(fill="both", expand=True, padx=16, pady=6)
        scroll = tk.Scrollbar(body)
        scroll.pack(side="right", fill="y")
        self.transcript = tk.Text(
            body,
            wrap="word",
            bg=PANEL,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            padx=14,
            pady=12,
            font=self.font,
            yscrollcommand=scroll.set,
            state="disabled",
        )
        self.transcript.pack(side="left", fill="both", expand=True)
        scroll.config(command=self.transcript.yview)
        self.transcript.tag_configure("you", foreground=USER, font=self.font_bold)
        self.transcript.tag_configure("mark", foreground=ACCENT, font=self.font_bold)
        self.transcript.tag_configure("note", foreground=MUTED)
        self.transcript.tag_configure("error", foreground=ERROR)

        bottom = tk.Frame(root, bg=BG)
        bottom.pack(fill="x", padx=16, pady=(6, 14))
        buttons = tk.Frame(bottom, bg=BG)
        buttons.pack(side="right", padx=(10, 0))
        self.send_button = self._button(buttons, "Enviar", lambda: self.send())
        self.mic_button = self._button(buttons, "Hablar", self.listen)

        self.entry = tk.Text(
            bottom,
            height=3,
            wrap="word",
            bg=PANEL,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            padx=10,
            pady=8,
            font=self.font,
        )
        self.entry.pack(side="left", fill="x", expand=True)
        self.entry.bind("<Return>", self._on_enter)
        self.entry.focus_set()

        root.protocol("WM_DELETE_WINDOW", self.close)
        root.after(50, self._drain)
        self._run(self._connect)

    # -- plumbing --------------------------------------------------------------

    def _set_icon(self) -> None:
        try:
            if sys.platform == "win32" and (_ASSETS / "mark.ico").is_file():
                self.root.iconbitmap(default=str(_ASSETS / "mark.ico"))
            elif (_ASSETS / "mark.png").is_file():
                self._icon = self.tk.PhotoImage(file=str(_ASSETS / "mark.png"))
                self.root.iconphoto(True, self._icon)
        except Exception:
            logger.debug("Could not set window icon", exc_info=True)

    def _button(self, parent: Any, text: str, command: Callable[[], None]) -> Any:
        button = self.tk.Button(
            parent,
            text=text,
            command=command,
            bg=ACCENT,
            fg="#06121c",
            activebackground="#7cc6ff",
            relief="flat",
            padx=14,
            pady=4,
            font=self.font_bold,
            cursor="hand2",
        )
        button.pack(fill="x", pady=(0, 4))
        return button

    def _ui(self, fn: Callable[[], None]) -> None:
        """Schedule *fn* on the Tk thread (safe from worker threads)."""
        self._events.put(fn)

    def _drain(self) -> None:
        try:
            while True:
                self._events.get_nowait()()
        except queue.Empty:
            pass
        self.root.after(50, self._drain)

    def _run(self, work: Callable[[], None]) -> None:
        threading.Thread(target=work, daemon=True).start()

    def _set_status(self, text: str) -> None:
        self._ui(lambda: self.status.config(text=text))

    def _set_busy(self, busy: bool) -> None:
        def apply() -> None:
            self.busy = busy
            state = "disabled" if busy or not self.ready else "normal"
            self.send_button.config(state=state)
            self.mic_button.config(state=state)

        self._ui(apply)

    def _append(self, text: str, tag: str = "") -> None:
        self.transcript.config(state="normal")
        self.transcript.insert("end", text, tag)
        self.transcript.config(state="disabled")
        self.transcript.see("end")

    # -- actions ---------------------------------------------------------------

    def _connect(self) -> None:
        self._set_busy(True)
        try:
            self.session.connect(status=self._set_status)
        except Exception as exc:
            message = str(exc)
            self._ui(lambda: self._append(f"{message}\n\n", "error"))
            self._set_status("Sin conexión")
            return
        model = self.session.model

        def done() -> None:
            self.ready = True
            self.status.config(text=f"Modelo: {model}")
            self._append("Mark está listo. Escribe o pulsa Hablar.\n\n", "note")

        self._ui(done)
        self._set_busy(False)

    def _on_enter(self, event: Any) -> str:
        if event.state & 0x0001:  # Shift+Enter inserts a newline
            return ""
        self.send()
        return "break"

    def send(self, text: Optional[str] = None) -> None:
        if not self.ready or self.busy:
            return
        if text is None:
            text = self.entry.get("1.0", "end").strip()
            self.entry.delete("1.0", "end")
        if not text:
            return
        self._append("Tú\n", "you")
        self._append(f"{text}\n\n")
        self._append("Mark\n", "mark")
        self._reply_start = self.transcript.index("end-1c")
        self._set_busy(True)
        self._set_status("Pensando…")
        self._run(lambda: self._reply(text))

    def _reply(self, text: str) -> None:
        def show(partial: str) -> None:
            def apply() -> None:
                self.transcript.config(state="normal")
                self.transcript.delete(self._reply_start, "end-1c")
                self.transcript.insert("end", partial)
                self.transcript.config(state="disabled")
                self.transcript.see("end")

            self._ui(apply)

        try:
            reply = self.session.send(text, on_text=show)
        except Exception as exc:
            message = str(exc)
            self._ui(lambda: self._append(f"Error: {message}\n\n", "error"))
            self._set_status(f"Modelo: {self.session.model}")
            self._set_busy(False)
            return
        self._ui(lambda: self._append("\n\n"))
        if self.speak_var.get() and reply:
            self._set_status("Hablando…")
            self._speak(reply)
        self._set_status(f"Modelo: {self.session.model}")
        self._set_busy(False)

    def _voice_session(self) -> Any:
        if self._voice is None:
            from openjarvis.cli._voice_chat import VoiceSession

            self._voice = VoiceSession(self.session.config)
        return self._voice

    def _speak(self, text: str) -> None:
        try:
            from openjarvis.cli._voice_chat import speak

            speak(text, _StatusConsole(self._set_status), self._voice_session())
        except Exception as exc:
            logger.debug("Speech failed", exc_info=True)
            self._set_status(f"Voz no disponible: {exc}")

    def listen(self) -> None:
        if not self.ready or self.busy:
            return
        self._set_busy(True)
        self._set_status("Escuchando… (habla ahora)")
        self._run(self._listen)

    def _listen(self) -> None:
        from openjarvis.cli._voice_chat import VOICE_EXIT, record_voice

        notes: list[str] = []

        def note(message: str) -> None:
            notes.append(message)
            self._set_status(message)

        try:
            result = record_voice(_StatusConsole(note), self._voice_session())
        except Exception as exc:
            result = None
            notes.append(str(exc))
        self._set_busy(False)
        if isinstance(result, str) and result:
            self._ui(lambda: self.send(result))
            return
        if result is VOICE_EXIT and notes:
            message = notes[-1]
            self._ui(lambda: self._append(f"{message}\n\n", "error"))
        self._set_status(f"Modelo: {self.session.model}" if self.ready else "")

    def new_conversation(self) -> None:
        if self.busy:
            return
        self.session.reset()
        self.transcript.config(state="normal")
        self.transcript.delete("1.0", "end")
        self.transcript.config(state="disabled")
        self._append("Nueva conversación.\n\n", "note")

    def close(self) -> None:
        try:
            self.session.close()
            backend = getattr(self._voice, "_tts_backend", None)
            if backend is not None and hasattr(backend, "close"):
                backend.close()
        finally:
            self.root.destroy()


def main() -> None:
    _prepare_windows_process()
    import tkinter as tk

    root = tk.Tk()
    MarkWindow(root)
    root.mainloop()


if __name__ == "__main__":
    main()
