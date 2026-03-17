"""
Unit tests for display.py – BulletinDisplay widget behaviour.

These tests use a headless Tk approach: they create the Tk root and
BulletinDisplay but never enter the main loop, instead calling private
methods directly to verify rendering logic.

On a CI machine without a display, tests are skipped via the
DISPLAY / WAYLAND_DISPLAY environment check.
"""

import os
import sys
import pytest

# Skip the entire module if there is no display server.
_HAS_DISPLAY = bool(
    os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
)

pytestmark = pytest.mark.skipif(
    not _HAS_DISPLAY,
    reason="No graphical display available (DISPLAY / WAYLAND_DISPLAY not set).",
)


@pytest.fixture(scope="module")
def tk_root():
    """Create a single Tk root for all display tests in this module."""
    import tkinter as tk

    root = tk.Tk()
    root.withdraw()  # hide the window during tests
    yield root
    root.destroy()


class TestBulletinDisplay:
    def _make_display(self, tk_root, messages):
        from display import BulletinDisplay

        # Cancel any after() callbacks that the constructor schedules.
        display = BulletinDisplay.__new__(BulletinDisplay)
        display._root = tk_root
        display._get_messages = lambda: messages
        display._setup_window()
        display._build_widgets()
        return display

    def test_renders_active_messages(self, tk_root):
        display = self._make_display(tk_root, ["Hello World", "Second message"])
        display._render_messages(["Hello World", "Second message"])
        content = display._text_widget.get("1.0", "end").strip()
        assert "Hello World" in content
        assert "Second message" in content

    def test_renders_no_messages_placeholder(self, tk_root):
        display = self._make_display(tk_root, [])
        display._render_messages([])
        content = display._text_widget.get("1.0", "end").strip()
        assert "No active messages" in content

    def test_renders_error_message(self, tk_root):
        display = self._make_display(tk_root, [])
        display._render_error("Connection refused")
        content = display._text_widget.get("1.0", "end").strip()
        assert "Connection refused" in content

    def test_timestamp_updated_on_render(self, tk_root):
        display = self._make_display(tk_root, ["Test"])
        display._render_messages(["Test"])
        ts = display._timestamp_var.get()
        assert "Updated:" in ts

    def test_timestamp_updated_on_error(self, tk_root):
        display = self._make_display(tk_root, [])
        display._render_error("Oops")
        ts = display._timestamp_var.get()
        assert "Error at" in ts

    def test_bullet_character_present_in_messages(self, tk_root):
        display = self._make_display(tk_root, ["Test"])
        display._render_messages(["Test"])
        content = display._text_widget.get("1.0", "end")
        assert "\u2022" in content

    def test_exit_fullscreen_disables_fullscreen(self, tk_root):
        display = self._make_display(tk_root, [])
        tk_root.attributes("-fullscreen", True)
        display._exit_fullscreen()
        assert not tk_root.attributes("-fullscreen")

    def test_toggle_fullscreen_enables_fullscreen(self, tk_root):
        display = self._make_display(tk_root, [])
        tk_root.attributes("-fullscreen", False)
        display._toggle_fullscreen()
        assert tk_root.attributes("-fullscreen")

    def test_toggle_fullscreen_disables_fullscreen(self, tk_root):
        display = self._make_display(tk_root, [])
        tk_root.attributes("-fullscreen", True)
        display._toggle_fullscreen()
        assert not tk_root.attributes("-fullscreen")

    def test_refresh_calls_get_messages(self, tk_root):
        called = []
        display = self._make_display(tk_root, [])
        display._get_messages = lambda: called.append(True) or ["Msg"]
        display._refresh()
        assert len(called) == 1

    def test_refresh_handles_exception_gracefully(self, tk_root):
        display = self._make_display(tk_root, [])
        display._get_messages = lambda: (_ for _ in ()).throw(RuntimeError("fail"))
        # Should not raise; should render an error instead.
        display._refresh()
        content = display._text_widget.get("1.0", "end").strip()
        assert content  # some error text was rendered
