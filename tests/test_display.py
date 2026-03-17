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
        from config import REFRESH_INTERVAL_MS, SLIDE_INTERVAL_MS
        from display import BulletinDisplay

        # Cancel any after() callbacks that the constructor schedules.
        display = BulletinDisplay.__new__(BulletinDisplay)
        display._root = tk_root
        display._get_messages = lambda: messages
        display._messages = list(messages)
        display._current_slide = 0
        display._title_text = "Test"
        display._refresh_interval_ms = REFRESH_INTERVAL_MS
        display._slide_interval_ms = SLIDE_INTERVAL_MS
        display._setup_window()
        display._build_widgets()
        return display

    def test_renders_active_messages(self, tk_root):
        display = self._make_display(tk_root, ["Hello World", "Second message"])
        # Only the first slide (index 0) should be visible.
        display._render_messages(["Hello World"])
        content = display._text_widget.cget("text")
        assert "Hello World" in content
        assert "Second message" not in content

    def test_renders_no_messages_placeholder(self, tk_root):
        display = self._make_display(tk_root, [])
        display._render_messages([])
        content = display._text_widget.cget("text")
        assert "No active messages" in content

    def test_renders_error_message(self, tk_root):
        display = self._make_display(tk_root, [])
        display._render_error("Connection refused")
        content = display._text_widget.cget("text")
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

    def test_slide_shows_single_message_not_bullet_list(self, tk_root):
        display = self._make_display(tk_root, ["Slide One", "Slide Two"])
        display._render_messages(["Slide One"])
        content = display._text_widget.cget("text")
        assert "Slide One" in content
        # Slide mode does not use bullet characters.
        assert "\u2022" not in content

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
        content = display._text_widget.cget("text")
        assert content  # some error text was rendered

    def test_render_current_slide_shows_first_message(self, tk_root):
        display = self._make_display(tk_root, ["First", "Second", "Third"])
        display._current_slide = 0
        display._render_current_slide()
        content = display._text_widget.cget("text")
        assert "First" in content
        assert "Second" not in content

    def test_render_current_slide_advances_correctly(self, tk_root):
        display = self._make_display(tk_root, ["First", "Second", "Third"])
        display._current_slide = 1
        display._render_current_slide()
        content = display._text_widget.cget("text")
        assert "Second" in content
        assert "First" not in content

    def test_advance_slide_cycles_through_messages(self, tk_root):
        display = self._make_display(tk_root, ["A", "B", "C"])
        display._current_slide = 0
        # Manually call _advance_slide without rescheduling (override after).
        display._root = tk_root

        # Patch root.after to be a no-op for this test.
        original_after = tk_root.after
        tk_root.after = lambda *args, **kwargs: None

        display._advance_slide()
        assert display._current_slide == 1

        display._advance_slide()
        assert display._current_slide == 2

        # Should wrap around to 0.
        display._advance_slide()
        assert display._current_slide == 0

        tk_root.after = original_after

    def test_advance_slide_single_message_stays_at_zero(self, tk_root):
        display = self._make_display(tk_root, ["Only"])
        display._current_slide = 0
        display._render_current_slide()  # Render initial content.

        original_after = tk_root.after
        tk_root.after = lambda *args, **kwargs: None

        display._advance_slide()
        assert display._current_slide == 0  # should not advance

        # The displayed content should still be the single message.
        content = display._text_widget.cget("text")
        assert "Only" in content

        tk_root.after = original_after

    def test_refresh_resets_slide_index_when_out_of_range(self, tk_root):
        display = self._make_display(tk_root, ["A", "B", "C"])
        display._current_slide = 5  # out of range
        # Return only 2 messages this refresh.
        display._get_messages = lambda: ["X", "Y"]
        display._refresh()
        assert display._current_slide == 0
