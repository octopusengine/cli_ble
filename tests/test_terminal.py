"""Tests and an interactive demonstration of the local terminal helpers.

Run the demo with ``python test_terminal.py``.
Run the checks with ``python -m unittest test_terminal.py``.
"""

import io
import time
import unittest
from unittest.mock import patch

from lib.wrapp_terminal import (
    COLOR_ALIASES,
    COLORS,
    RESET,
    StatusLine,
    Terminal,
    clear_line,
    color_text,
    cursor_down,
    cursor_up,
    hide_cursor,
    progress_bar,
    show_cursor,
    spinner,
    status_line,
    strip_ansi,
    style_text,
    terminal_width,
)


class TerminalTests(unittest.TestCase):
    """Fast checks for terminal colors, controls, and dynamic output."""

    def test_standard_palette_has_sixteen_colors(self) -> None:
        self.assertEqual(len(COLORS), 16)
        self.assertEqual(COLORS["red"], "\033[31m")
        self.assertEqual(COLORS["bright_white"], "\033[97m")

    def test_short_aliases_resolve_to_expected_colors(self) -> None:
        expected = {
            "r": "red",
            "g": "green",
            "b": "blue",
            "y": "bright_yellow",
            "w": "bright_white",
            "m": "magenta",
            "c": "cyan",
            "v": "bright_magenta",
        }
        self.assertEqual(COLOR_ALIASES, {**expected, "violet": "bright_magenta"})

    def test_color_text_can_force_color_output(self) -> None:
        self.assertEqual(color_text("test", "cyan", enabled=True), f"\033[36mtest{RESET}")
        self.assertEqual(color_text("test", "v", enabled=True), f"\033[95mtest{RESET}")
        with self.assertRaises(ValueError):
            color_text("test", "not-a-color", enabled=False)

    def test_style_text_combines_styles_and_colors(self) -> None:
        self.assertEqual(
            style_text("test", fg="red", bg="blue", bold=True, underline=True, enabled=True),
            f"\033[1;4;31;44mtest{RESET}",
        )

    def test_strip_ansi_removes_color_and_cursor_sequences(self) -> None:
        self.assertEqual(strip_ansi("\033[31mError\033[0m\033[2A"), "Error")

    def test_progress_bar_and_spinner(self) -> None:
        self.assertEqual(progress_bar(5, 10, width=4), "[##--]  50.0% (5/10)")
        self.assertEqual(progress_bar(12, 10, width=4), "[####] 100.0% (10/10)")
        self.assertEqual(spinner(0), "|")
        self.assertEqual(spinner(3), "\\")

    def test_terminal_width_is_positive(self) -> None:
        self.assertGreaterEqual(terminal_width(), 1)

    def test_status_line_falls_back_to_a_regular_line(self) -> None:
        output = io.StringIO()
        with patch("lib.wrapp_terminal.sys.stdout", output):
            status_line("50 %")

        self.assertEqual(output.getvalue(), "50 %\n")

    def test_status_line_uses_ansi_when_supported(self) -> None:
        output = io.StringIO()
        with patch("lib.wrapp_terminal.sys.stdout", output), patch(
            "lib.wrapp_terminal.ansi_enabled", return_value=True
        ):
            status_line("50 %")

        self.assertEqual(output.getvalue(), "\r50 %\033[K")

    def test_cursor_helpers_emit_expected_control_sequences(self) -> None:
        output = io.StringIO()
        with patch("lib.wrapp_terminal.ansi_enabled", return_value=True):
            clear_line(output)
            cursor_up(2, output)
            cursor_down(3, output)
            hide_cursor(output)
            show_cursor(output)

        self.assertEqual(output.getvalue(), "\r\033[K\033[2A\033[3B\033[?25l\033[?25h")

    def test_status_line_can_log_above_current_status(self) -> None:
        output = io.StringIO()
        with patch("lib.wrapp_terminal.ansi_enabled", return_value=True):
            status = StatusLine(output)
            status.update("Waiting")
            status.log("File completed")
            status.finish("Done")

        self.assertEqual(
            output.getvalue(),
            "\rWaiting\033[K\r\033[KFile completed\n\rWaiting\033[K\rDone\033[K\n",
        )


def show_palette() -> None:
    """Print every named ANSI color and every short alias."""

    terminal = Terminal()
    print("\n16 ANSI colors:")
    for name in COLORS:
        terminal.print(name, f"  {name:<16} sample text")

    print("\nShort aliases:")
    for alias, name in COLOR_ALIASES.items():
        if alias == "violet":
            continue
        label = "violet (bright_magenta)" if alias == "v" else name
        terminal.print(alias, f"  {alias:<6} = {label}")


def show_colored_sentence() -> None:
    """Show how several colors can be composed inside one print call."""

    terminal = Terminal()
    print("\nComposed colored text:")
    print(
        "  "
        + terminal.color("bright_white", "Status:")
        + " "
        + terminal.color("green", "OK")
        + ", "
        + terminal.color("bright_yellow", "warning")
        + ", "
        + terminal.color("bright_red", "error")
    )


def show_text_styles() -> None:
    """Show bold, dim, underline, and background formatting."""

    terminal = Terminal()
    print("\nText styles:")
    print("  " + terminal.style("Bold red", fg="red", bold=True))
    print("  " + terminal.style("Underlined cyan", fg="cyan", underline=True))
    print("  " + terminal.style("Bright text on blue", fg="bright_white", bg="blue"))


def show_progress_bar() -> None:
    """Animate a progress bar and log a message above the status line."""

    print("\nProgress bar:")
    total = 40
    status = StatusLine()
    for current in range(total + 1):
        status.update(progress_bar(current, total))
        if current == total // 2:
            status.log("Halfway completed.")
        time.sleep(0.03)
    status.finish("Done.")


def show_spinner() -> None:
    """Show the four standard spinner frames without cursor movement."""

    print("\nSpinner frames: " + " ".join(spinner(frame) for frame in range(4)))


def main() -> None:
    """Run the interactive terminal demonstration."""

    print("=== lib.wrapp_terminal - demo ===")
    show_palette()
    show_colored_sentence()
    show_text_styles()
    show_progress_bar()
    show_spinner()


if __name__ == "__main__":
    main()
