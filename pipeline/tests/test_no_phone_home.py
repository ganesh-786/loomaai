"""Looma must make no outside connections at search time (Skip: "no external accesses").

Seen 2026-11-02: ONNX Runtime 1.31.1 opened HTTPS connections to outside hosts from the looma-search container as
soon as it loaded, even after onnxruntime.disable_telemetry_events(). Only the ORT_DISABLE_TELEMETRY environment
variable, set before the library loads, stopped them (probe: zero outside connections). These tests keep it set.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

PIPELINE = Path(__file__).resolve().parents[1]


def test_importing_the_package_turns_off_onnx_runtime_telemetry_before_it_loads():
    env = {key: value for key, value in os.environ.items() if key != "ORT_DISABLE_TELEMETRY"}
    script = "import os, sys, looma_pipeline; print(os.environ.get('ORT_DISABLE_TELEMETRY'), 'onnxruntime' in sys.modules)"
    result = subprocess.run([sys.executable, "-c", script], env=env, capture_output=True, text=True, timeout=60)
    assert result.stdout.split() == ["1", "False"], result.stderr


@pytest.mark.parametrize("dockerfile", ["Dockerfile", "Dockerfile.serve"])
def test_both_images_turn_off_onnx_runtime_telemetry(dockerfile):
    assert "ORT_DISABLE_TELEMETRY=1" in (PIPELINE / dockerfile).read_text(encoding="utf-8")
