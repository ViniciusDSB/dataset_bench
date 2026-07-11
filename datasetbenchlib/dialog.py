"""Plugin dialog API.

Plugins call into this module to ask the user for input from *inside*
run(), instead of declaring a static parameter schema up front. This
means a plugin's dialogs can be however simple or complex it needs --
one field, ten fields, several separate dialogs in sequence -- without
DatasetBench needing to know its shape ahead of time.

Usage inside a plugin's run():

    from datasetbenchlib import dialog

    dialog.write("Please enter the cut coordinates.")
    values = dialog.request({"x_i": 0, "x_f": 100, "y_i": 0, "y_f": 100})
    x_i, x_f = values["x_i"], values["x_f"]

Widget type is inferred from each field's default value:
    bool          -> checkbox
    int           -> spin box
    float         -> spin box (decimal)
    list[(a, b)]  -> dynamic range list (add/remove rows)
    anything else -> text field

--- How "Apply to Dataset" avoids re-prompting per file ---

DatasetBench calls a plugin's run() once per image when applying to a
whole dataset. To avoid opening a dialog hundreds of times, request()
behaves differently depending on the session DatasetBench started:

  - Interactive session (single-image tab): request() shows a real
    dialog and *records* what the user entered.
  - Replay session (Apply to Dataset): request() does NOT show a
    dialog -- it just returns the next recorded answer, in the same
    order they were originally requested.

This means a plugin should call dialog.request() the same number of
times, in the same order, on every run() call -- i.e. call it up front,
before branching on dataset_type. DatasetBench takes care of starting
and ending these sessions; plugins never touch that part.

--- Standalone use ---

If a plugin is run directly (`python plugins/cut.py ...`), no session
is active. request() then falls back to a plain console prompt, so
plugins stay runnable outside the app.
"""

from __future__ import annotations

from typing import Any

# Session state. Set by DatasetBench (via start_session) right before
# calling a plugin's run(), and cleared right after (via end_session).
# Plugins never touch these directly -- only write()/request().
_active_parent = None
_replay_queue: list[dict] | None = None
_recorded_calls: list[dict] = []
_pending_text: list[str] = []


class PluginCancelled(Exception):
    """Raised by request() when the user cancels the dialog. Plugins can
    just let this propagate -- DatasetBench treats it as a clean abort,
    not an error."""


# --- Plugin-facing API ---------------------------------------------------


def write(text: str) -> None:
    """Queue a line of help/description text to show above the fields in
    the next request() dialog. Can be called more than once to build up
    a short message; cleared after the next request()."""
    _pending_text.append(text)


def request(fields: dict[str, Any]) -> dict[str, Any]:
    """Ask the user for the given fields; returns {name: value}.

    `fields` maps each field name to its default value -- the default's
    Python type also determines the input widget (see module docstring).
    """
    if _replay_queue is not None:
        # Batch/replay mode (Apply to Dataset): don't prompt again, just
        # play back what was recorded during the original interactive run.
        if not _replay_queue:
            raise RuntimeError(
                "Plugin called dialog.request() more times than it did "
                "during the original interactive run -- DatasetBench has "
                "no recorded answer to replay for this call."
            )
        _pending_text.clear()
        return _replay_queue.pop(0)

    if _active_parent is None:
        # No app session bound: standalone use (`python plugins/x.py`).
        values = _request_cli(fields)
        _recorded_calls.append(values)
        return values

    from PySide6.QtWidgets import QDialog

    from ui.plugin_dialog import PluginRequestDialog

    text = "\n".join(_pending_text)
    _pending_text.clear()

    box = PluginRequestDialog(text, fields, _active_parent)
    if box.exec() != QDialog.DialogCode.Accepted:
        raise PluginCancelled("User cancelled the input dialog.")

    values = box.values()
    _recorded_calls.append(values)
    return values


def _request_cli(fields: dict[str, Any]) -> dict[str, Any]:
    if _pending_text:
        print("\n".join(_pending_text))
        _pending_text.clear()

    values: dict[str, Any] = {}
    for name, default in fields.items():
        raw = input(f"{name} [{default}]: ").strip()
        if not raw:
            values[name] = default
        elif default is None:
            values[name] = raw
        else:
            values[name] = type(default)(raw)
    return values


# --- App-facing API (DatasetBench only, not for plugin use) -------------


def start_session(parent, replay: list[dict] | None = None) -> None:
    """Called by DatasetBench right before invoking a plugin's run().

    `replay=None` starts an interactive session (real dialogs, answers
    get recorded). `replay=<list from a previous end_session()>` starts
    a replay session (no dialogs, answers played back in order).
    """
    global _active_parent, _replay_queue, _recorded_calls
    _active_parent = parent
    _pending_text.clear()
    _replay_queue = list(replay) if replay is not None else None
    _recorded_calls = []


def end_session() -> list[dict]:
    """Called by DatasetBench right after a plugin's run() returns (or
    raises). Returns everything recorded during an interactive session
    (empty list for a replay session), and clears session state."""
    global _active_parent, _replay_queue
    recorded = list(_recorded_calls)
    _active_parent = None
    _replay_queue = None
    _pending_text.clear()
    return recorded
