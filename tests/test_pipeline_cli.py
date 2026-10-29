"""The CLI's contract with the modules it wires together.

WHY THIS FILE EXISTS

`hoopal.py` read `info['duration']` from a `get_video_info()` that returns
`duration_seconds`. A one-word mismatch, and it meant the entry point raised
KeyError on every invocation it ever had — including every job the API queued,
since the worker shells out to this exact script.

It stayed invisible for two reasons worth remembering. The crash is in the
banner, three lines in, so there is no partial progress output to suggest the
pipeline ever started. And the original API inferred success from the number of
clips on disk rather than from the exit status, so a student saw "done, 0
baskets" — indistinguishable from a video with no baskets in it.

So these tests check the seam, not the computer vision: that the CLI asks each
module for things that module actually provides. They need no model weights, no
video, and no GPU — a mismatch of this kind is a static property of the code,
and a test that required a 23 MB checkpoint to catch a typo would not be run.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOPAL = REPO_ROOT / "hoopal.py"


def _subscript_keys(source: str, variable: str) -> set[str]:
    """Every literal string key read from `variable[...]` in the source."""
    keys: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if (
            isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Name)
            and node.value.id == variable
            and isinstance(node.slice, ast.Constant)
            and isinstance(node.slice.value, str)
        ):
            keys.add(node.slice.value)
    return keys


def test_every_key_the_cli_reads_from_get_video_info_exists():
    """The regression test for the KeyError.

    Reads the CLI's source for `info[...]` accesses and compares them against
    the keys get_video_info actually builds. Fails against the previous code
    with `duration` named explicitly.
    """
    from ingest import frame_extractor

    wanted = _subscript_keys(HOOPAL.read_text(encoding="utf-8"), "info")
    assert wanted, "no info[...] accesses found — did hoopal.py stop using get_video_info?"

    provided = _subscript_keys(inspect.getsource(frame_extractor.get_video_info), "info")
    # The dict literal's own keys, plus anything assigned afterwards.
    tree = ast.parse(inspect.getsource(frame_extractor.get_video_info).lstrip())
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            provided |= {k.value for k in node.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)}

    missing = wanted - provided
    assert not missing, (
        f"hoopal.py reads {sorted(missing)} from get_video_info(), which never returns "
        f"{'it' if len(missing) == 1 else 'them'}. Provided keys: {sorted(provided)}"
    )


def test_get_video_info_reports_duration_under_the_name_the_cli_uses():
    """Pin the name from the other side, so renaming the key breaks here too."""
    from ingest.frame_extractor import get_video_info

    source = inspect.getsource(get_video_info)
    assert "duration_seconds" in source


@pytest.mark.parametrize(
    ("module_path", "symbol", "required_params"),
    [
        ("ingest.frame_extractor", "extract_frames", {"video_path", "sample_every_n"}),
        ("detect.basket_detector", "BasketDetector", {"model_path", "confidence"}),
        ("clips.clip_exporter", "export_clips", {"video_path", "events", "output_dir", "pre_roll", "post_roll"}),
    ],
)
def test_the_cli_calls_each_module_with_parameters_it_accepts(module_path, symbol, required_params):
    """The same class of bug, one layer out.

    hoopal.py passes all of these by keyword. A rename on either side is a
    TypeError at runtime — and, as above, one nothing would notice until a
    student uploaded a video.
    """
    import importlib

    target = getattr(importlib.import_module(module_path), symbol)
    accepted = set(inspect.signature(target).parameters)
    missing = required_params - accepted
    assert not missing, f"{symbol} does not accept {sorted(missing)}; hoopal.py passes them by keyword"


def test_the_cli_parses_and_defines_main():
    """Cheapest possible guard against a syntax error reaching the server.

    The worker runs this file with `sys.executable hoopal.py`, so a parse error
    surfaces only as a non-zero exit inside a container.
    """
    tree = ast.parse(HOOPAL.read_text(encoding="utf-8"))
    assert any(
        isinstance(node, ast.FunctionDef) and node.name == "main" for node in ast.walk(tree)
    ), "hoopal.py no longer defines main()"
