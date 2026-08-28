"""The worked example in the skill must actually boot.

`worked-example.md` is the file an agent copies first, and its whole claim is
"this validates under --strict and boots clean". That claim was checked once, by
hand, in the session that wrote it -- and by the time it shipped it was false:
the page drew a `pages/` tree of three files and supplied a sample for one, so a
reader who copied it got a study that started, answered 200, and had silently
dropped its instructions and post-study phases.

Nothing caught that, because everything about the pack was checked as text.
This boots it.

Marked `slow`: it starts a real server in a subprocess.
"""

import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

from skillpack import SCRIPTS_DIR, has_potato_repo, potato_repo_path

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Potato's own example directory. Not in the wheel, so this needs a checkout.
EXAMPLE = Path(potato_repo_path("examples", "advanced", "full-study-skeleton"))

#: Features the skeleton switches on, and the count each one logs. A zero here
#: is the failure the pack exists to warn about: enabled, validated, and off.
EXPECTED_COUNTS = {
    r"Loaded (\d+) training instances": 2,
    r"Loaded (\d+) attention check items": 1,
}


def _free_port() -> int:
    """Bind the way the server binds, or the probe hands out a busy port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="module")
def booted(tmp_path_factory):
    if not has_potato_repo():
        pytest.skip("no Potato checkout; set POTATO_REPO")

    work_dir = str(tmp_path_factory.mktemp("worked_example") / "project")
    if os.path.isdir(work_dir):
        shutil.rmtree(work_dir)
    shutil.copytree(EXAMPLE, work_dir)

    port = _free_port()
    log_path = os.path.join(work_dir, "server.log")
    with open(log_path, "w", encoding="utf-8") as log:
        proc = subprocess.Popen(
            [sys.executable, "-m", "potato.flask_server", "start",
             "config.yaml", "-p", str(port)],
            cwd=work_dir, stdout=log, stderr=subprocess.STDOUT,
            start_new_session=True,
        )

    deadline = time.time() + 180
    ready = False
    while time.time() < deadline:
        if proc.poll() is not None:
            break
        text = Path(log_path).read_text(encoding="utf-8", errors="replace")
        if "Running on" in text or "Serving Flask" in text:
            ready = True
            break
        time.sleep(1)

    time.sleep(2)
    log_text = Path(log_path).read_text(encoding="utf-8", errors="replace")

    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        proc.kill()
    proc.wait(timeout=30)

    yield {"ready": ready, "log": log_text, "dir": work_dir}

    shutil.rmtree(work_dir, ignore_errors=True)


@pytest.mark.slow
class TestTheWorkedExampleBoots:
    def test_it_starts(self, booted):
        assert booted["ready"], (
            "the skeleton never reached its readiness line. The last of the log:\n"
            + "\n".join(booted["log"].splitlines()[-30:]))

    def test_no_phase_was_dropped(self, booted):
        dropped = [line for line in booted["log"].splitlines()
                   if "Failed to load phase" in line]
        assert not dropped, (
            "a phase in the worked example was dropped at boot:\n  "
            + "\n  ".join(dropped)
            + "\n\nThe study still starts and answers 200 with the phase missing, "
              "which is exactly the failure this example is supposed to model "
              "avoiding.")

    def test_nothing_raised(self, booted):
        errors = [line for line in booted["log"].splitlines()
                  if "[ERROR]" in line or "Traceback" in line]
        assert not errors, "\n".join(errors[:10])

    @pytest.mark.parametrize("pattern,expected", sorted(EXPECTED_COUNTS.items()))
    def test_every_enabled_feature_actually_loaded(self, booted, pattern, expected):
        match = re.search(pattern, booted["log"])
        assert match, (
            f"the log never reported {pattern!r}. The feature is enabled in "
            f"config.yaml and did not initialise.")
        assert int(match.group(1)) == expected, (
            f"loaded {match.group(1)}, expected {expected}. A count of 0 means "
            f"the study runs with that feature off and nothing says so.")

    def test_boot_and_check_agrees(self, booted):
        """The skill's own script must reach the same verdict as this test."""
        sys.path.insert(0, SCRIPTS_DIR)
        try:
            import boot_and_check
        finally:
            sys.path.pop(0)

        result = boot_and_check.analyse(
            booted["log"], {"training", "attention_checks"})
        assert not result["findings"], (
            "boot_and_check.py reports problems the boot test does not: "
            + json.dumps(result["findings"], indent=2))
        assert result["counts"]["training"] == 2
        assert result["counts"]["attention_checks"] == 1
