"""End-to-end self-update probe.

The picker probe answers "does Tk draw what we think it draws?"; this one
answers the update question the unit tests cannot: **does an update actually
work on a real Windows machine?**

Nothing here is simulated. The probe is built into a onefile executable,
placed where an installed copy would live, and told to install a *different*
build of itself; it does that through the application's own
`install_update_and_restart`, so the swap script, the environment handling and
the start-up handshake under test are the real ones. Started again by that
script, it behaves like the app does once its window is up
(`mark_startup_complete`) and writes a report the CI job can inspect — which is
how "the new build is live, and it started with a clean onefile environment"
becomes an assertion instead of a hope.

Usage (see `.github/workflows/diagnostics.yml`):

    probe --self-update TARGET NEW_EXE NEW_VERSION [--watch SECONDS]
    probe                     # what the swap script starts: report and signal
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import auto_typer as at  # noqa: E402


def report(line: str) -> None:
    """Say something loudly *and* leave it behind for the CI job to read."""
    print(line, flush=True)
    try:
        path = at.app_data_dir() / "probe-report.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError:
        pass


def describe_environment() -> str:
    """What this build is, and whether it is using its *own* extraction folder.

    A onefile child always inherits `_PYI_*` variables — they are how the
    bootloader tells it where its files are — so "no variables at all" is not
    the health check. The check is that
    `_PYI_APPLICATION_HOME_DIR` names *this* build's extraction directory:
    anything else means it is looking at another process's folder, which is the
    state that dies with "Error loading Python DLL".
    """
    home = at.os.environ.get("_PYI_APPLICATION_HOME_DIR") or ""
    meipass = getattr(at.sys, "_MEIPASS", "") or ""
    own = bool(home) and bool(meipass) and (at.os.path.normcase(home)
                                            == at.os.path.normcase(meipass))
    return (f"v{at.APP_VERSION} started from {at.sys.executable} "
            f"(frozen={at.is_frozen()}, onefile-home={home or 'unset'} "
            f"({'own' if own else 'NOT own'}), meipass={meipass or 'unset'})")


def main(argv):
    at.scrub_pyinstaller_runtime_environment()
    if argv and argv[0] == "--self-update":
        target, new_exe, version = Path(argv[1]), Path(argv[2]), argv[3]
        watch = 60
        if "--watch" in argv:
            watch = int(argv[argv.index("--watch") + 1])
        # Stage it exactly like a downloaded update, so the script is given the
        # same kind of file the app hands it (and the built artefact survives).
        staged = at.staging_path(at.UpdateAsset(name="AutoTyper.exe", url="file://" + str(new_exe)))
        staged.parent.mkdir(parents=True, exist_ok=True)
        staged.write_bytes(new_exe.read_bytes())
        script = at.install_update_and_restart(staged, target, version=version,
                                               expected_size=staged.stat().st_size,
                                               watch_seconds=watch)
        report(f"staged {staged.name} as v{version}; swap script: {script.name}")
        return 0
    # What the swap script starts: the app's start-up handshake, and a report
    # of what this build inherited.
    at.mark_startup_complete()
    report(describe_environment())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
