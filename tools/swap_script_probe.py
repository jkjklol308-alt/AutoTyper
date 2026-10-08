"""Run the generated Windows swap script for real, and report what cmd.exe did.

The unit tests check the script's text; the end-to-end job checks that a whole
update works. Neither can tell you *why* a batch file stopped half way through:
cmd.exe parses and executes line by line, kills the whole script on a syntax
error, and - started detached by the app - has nowhere to print it. So this
driver runs the generated script synchronously, with its output captured, twice:
once with a build that signals its start-up and once with a build that never
does. The verdicts, the files they leave and cmd.exe's own output are printed as
JSON for the CI job to publish.

    swap_script_probe.py --work DIR --good NEW.exe --broken BROKEN.exe \
                         --version 9.9.9 [--watch 20]

The scenarios deliberately use the *real* hand-off paths (`update_handoff()`),
because the marker is written by the build itself - the script has to look where
the app puts it, not where a test would prefer.
"""

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import auto_typer as at  # noqa: E402


def cleanup(files: at.UpdateHandoff) -> None:
    for path in (files.marker, files.result, files.log):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


def run_script(script: Path, timeout: float) -> dict:
    """Run one generated .bat the way it runs on a user's machine."""
    try:
        done = subprocess.run(["cmd", "/c", str(script)], capture_output=True,
                              text=True, timeout=timeout)
        return {"exit": done.returncode, "stdout": done.stdout, "stderr": done.stderr}
    except subprocess.TimeoutExpired as expired:
        return {"exit": "timeout", "stdout": expired.stdout, "stderr": expired.stderr}


def scenario(name: str, work: Path, target_source: Path, new_source: Path,
             version: str, watch: int) -> dict:
    """One swap: lay out a folder, generate the script, run it, collect state."""
    root = work / name
    app = root / "app"
    app.mkdir(parents=True, exist_ok=True)
    target = app / "AutoTyper.exe"
    new_exe = root / "staged" / "AutoTyper.exe"
    new_exe.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(target_source, target)
    shutil.copyfile(new_source, new_exe)
    files = at.update_handoff()
    cleanup(files)
    script = root / "AutoTyper-update.bat"
    script.write_text(at.build_windows_swap_script(new_exe, target, version=version,
                                                   handoff=files, watch_seconds=watch),
                      encoding="utf-8")
    started = run_script(script, timeout=watch + 120)
    # The build the script started may still be coming up: give its start-up
    # signal a moment to land before reading the verdict.
    deadline = time.time() + 20
    while time.time() < deadline and not files.result.exists():
        time.sleep(0.5)
    return {
        "name": name,
        "cmd": started,
        "verdict": read(files.result),
        "marker": read(files.marker),
        "log": read(files.log),
        "script_left_behind": script.exists(),
        "new_build_is_in_place": target.read_bytes() == Path(new_source).read_bytes(),
        "backup_taken": Path(str(target) + ".old").exists(),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--work", required=True)
    ap.add_argument("--good", required=True)
    ap.add_argument("--broken", required=True)
    ap.add_argument("--version", default="9.9.9")
    ap.add_argument("--watch", type=int, default=20)
    args = ap.parse_args(argv)

    work = Path(args.work)
    work.mkdir(parents=True, exist_ok=True)
    good, broken = Path(args.good), Path(args.broken)
    report = {
        "kept": scenario("kept", work, good, good, args.version, args.watch),
        "rolled_back": scenario("rolled_back", work, good, broken, "0.0.0", args.watch),
    }
    print(json.dumps(report, indent=2))

    failures = []
    kept, rolled_back = report["kept"], report["rolled_back"]
    if kept["verdict"] != f"ok v{args.version}":
        failures.append(f"a build that signals was not kept: {kept['verdict']!r}")
    if not kept["new_build_is_in_place"]:
        failures.append("the new build was not left in place")
    if not rolled_back["verdict"].startswith("rolled-back v0.0.0"):
        failures.append(f"a build that never signals was not rolled back: "
                        f"{rolled_back['verdict']!r}")
    if "never signalled" not in rolled_back["log"]:
        failures.append("the rollback was not explained in the swap log")
    if failures:
        print("FAILURES: " + "; ".join(failures), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
