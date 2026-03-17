"""
Full-screen Tkinter bulletin-board display for Pi Edge Display Node.

Layout
──────
• Black background, white text – high contrast for a dedicated display panel.
• Header bar showing the application title and last-refresh timestamp.
• Central area listing each active message as a bullet point (•).
• "No active messages" placeholder when the sheet has nothing to show.
• Messages are refreshed on a timer (default 60 s) by calling back into the
  data layer – no local data is persisted between refreshes.

Controls (for operator use)
───────────────────────────
• Esc        – exit full-screen mode (useful for debugging on a desktop).
• F11        – toggle full-screen mode.
• Ctrl+Q     – quit the application.
"""

import logging
import tkinter as tk
from datetime import datetime
from typing import Callable

from config import (
    BACKGROUND_COLOR,
    FONT_FAMILY,
    FONT_SIZE,
    REFRESH_INTERVAL_MS,
    TEXT_COLOR,
    TITLE_TEXT,
)

logger = logging.getLogger(__name__)


class BulletinDisplay:
    """
    Manages a full-screen Tkinter window that displays active bulletin messages.

    Parameters
    ----------
    root:
        A :class:`tkinter.Tk` instance (the caller owns the event loop).
    get_messages_fn:
        A zero-argument callable that returns a ``list[str]`` of active
        message texts.  It may raise; exceptions are caught and displayed as
        an error notice.
    title_text:
        Optional display title (e.g. agency name).  Defaults to
        ``config.TITLE_TEXT``.
    refresh_interval_ms:
        Optional refresh interval in milliseconds.  Defaults to
        ``config.REFRESH_INTERVAL_MS``.
    """

    def __init__(
        self,
        root: tk.Tk,
        get_messages_fn: Callable[[], list[str]],
        *,
        title_text: str | None = None,
        refresh_interval_ms: int | None = None,
    ) -> None:
        self._root = root
        self._get_messages = get_messages_fn
        self._title_text = title_text if title_text is not None else TITLE_TEXT
        self._refresh_interval_ms = (
            refresh_interval_ms if refresh_interval_ms is not None else REFRESH_INTERVAL_MS
        )
        self._setup_window()
        self._build_widgets()
        # Schedule the first refresh immediately once the event loop starts.
        self._root.after(0, self._refresh)

    # ── Window setup ──────────────────────────────────────────────────────────

    def _setup_window(self) -> None:
        self._root.title(self._title_text)
        self._root.configure(bg=BACKGROUND_COLOR)
        self._root.attributes("-fullscreen", True)
        self._root.bind("<Escape>", self._exit_fullscreen)
        self._root.bind("<F11>", self._toggle_fullscreen)
        self._root.bind("<Control-q>", self._quit)
        self._root.bind("<Control-Q>", self._quit)

    # ── Widget construction ───────────────────────────────────────────────────

    def _build_widgets(self) -> None:
        # ── Top header bar ─────────────────────────────────────────────────────
        header_frame = tk.Frame(self._root, bg=BACKGROUND_COLOR)
        header_frame.pack(side=tk.TOP, fill=tk.X, padx=20, pady=(20, 0))

        tk.Label(
            header_frame,
            text=self._title_text,
            font=(FONT_FAMILY, FONT_SIZE // 2, "bold"),
            bg=BACKGROUND_COLOR,
            fg=TEXT_COLOR,
            anchor="w",
        ).pack(side=tk.LEFT)

        self._timestamp_var = tk.StringVar()
        tk.Label(
            header_frame,
            textvariable=self._timestamp_var,
            font=(FONT_FAMILY, FONT_SIZE // 3),
            bg=BACKGROUND_COLOR,
            fg="#AAAAAA",
            anchor="e",
        ).pack(side=tk.RIGHT)

        # ── Separator ──────────────────────────────────────────────────────────
        separator = tk.Frame(self._root, bg=TEXT_COLOR, height=2)
        separator.pack(fill=tk.X, padx=20, pady=10)

        # ── Message area (scrollable) ──────────────────────────────────────────
        msg_frame = tk.Frame(self._root, bg=BACKGROUND_COLOR)
        msg_frame.pack(expand=True, fill=tk.BOTH, padx=20, pady=10)

        scrollbar = tk.Scrollbar(msg_frame, orient=tk.VERTICAL)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self._text_widget = tk.Text(
            msg_frame,
            font=(FONT_FAMILY, FONT_SIZE),
            bg=BACKGROUND_COLOR,
            fg=TEXT_COLOR,
            wrap=tk.WORD,
            state=tk.DISABLED,
            cursor="none",
            relief=tk.FLAT,
            highlightthickness=0,
            yscrollcommand=scrollbar.set,
            spacing1=10,   # Space above each paragraph/line.
            spacing3=10,   # Space below each paragraph/line.
        )
        self._text_widget.pack(side=tk.LEFT, expand=True, fill=tk.BOTH)
        scrollbar.config(command=self._text_widget.yview)

    # ── Refresh logic ─────────────────────────────────────────────────────────

    def _refresh(self) -> None:
        """Fetch current messages and update the display."""
        try:
            messages = self._get_messages()
            self._render_messages(messages)
        except Exception as exc:  # noqa: BLE001
            logger.error("Error fetching messages: %s", exc)
            self._render_error(str(exc))

        # Schedule next refresh.
        self._root.after(self._refresh_interval_ms, self._refresh)

    def _render_messages(self, messages: list[str]) -> None:
        """Update the text widget with *messages*."""
        self._timestamp_var.set(f"Updated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

        self._text_widget.config(state=tk.NORMAL)
        self._text_widget.delete("1.0", tk.END)

        if messages:
            for msg in messages:
                self._text_widget.insert(tk.END, f"\u2022  {msg}\n")
        else:
            self._text_widget.insert(
                tk.END, "No active messages at this time.", "placeholder"
            )
            self._text_widget.tag_config(
                "placeholder",
                foreground="#888888",
                justify="center",
            )

        self._text_widget.config(state=tk.DISABLED)
        logger.debug("Display updated with %d message(s).", len(messages))

    def _render_error(self, message: str) -> None:
        """Display an error notice in the text widget."""
        self._timestamp_var.set(f"Error at {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        self._text_widget.config(state=tk.NORMAL)
        self._text_widget.delete("1.0", tk.END)
        self._text_widget.insert(tk.END, f"\u26a0  {message}", "error")
        self._text_widget.tag_config("error", foreground="#FF4444")
        self._text_widget.config(state=tk.DISABLED)

    # ── Key bindings ──────────────────────────────────────────────────────────

    def _exit_fullscreen(self, _event=None) -> None:
        self._root.attributes("-fullscreen", False)

    def _toggle_fullscreen(self, _event=None) -> None:
        current = self._root.attributes("-fullscreen")
        self._root.attributes("-fullscreen", not current)

    def _quit(self, _event=None) -> None:
        logger.info("Quit requested by operator.")
        self._root.destroy()
