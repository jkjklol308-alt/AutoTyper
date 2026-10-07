"""Tests for the AutoTyper update checker and self-updater.

The updater has four hard behavioural contracts, all covered here:

  1. It compares versions numerically (1.10.0 > 1.9.0), never lexically.
  2. When no update exists (or the check fails), it stays silent:
     ``update_to_announce``/``release_to_announce`` return None and nothing is
     posted to the GUI.
  3. It never forces anything: the user can install, save the .exe for later,
     or keep using the version they have.
  4. It ships the *executable*, not a Python script: the release's .exe asset
     is what gets downloaded, a download that is not a real Windows binary is
     rejected before anything is touched, and a packaged build replaces
     itself and restarts once the old process has exited.
"""

import io
import json
import os
import sys
import tempfile
import types
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

import auto_typer as at

from test_custom_colours import _load_module_with_tk_stub


class FakeResponse:
    """Stands in for the object ``urllib.request.urlopen`` returns.

    Like a real socket it *consumes* what it hands out: a chunked reader such
    as ``download_file`` keeps calling ``read`` until it sees an empty chunk,
    so a stub that replayed its payload forever would look like an endless
    download (and fill the disk).
    """

    def __init__(self, payload=b"", status=200, headers=None):
        self._payload = payload
        self._offset = 0
        self.status = status
        self.headers = headers or {}

    def read(self, limit=None):
        if limit is None:
            chunk = self._payload[self._offset:]
            self._offset = len(self._payload)
            return chunk
        chunk = self._payload[self._offset:self._offset + limit]
        self._offset += len(chunk)
        return chunk

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def make_exe(size: int = 4096) -> bytes:
    """A payload that passes the real "is this a Windows executable?" check."""
    return b"MZ" + b"\x00" * (size - 2)


def release_payload(version="9.9.9", assets=None, url="https://example.invalid/rel"):
    return json.dumps({
        "tag_name": f"v{version}",
        "html_url": url,
        "assets": assets if assets is not None else [
            {"name": "AutoTyper.exe", "browser_download_url": "https://example.invalid/AutoTyper.exe",
             "size": 4096},
        ],
    }).encode()


# ---------------------------------------------------------------------------
# Version handling
# ---------------------------------------------------------------------------
class ParseVersionTests(unittest.TestCase):
    def test_simple_dotted(self):
        self.assertEqual(at.parse_version("1.0.0"), (1, 0, 0))

    def test_v_prefix_and_whitespace(self):
        self.assertEqual(at.parse_version(" v1.10.3 "), (1, 10, 3))

    def test_numeric_prefix_junk(self):
        self.assertEqual(at.parse_version("1.0.0rc1"), (1, 0, 0))

    def test_missing_components(self):
        self.assertEqual(at.parse_version("1.1"), (1, 1))
        self.assertEqual(at.parse_version("7"), (7,))

    def test_garbage_returns_none(self):
        self.assertIsNone(at.parse_version("banana"))
        self.assertIsNone(at.parse_version(""))
        self.assertIsNone(at.parse_version(None))


class IsNewerVersionTests(unittest.TestCase):
    def test_numeric_not_lexical_comparison(self):
        # Lexical string comparison would say "1.10.0" < "1.9.0".
        self.assertTrue(at.is_newer_version("1.10.0", "1.9.0"))

    def test_newer_at_each_level(self):
        self.assertTrue(at.is_newer_version("1.0.1", "1.0.0"))
        self.assertTrue(at.is_newer_version("1.1.0", "1.0.9"))
        self.assertTrue(at.is_newer_version("2.0.0", "1.99.99"))

    def test_equal_is_not_newer(self):
        self.assertFalse(at.is_newer_version("1.0.0", "1.0.0"))
        self.assertFalse(at.is_newer_version("v1.0", "1.0.0"))

    def test_older_is_not_newer(self):
        self.assertFalse(at.is_newer_version("0.9.9", "1.0.0"))

    def test_malformed_never_announces(self):
        self.assertFalse(at.is_newer_version("garbage", "1.0.0"))
        self.assertFalse(at.is_newer_version("1.0.1", "garbage"))


class AppVersionTests(unittest.TestCase):
    def test_shipped_version_is_1_1_2(self):
        self.assertEqual(at.APP_VERSION, "1.1.2")

    def test_points_at_this_repository(self):
        self.assertEqual(at.GITHUB_REPO, "jkjklol308-alt/AutoTyper")
        self.assertIn("jkjklol308-alt/AutoTyper", at.RELEASES_API_URL)
        self.assertTrue(at.EXE_ASSET_NAME.endswith(".exe"))

    def test_real_shipped_file_declares_its_version(self):
        # The published-version lookup depends on this exact declaration style,
        # so pin it against the real module on disk.
        own_source = Path(__file__).with_name("auto_typer.py").read_text(encoding="utf-8")
        self.assertEqual(at.extract_version_from_source(own_source), at.APP_VERSION)
        self.assertIsNotNone(at.parse_version(at.APP_VERSION))

    def test_no_python_script_url_is_advertised(self):
        # v1.0.0 ships the .exe: nothing should send users to a .py file.
        for url in (at.RELEASES_API_URL, at.RELEASES_PAGE_URL, at.UPDATE_PAGE_URL):
            self.assertFalse(url.endswith(".py"), url)


class ExtractVersionTests(unittest.TestCase):
    def test_extracts_declared_version(self):
        source = '"""Doc."""\nAPP_VERSION = "9.9.9"\nX = 1\n'
        self.assertEqual(at.extract_version_from_source(source), "9.9.9")

    def test_single_quotes(self):
        self.assertEqual(at.extract_version_from_source("APP_VERSION = '1.2.3'"), "1.2.3")

    def test_indented_declaration(self):
        self.assertEqual(at.extract_version_from_source('    APP_VERSION = "4.5.6"'), "4.5.6")

    def test_no_declaration_returns_none(self):
        self.assertIsNone(at.extract_version_from_source("print('hello')"))
        self.assertIsNone(at.extract_version_from_source(""))

    def test_prose_mention_is_not_a_declaration(self):
        source = "compares APP_VERSION against the published copy\n"
        self.assertIsNone(at.extract_version_from_source(source))


# ---------------------------------------------------------------------------
# The silence contract
# ---------------------------------------------------------------------------
class UpdateToAnnounceTests(unittest.TestCase):
    def test_no_information_is_silent(self):
        self.assertIsNone(at.update_to_announce(None, "1.0.0"))

    def test_same_version_is_silent(self):
        self.assertIsNone(at.update_to_announce("1.0.0", "1.0.0"))

    def test_older_version_is_silent(self):
        self.assertIsNone(at.update_to_announce("0.9.0", "1.0.0"))

    def test_unparsable_is_silent(self):
        self.assertIsNone(at.update_to_announce("???bad???", "1.0.0"))

    def test_newer_version_is_announced(self):
        self.assertEqual(at.update_to_announce("1.1.0", "1.0.0"), "1.1.0")


class ReleaseToAnnounceTests(unittest.TestCase):
    def _release(self, version):
        return at.ReleaseInfo(version=version, assets=(
            at.UpdateAsset("AutoTyper.exe", "https://example.invalid/AutoTyper.exe", 4096),
        ))

    def test_silent_without_information(self):
        self.assertIsNone(at.release_to_announce(None, "1.0.0"))
        self.assertIsNone(at.release_to_announce(at.ReleaseInfo(version=None), "1.0.0"))

    def test_silent_when_current(self):
        self.assertIsNone(at.release_to_announce(self._release("1.0.0"), "1.0.0"))

    def test_announces_newer_release(self):
        release = self._release("1.4.0")
        self.assertIs(at.release_to_announce(release, "1.0.0"), release)


# ---------------------------------------------------------------------------
# Release payloads and asset selection
# ---------------------------------------------------------------------------
class SelectExeAssetTests(unittest.TestCase):
    def test_prefers_the_canonical_name(self):
        assets = [at.UpdateAsset("notes.txt", "u1"), at.UpdateAsset("AutoTyper.exe", "u2"),
                  at.UpdateAsset("AutoTyper-portable.exe", "u3")]
        self.assertEqual(at.select_exe_asset(assets).name, "AutoTyper.exe")

    def test_accepts_a_renamed_executable(self):
        assets = [at.UpdateAsset("AutoTyper-1.2.0.exe", "u"), at.UpdateAsset("source.zip", "z")]
        self.assertEqual(at.select_exe_asset(assets).url, "u")

    def test_no_executable_returns_none(self):
        self.assertIsNone(at.select_exe_asset([at.UpdateAsset("source.zip", "z")]))
        self.assertIsNone(at.select_exe_asset([]))

    def test_never_picks_a_non_executable(self):
        assets = [at.UpdateAsset("AutoTyper.exe.sha256", "s"), at.UpdateAsset("AutoTyper.exe", "e")]
        self.assertEqual(at.select_exe_asset(assets).url, "e")


class ParseReleasePayloadTests(unittest.TestCase):
    def test_parses_tag_assets_and_page(self):
        release = at.parse_release_payload(release_payload("1.2.3"))
        self.assertEqual(release.version, "1.2.3")
        self.assertEqual(release.page_url, "https://example.invalid/rel")
        self.assertIsNotNone(release.exe_asset)

    def test_accepts_json_text_and_dicts(self):
        text = release_payload("1.2.3").decode()
        self.assertEqual(at.parse_release_payload(text).version, "1.2.3")
        self.assertEqual(at.parse_release_payload(json.loads(text)).version, "1.2.3")

    def test_tolerates_untagged_version(self):
        payload = json.dumps({"name": "1.2.3", "assets": []}).encode()
        self.assertEqual(at.parse_release_payload(payload).version, "1.2.3")

    def test_assets_without_urls_are_dropped(self):
        payload = json.dumps({
            "tag_name": "v1.2.3",
            "assets": [{"name": "AutoTyper.exe"}, {"name": "b.exe", "browser_download_url": "u"},
                       "not-a-dict"],
        }).encode()
        release = at.parse_release_payload(payload)
        self.assertEqual([a.name for a in release.assets], ["b.exe"])

    def test_garbage_payload_is_none(self):
        self.assertIsNone(at.parse_release_payload(b"<html>404 not found</html>"))
        self.assertIsNone(at.parse_release_payload(b"{}"))
        self.assertIsNone(at.parse_release_payload(b""))

    def test_release_without_exe_reports_no_asset(self):
        payload = json.dumps({"tag_name": "v1.2.3", "assets": [
            {"name": "source.zip", "browser_download_url": "u"}]}).encode()
        release = at.parse_release_payload(payload)
        self.assertEqual(release.version, "1.2.3")
        self.assertIsNone(release.exe_asset)


class VersionFromTagTests(unittest.TestCase):
    def test_strips_the_release_prefix(self):
        self.assertEqual(at.version_from_tag("v1.2.3"), "1.2.3")
        self.assertEqual(at.version_from_tag("1.2.3"), "1.2.3")
        self.assertEqual(at.version_from_tag("AutoTyper v1.2.3"), "1.2.3")

    def test_rejects_anything_unparsable(self):
        for junk in ("latest", "", None, "nightly", 42):
            self.assertIsNone(at.version_from_tag(junk), junk)


class UpdateCheckerFetchTests(unittest.TestCase):
    def setUp(self):
        self.checker = at.UpdateChecker(source_url="http://example.invalid/auto_typer.py",
                                        releases_url="http://example.invalid/releases/latest")

    def test_fetches_release_with_assets(self):
        with mock.patch.object(at.urllib.request, "urlopen",
                               return_value=FakeResponse(release_payload("4.5.6"))):
            release = self.checker.fetch_latest_release()
        self.assertEqual(release.version, "4.5.6")
        self.assertIsNotNone(release.exe_asset)

    def test_release_api_failure_falls_back_to_published_source(self):
        calls = []

        def fake_urlopen(request, timeout=None):
            calls.append(request.full_url)
            if "releases" in request.full_url:
                raise urllib.error.HTTPError(request.full_url, 404, "Not Found", None, None)
            return FakeResponse(b'APP_VERSION = "4.5.7"\n')

        with mock.patch.object(at.urllib.request, "urlopen", side_effect=fake_urlopen):
            release = self.checker.fetch_latest_release()
        self.assertEqual(release.version, "4.5.7")
        self.assertIsNone(release.exe_asset)      # unknown without the API
        self.assertEqual(len(calls), 2)

    def test_both_sources_down_is_silent(self):
        with mock.patch.object(at.urllib.request, "urlopen", side_effect=OSError("offline")):
            self.assertIsNone(self.checker.fetch_latest_release())
            self.assertIsNone(self.checker.fetch_latest_version())

    def test_http_error_is_silent(self):
        error = urllib.error.HTTPError("url", 500, "Server Error", None, None)
        with mock.patch.object(at.urllib.request, "urlopen", side_effect=error):
            self.assertIsNone(self.checker.fetch_latest_release())

    def test_non_200_is_silent(self):
        with mock.patch.object(at.urllib.request, "urlopen",
                               return_value=FakeResponse(release_payload("9.9.9"), status=404)):
            self.assertIsNone(self.checker.fetch_latest_release())

    def test_payload_without_version_is_silent(self):
        with mock.patch.object(at.urllib.request, "urlopen",
                               return_value=FakeResponse(b'print("no version here")')):
            self.assertIsNone(self.checker.fetch_latest_release())

    def test_user_agent_identifies_the_app(self):
        seen = {}

        def fake_urlopen(request, timeout=None):
            seen["ua"] = request.get_header("User-agent")
            return FakeResponse(release_payload("1.0.1"))

        with mock.patch.object(at.urllib.request, "urlopen", side_effect=fake_urlopen):
            self.checker.fetch_latest_release()
        self.assertIn("AutoTyper", seen["ua"])


# ---------------------------------------------------------------------------
# What a downloaded release may do on this machine
# ---------------------------------------------------------------------------
class PlanUpdateTests(unittest.TestCase):
    def setUp(self):
        self.asset = at.UpdateAsset(at.EXE_ASSET_NAME, "https://example.invalid/AutoTyper.exe", 100)

    def test_packaged_build_stages_then_replaces_itself(self):
        plan = at.plan_update(frozen=True, asset=self.asset, target=Path("/opt/AutoTyper.exe"),
                              staging_dir=Path("/tmp/stage"), version="1.2.0")
        self.assertEqual(plan.kind, "self_update")
        self.assertEqual(plan.install_target, Path("/opt/AutoTyper.exe"))
        # Never downloaded straight onto the running program: Windows locks it.
        self.assertNotEqual(plan.destination, plan.install_target)
        self.assertEqual(plan.destination, Path("/tmp/stage") / at.EXE_ASSET_NAME)

    def test_staging_defaults_to_the_temp_folder(self):
        plan = at.plan_update(frozen=True, asset=self.asset, target=Path("/opt/AutoTyper.exe"))
        self.assertTrue(str(plan.destination).startswith(tempfile.gettempdir()))

    def test_staged_name_is_sanitised(self):
        asset = at.UpdateAsset("../../AutoTyper.exe", "u")
        plan = at.plan_update(frozen=True, asset=asset, target=Path("/opt/AutoTyper.exe"),
                              staging_dir=Path("/tmp/stage"))
        self.assertEqual(plan.destination, Path("/tmp/stage") / "AutoTyper.exe")

    def test_source_run_saves_the_exe_for_the_user(self):
        plan = at.plan_update(frozen=False, asset=self.asset, fallback_dir=Path("/tmp/dl"),
                              version="1.2.0")
        self.assertEqual(plan.kind, "download")
        self.assertEqual(plan.destination, Path("/tmp/dl") / at.EXE_ASSET_NAME)

    def test_missing_asset_falls_back_to_the_release_page(self):
        plan = at.plan_update(frozen=True, asset=None, target=Path("/opt/AutoTyper.exe"))
        self.assertEqual(plan.kind, "open_page")
        self.assertTrue(plan.reason)

    def test_frozen_without_a_target_is_not_a_self_update(self):
        plan = at.plan_update(frozen=True, asset=self.asset, target=None, fallback_dir=Path("/tmp/dl"))
        self.assertEqual(plan.kind, "download")

    def test_asset_names_are_sanitised(self):
        hostile = at.UpdateAsset("../../evil name.exe", "u")
        plan = at.plan_update(frozen=False, asset=hostile, fallback_dir=Path("/tmp/dl"))
        self.assertEqual(plan.destination.parent, Path("/tmp/dl"))
        self.assertNotIn("..", plan.destination.name)
        self.assertNotIn(" ", plan.destination.name)


class SanitiseFilenameTests(unittest.TestCase):
    def test_keeps_ordinary_names(self):
        self.assertEqual(at.sanitise_asset_filename("AutoTyper.exe"), "AutoTyper.exe")

    def test_strips_paths_and_odd_characters(self):
        self.assertEqual(at.sanitise_asset_filename("a/b\\c:d e.exe"), "c_d_e.exe")

    def test_appends_extension_and_handles_blank(self):
        self.assertEqual(at.sanitise_asset_filename("build"), "build.exe")
        self.assertEqual(at.sanitise_asset_filename(""), at.EXE_ASSET_NAME)
        self.assertEqual(at.sanitise_asset_filename("///"), at.EXE_ASSET_NAME)


class ExecutableDetectionTests(unittest.TestCase):
    def test_accepts_mz_header(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "AutoTyper.exe"
            path.write_bytes(make_exe())
            self.assertTrue(at.looks_like_windows_executable(path))

    def test_rejects_html_and_empty_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            html = Path(tmp) / "page.exe"
            html.write_bytes(b"<!DOCTYPE html><html>404</html>")
            self.assertFalse(at.looks_like_windows_executable(html))
            self.assertFalse(at.looks_like_windows_executable(Path(tmp) / "missing.exe"))
            empty = Path(tmp) / "empty.exe"
            empty.write_bytes(b"")
            self.assertFalse(at.looks_like_windows_executable(empty))

    def test_running_from_source_is_not_frozen(self):
        self.assertFalse(at.is_frozen())
        self.assertIsNone(at.running_executable())


# ---------------------------------------------------------------------------
# Restarting with a clean environment
#
# A onefile build describes its own unpacked files in the environment
# (_PYI_APPLICATION_HOME_DIR and friends). Handing those to a freshly started
# build makes it load the Python DLL out of a temporary folder that has just
# been deleted, so the relaunch after an update died with "Error loading
# Python DLL" while launching the very same file by hand worked. Everything
# that restarts a build must scrub them.
# ---------------------------------------------------------------------------
class RestartEnvironmentTests(unittest.TestCase):
    def test_drops_every_pyinstaller_runtime_variable(self):
        dirty = {name: "stale" for name in at.PYINSTALLER_RUNTIME_ENV_VARS}
        self.assertEqual(at.restart_environment(dirty), {})

    def test_matches_windows_case_insensitively(self):
        dirty = {"_meipass2": "x", "_pyi_archive_file": "y", "_PYI_APPLICATION_HOME_DIR": "z"}
        self.assertEqual(at.restart_environment(dirty), {})

    def test_keeps_the_environment_the_restart_actually_needs(self):
        dirty = {
            "PATH": r"C:\Windows\System32",
            "TEMP": r"C:\Users\me\AppData\Local\Temp",
            "USERPROFILE": r"C:\Users\me",
            "_PYI_APPLICATION_HOME_DIR": r"C:\Users\me\AppData\Local\Temp\_MEI1234",
        }
        clean = at.restart_environment(dirty)
        self.assertEqual(clean, {"PATH": dirty["PATH"], "TEMP": dirty["TEMP"],
                                 "USERPROFILE": dirty["USERPROFILE"]})
        self.assertNotIn("_PYI_APPLICATION_HOME_DIR", clean)

    def test_defaults_to_the_real_environment_without_mutating_it(self):
        with mock.patch.dict(os.environ, {"_PYI_ARCHIVE_FILE": "here.exe"}, clear=False):
            clean = at.restart_environment()
            self.assertNotIn("_PYI_ARCHIVE_FILE", clean)
            self.assertIn("_PYI_ARCHIVE_FILE", os.environ)   # still ours, just not copied

    def test_scrub_removes_from_this_process_and_reports_what_went(self):
        target = {"PATH": "/usr/bin", "_PYI_ARCHIVE_FILE": "a", "_MEIPASS2": "b"}
        removed = at.scrub_pyinstaller_runtime_environment(target)
        self.assertEqual(sorted(removed), ["_MEIPASS2", "_PYI_ARCHIVE_FILE"])
        self.assertEqual(target, {"PATH": "/usr/bin"})

    def test_scrub_is_happy_when_there_is_nothing_to_remove(self):
        self.assertEqual(at.scrub_pyinstaller_runtime_environment({}), [])

    def test_scrub_on_the_real_environment_leaves_it_usable(self):
        with mock.patch.dict(os.environ, {"_PYI_PARENT_PROCESS_LEVEL": "0"}, clear=False):
            at.scrub_pyinstaller_runtime_environment()
            self.assertNotIn("_PYI_PARENT_PROCESS_LEVEL", os.environ)
            self.assertTrue(at.restart_environment())


# ---------------------------------------------------------------------------
# Downloading
# ---------------------------------------------------------------------------
class DownloadFileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.destination = self.dir / "AutoTyper.exe"

    def tearDown(self):
        self.tmp.cleanup()

    def test_downloads_and_reports_progress(self):
        seen = []
        with mock.patch.object(at.urllib.request, "urlopen",
                               return_value=FakeResponse(make_exe(200000),
                                                         headers={"Content-Length": "200000"})):
            path = at.download_file("https://example.invalid/AutoTyper.exe", self.destination,
                                    progress=lambda done, total: seen.append((done, total)))
        self.assertEqual(path, self.destination)
        self.assertTrue(at.looks_like_windows_executable(self.destination))
        self.assertEqual(seen[-1], (200000, 200000))
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), ["AutoTyper.exe"])

    def test_creates_missing_directories(self):
        target = self.dir / "nested" / "deeper" / "AutoTyper.exe"
        with mock.patch.object(at.urllib.request, "urlopen",
                               return_value=FakeResponse(make_exe())):
            at.download_file("https://example.invalid/AutoTyper.exe", target)
        self.assertTrue(target.is_file())

    def test_html_error_page_is_rejected_and_nothing_is_left_behind(self):
        with mock.patch.object(at.urllib.request, "urlopen",
                               return_value=FakeResponse(b"<html>not found</html>")):
            with self.assertRaises(at.DownloadError):
                at.download_file("https://example.invalid/AutoTyper.exe", self.destination)
        self.assertFalse(self.destination.exists())
        self.assertEqual(list(self.dir.iterdir()), [])

    def test_empty_download_is_rejected(self):
        with mock.patch.object(at.urllib.request, "urlopen", return_value=FakeResponse(b"")):
            with self.assertRaises(at.DownloadError):
                at.download_file("https://example.invalid/AutoTyper.exe", self.destination)

    def test_http_error_status_is_rejected(self):
        with mock.patch.object(at.urllib.request, "urlopen",
                               return_value=FakeResponse(make_exe(), status=503)):
            with self.assertRaises(at.DownloadError):
                at.download_file("https://example.invalid/AutoTyper.exe", self.destination)

    def test_network_error_is_reported(self):
        with mock.patch.object(at.urllib.request, "urlopen", side_effect=OSError("offline")):
            with self.assertRaises(at.DownloadError):
                at.download_file("https://example.invalid/AutoTyper.exe", self.destination)

    def test_existing_build_survives_a_failed_download(self):
        self.destination.write_bytes(make_exe(16))
        with mock.patch.object(at.urllib.request, "urlopen",
                               return_value=FakeResponse(b"<html>nope</html>")):
            with self.assertRaises(at.DownloadError):
                at.download_file("https://example.invalid/AutoTyper.exe", self.destination)
        self.assertEqual(self.destination.read_bytes(), make_exe(16))

    def test_broken_progress_callback_does_not_break_the_download(self):
        def explode(done, total):
            raise RuntimeError("boom")

        with mock.patch.object(at.urllib.request, "urlopen",
                               return_value=FakeResponse(make_exe())):
            path = at.download_file("https://example.invalid/AutoTyper.exe", self.destination,
                                    progress=explode)
        self.assertTrue(path.is_file())


# ---------------------------------------------------------------------------
# Installing: the swap script
# ---------------------------------------------------------------------------
class WindowsSwapScriptTests(unittest.TestCase):
    def setUp(self):
        self.script = at.build_windows_swap_script(r"C:\Temp\AutoTyper-new.exe",
                                                   r"C:\Apps\AutoTyper.exe")

    def test_retries_the_copy_until_the_running_build_exits(self):
        self.assertIn(":waitloop", self.script)
        self.assertIn("goto waitloop", self.script)
        self.assertIn('copy /Y "%NEW%" "%TARGET%"', self.script)

    def test_keeps_a_backup_and_restarts_the_app(self):
        self.assertIn('copy /Y "%TARGET%" "%TARGET%.old"', self.script)
        self.assertIn('start "" "%TARGET%"', self.script)

    def test_cleans_up_after_itself(self):
        self.assertIn('del "%NEW%"', self.script)
        self.assertIn('del "%~f0"', self.script)

    def test_gives_up_instead_of_looping_forever(self):
        self.assertIn("set /a COUNT+=1", self.script)
        self.assertIn("if %COUNT% GEQ %TRIES% goto giveup", self.script)

    def test_is_a_batch_file_with_crlf_line_endings(self):
        self.assertTrue(self.script.startswith("@echo off\r\n"))
        self.assertTrue(all(not line.endswith("\n") or line.endswith("\r\n")
                            for line in self.script.split("\n")))

    def test_wait_budget_is_configurable(self):
        script = at.build_windows_swap_script("a.exe", "b.exe", wait_seconds=7)
        self.assertIn('set "TRIES=7"', script)

    def test_backup_is_taken_before_the_new_build_is_copied_in(self):
        # After the swap the target *is* the new build, so a later copy would
        # back up the wrong file and leave nothing to roll back to.
        backup = self.script.index('copy /Y "%TARGET%" "%TARGET%.old"')
        swap = self.script.index('copy /Y "%NEW%" "%TARGET%"')
        self.assertLess(backup, swap)

    def test_restart_clears_the_onefile_environment(self):
        for name in at.PYINSTALLER_RUNTIME_ENV_VARS:
            self.assertIn(f'set "{name}=', self.script,
                          f"{name} must not be handed to the new build")

    def test_restart_also_asks_the_bootloader_for_a_reset(self):
        self.assertIn('set "PYINSTALLER_RESET_ENVIRONMENT=1"', self.script)

    def test_an_aborted_swap_still_brings_the_app_back(self):
        give_up = self.script.split(":giveup", 1)[1]
        self.assertIn('start "" "%TARGET%"', give_up)


class PosixSwapScriptTests(unittest.TestCase):
    def test_waits_for_the_pid_then_swaps_and_relaunches(self):
        script = at.build_posix_swap_script("/tmp/new", "/opt/AutoTyper", 4242)
        self.assertIn('while kill -0 "$PID" 2>/dev/null; do', script)
        self.assertIn('mv -f "$NEW" "$TARGET"', script)
        self.assertIn('nohup "$TARGET"', script)
        self.assertIn("chmod +x", script)
        self.assertIn("PID=4242", script)

    def test_relaunch_clears_the_onefile_environment(self):
        script = at.build_posix_swap_script("/tmp/new", "/opt/AutoTyper", 1)
        for name in at.PYINSTALLER_RUNTIME_ENV_VARS:
            self.assertIn(f"unset {name}\n", script)
        self.assertIn("export PYINSTALLER_RESET_ENVIRONMENT=1", script)

    def test_platform_dispatch(self):
        windows = at.build_swap_script("n", "t", 1, windows=True)
        posix = at.build_swap_script("n", "t", 1, windows=False)
        self.assertTrue(windows.startswith("@echo off"))
        self.assertTrue(posix.startswith("#!/bin/sh"))


class InstallUpdateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.new_exe = self.dir / "downloaded.exe"
        self.new_exe.write_bytes(make_exe())
        self.target = self.dir / "AutoTyper.exe"
        self.target.write_bytes(make_exe(16))

    def tearDown(self):
        self.tmp.cleanup()

    def test_writes_and_launches_a_swap_script(self):
        with mock.patch.object(at, "launch_swap_script") as launch:
            script = at.install_update_and_restart(self.new_exe, self.target, windows=True,
                                                   temp_dir=self.dir / "stage", pid=1234)
        self.assertTrue(script.is_file())
        self.assertEqual(script.suffix, ".bat")
        self.assertIn(str(self.new_exe), script.read_text(encoding="utf-8"))
        launch.assert_called_once()

    def test_posix_script_is_executable(self):
        with mock.patch.object(at, "launch_swap_script"):     # never spawn a real swapper here
            script = at.install_update_and_restart(self.new_exe, self.target, windows=False,
                                                   temp_dir=self.dir / "stage", pid=99)
        self.assertEqual(script.suffix, ".sh")
        if os.name != "nt":
            self.assertTrue(script.stat().st_mode & 0o111)

    def test_refuses_when_the_download_vanished(self):
        with self.assertRaises(at.DownloadError):
            at.install_update_and_restart(self.dir / "missing.exe", self.target, windows=True,
                                          temp_dir=self.dir)

    def test_refuses_without_a_packaged_target(self):
        with self.assertRaises(at.DownloadError):
            at.install_update_and_restart(self.new_exe, None, windows=True, temp_dir=self.dir)

    def test_launch_uses_a_detached_process_on_windows(self):
        with mock.patch.object(at.subprocess, "Popen") as popen:
            at.launch_swap_script(self.dir / "s.bat", windows=True)
        args, kwargs = popen.call_args
        self.assertEqual(args[0][0], "cmd")
        self.assertIn("creationflags", kwargs)   # detached: the swap outlives this process

    def test_launch_uses_a_new_session_elsewhere(self):
        with mock.patch.object(at.subprocess, "Popen") as popen:
            at.launch_swap_script(self.dir / "s.sh", windows=False)
        _, kwargs = popen.call_args
        self.assertTrue(kwargs.get("start_new_session"))

    def test_launch_hands_the_script_a_scrubbed_environment(self):
        """The swap script must not describe *our* unpacked files: it starts
        the next build, and inheriting them breaks that build's start-up."""
        stale = {name: "stale" for name in at.PYINSTALLER_RUNTIME_ENV_VARS}
        for windows in (True, False):
            with mock.patch.object(at.subprocess, "Popen") as popen, \
                    mock.patch.dict(os.environ, stale, clear=False):
                at.launch_swap_script(self.dir / ("s.bat" if windows else "s.sh"),
                                      windows=windows)
            _, kwargs = popen.call_args
            env = kwargs.get("env")
            self.assertIsInstance(env, dict)
            for name in at.PYINSTALLER_RUNTIME_ENV_VARS:
                self.assertNotIn(name, env)


# ---------------------------------------------------------------------------
# GUI wiring (driven through a stub object: this suite runs with no display)
# ---------------------------------------------------------------------------
class _StubButton:
    def __init__(self):
        self.kw = {}

    def config(self, **kwargs):
        self.kw.update(kwargs)

    configure = config

    def grid(self, **kwargs):
        self.grid_kw = kwargs

    pack = grid

    def winfo_exists(self):
        return 1


class _StubApp:
    """Just enough object to call the real window methods on.

    Since v1.1.0 the header holds only the Settings button, so the download
    affordance the app toggles is the settings window's button (stubbed here
    as if that window were open).
    """

    def __init__(self):
        self.posts = []
        self.colors = {"foreground": "#111", "accent": "#00F", "muted": "#888"}
        self.status_label = _StubButton()
        self.progress = {"value": 0, "maximum": 0}
        self._download_exe_button = _StubButton()
        self._update_hint = _StubButton()
        self._available_version = None
        self.quit_calls = 0
        self.installed = []
        self.opened_pages = 0
        # Bind the real settings-button helpers so announcement/download
        # results exercise the genuine code paths against the stubs above.
        self._refresh_update_controls = types.MethodType(
            at.AutoTyperApp._refresh_update_controls, self)
        self._set_download_button_state = types.MethodType(
            at.AutoTyperApp._set_download_button_state, self)

    def _post(self, *msg):
        self.posts.append(msg)

    def update(self):
        pass

    def _quitting(self):
        self.quit_calls += 1

    def _close_settings(self):
        pass

    def after_cancel(self, _id):
        pass

    def quit(self):
        pass

    def destroy(self):
        pass

    def _open_update_page(self):
        self.opened_pages += 1


def _bind(app, name):
    """Attach one real AutoTyperApp method to the stub instance."""
    return types.MethodType(getattr(at.AutoTyperApp, name), app)


class GuiHookTests(unittest.TestCase):
    def test_app_class_exposes_the_update_hooks(self):
        for name in ("_start_update_check", "_update_check_worker", "_manual_update_check",
                     "_on_update_available", "_on_manual_update_result", "_open_update_page",
                     "_start_exe_download", "_exe_download_worker", "_on_download_result",
                     "_install_downloaded_update", "_quit_for_restart"):
            self.assertTrue(hasattr(at.AutoTyperApp, name), name)

    def test_open_update_page_points_at_the_releases(self):
        app = _StubApp()
        with mock.patch.object(at.webbrowser, "open") as opened:
            _bind(app, "_open_update_page")()
        opened.assert_called_once_with(at.RELEASES_PAGE_URL)


class GuiUpdateAnnouncementTests(unittest.TestCase):
    def setUp(self):
        self.mod, self.messagebox = _load_module_with_tk_stub()
        self.messagebox.calls.clear()
        self.messagebox.askyesno = lambda *args, **kwargs: False
        self.app = _StubApp()

    def _release(self, version="1.3.0", with_exe=True):
        assets = (at.UpdateAsset(at.EXE_ASSET_NAME, "https://example.invalid/AutoTyper.exe"),) \
            if with_exe else ()
        return self.mod.ReleaseInfo(version=version, assets=assets)

    def test_announcement_names_the_version_and_offers_the_exe(self):
        self.messagebox.askyesno = lambda *args, **kwargs: False
        types.MethodType(self.mod.AutoTyperApp._on_update_available, self.app)(self._release())
        self.assertEqual(self.app.status_label.kw["text"],
                         "Status: Update available — v1.3.0 (you have v%s)" % at.APP_VERSION)
        # The offer now lives in Settings: the download button is relabelled
        # with the version it will fetch and the hint names it too.
        self.assertEqual(self.app._available_version, "1.3.0")
        self.assertIn("1.3.0", self.app._download_exe_button.kw["text"])
        self.assertIn("exe", self.app._download_exe_button.kw["text"].lower())
        self.assertIn("1.3.0", self.app._update_hint.kw["text"])

    def test_declining_downloads_nothing(self):
        started = []
        self.app._start_exe_download = lambda: started.append(True)
        self.messagebox.askyesno = lambda *args, **kwargs: False
        types.MethodType(self.mod.AutoTyperApp._on_update_available, self.app)(self._release())
        self.assertEqual(started, [])

    def test_accepting_starts_the_exe_download(self):
        started = []
        self.app._start_exe_download = lambda: started.append(True)
        self.messagebox.askyesno = lambda *args, **kwargs: True
        types.MethodType(self.mod.AutoTyperApp._on_update_available, self.app)(self._release())
        self.assertEqual(started, [True])

    def test_release_without_an_exe_opens_the_release_page_instead(self):
        self.messagebox.askyesno = lambda *args, **kwargs: True
        types.MethodType(self.mod.AutoTyperApp._on_update_available, self.app)(
            self._release(with_exe=False))
        self.assertEqual(self.app.opened_pages, 1)


class GuiDownloadWorkerTests(unittest.TestCase):
    def setUp(self):
        self.mod, self.messagebox = _load_module_with_tk_stub()
        self.messagebox.calls.clear()
        self.app = _StubApp()
        self.worker = types.MethodType(self.mod.AutoTyperApp._exe_download_worker, self.app)

    def _release(self, version="1.3.0"):
        return self.mod.ReleaseInfo(
            version=version,
            assets=(self.mod.UpdateAsset(self.mod.EXE_ASSET_NAME, "https://example.invalid/f.exe"),),
        )

    def test_packaged_build_reports_self_update_with_the_downloaded_path(self):
        with mock.patch.object(self.mod, "UpdateChecker") as checker, \
             mock.patch.object(self.mod, "download_file", return_value=Path("/tmp/AutoTyper.exe")) as dl, \
             mock.patch.object(self.mod, "is_frozen", return_value=True), \
             mock.patch.object(self.mod, "running_executable", return_value=Path("/opt/AutoTyper.exe")), \
             mock.patch.object(self.mod, "staging_path",
                              return_value=Path(tempfile.gettempdir()) / "AutoTyper-update" / "AutoTyper.exe"):
            checker.return_value.fetch_latest_release.return_value = self._release()
            self.worker()
        # The reported path is whatever the (mocked) download produced...
        self.assertEqual(self.app.posts[-1], ("download_result", "self_update",
                                              (str(Path("/tmp/AutoTyper.exe")), "1.3.0")))
        # ...and the file was staged in the temp folder, never written over the
        # running executable (Windows keeps that locked).
        staged = dl.call_args[0][1]
        self.assertEqual(staged, Path(tempfile.gettempdir()) / "AutoTyper-update" / "AutoTyper.exe")
        self.assertIn(tempfile.gettempdir(), str(staged))

    def test_source_run_saves_into_the_download_folder(self):
        with mock.patch.object(self.mod, "UpdateChecker") as checker, \
             mock.patch.object(self.mod, "download_file", return_value=Path("/home/u/Downloads/AutoTyper.exe")), \
             mock.patch.object(self.mod, "is_frozen", return_value=False), \
             mock.patch.object(self.mod, "default_download_dir", return_value=Path("/home/u/Downloads")):
            checker.return_value.fetch_latest_release.return_value = self._release()
            self.worker()
        kind, payload = self.app.posts[-1][1], self.app.posts[-1][2]
        self.assertEqual(kind, "download")
        self.assertEqual(payload, (str(Path("/home/u/Downloads/AutoTyper.exe")), "1.3.0"))

    def test_release_without_exe_asks_for_the_page(self):
        with mock.patch.object(self.mod, "UpdateChecker") as checker:
            checker.return_value.fetch_latest_release.return_value = self.mod.ReleaseInfo(version="1.3.0")
            self.worker()
        self.assertEqual(self.app.posts[-1][1], "open_page")

    def test_download_failure_is_reported_not_raised(self):
        with mock.patch.object(self.mod, "UpdateChecker") as checker, \
             mock.patch.object(self.mod, "download_file",
                               side_effect=self.mod.DownloadError("network died")):
            checker.return_value.fetch_latest_release.return_value = self._release()
            self.worker()
        self.assertEqual(self.app.posts[-1], ("download_result", "failed", "network died"))

    def test_unexpected_error_is_reported_not_raised(self):
        with mock.patch.object(self.mod, "UpdateChecker", side_effect=RuntimeError("boom")):
            self.worker()
        self.assertEqual(self.app.posts[-1][1], "failed")


class GuiDownloadResultTests(unittest.TestCase):
    def setUp(self):
        self.mod, self.messagebox = _load_module_with_tk_stub()
        self.messagebox.calls.clear()
        self.app = _StubApp()
        self.result = types.MethodType(self.mod.AutoTyperApp._on_download_result, self.app)

    def test_failure_shows_an_error_and_reenables_the_button(self):
        self.result("failed", "network died")
        self.assertEqual(self.messagebox.calls[-1][0], "showerror")
        self.assertEqual(self.app._download_exe_button.kw["state"], "normal")

    def test_button_state_survives_a_closed_settings_window(self):
        self.app._download_exe_button = None
        self.result("failed", "network died")          # must not explode
        self.assertEqual(self.messagebox.calls[-1][0], "showerror")

    def test_self_update_offers_to_install(self):
        installed = []
        self.app._install_downloaded_update = installed.append
        self.messagebox.askyesno = lambda *args, **kwargs: True
        self.result("self_update", ("C:/Temp/AutoTyper.exe", "1.3.0"))
        self.assertEqual(installed, ["C:/Temp/AutoTyper.exe"])

    def test_declining_the_install_keeps_the_current_build(self):
        installed = []
        self.app._install_downloaded_update = installed.append
        self.messagebox.askyesno = lambda *args, **kwargs: False
        self.result("self_update", ("C:/Temp/AutoTyper.exe", "1.3.0"))
        self.assertEqual(installed, [])

    def test_source_run_reports_the_saved_path_and_reveals_it(self):
        opened = []
        with mock.patch.object(self.mod, "open_in_file_manager", side_effect=lambda p: opened.append(p)):
            self.result("download", ("/home/u/Downloads/AutoTyper.exe", "1.3.0"))
        self.assertEqual(self.messagebox.calls[-1][0], "showinfo")
        self.assertIn("AutoTyper.exe", self.messagebox.calls[-1][2])
        self.assertEqual(opened, ["/home/u/Downloads/AutoTyper.exe"])

    def test_no_exe_published_opens_the_release_page(self):
        plan = self.mod.UpdatePlan(kind="open_page", reason="no .exe attached yet")
        self.result("open_page", plan)
        self.assertEqual(self.app.opened_pages, 1)

    def test_installing_spawns_the_swap_and_quits(self):
        install = types.MethodType(self.mod.AutoTyperApp._install_downloaded_update, self.app)
        self.app._quit_for_restart = lambda: setattr(self.app, "quit_calls", self.app.quit_calls + 1)
        with mock.patch.object(self.mod, "install_update_and_restart",
                               return_value=Path("/tmp/AutoTyper-update.bat")) as installer, \
             mock.patch.object(self.mod, "running_executable", return_value=Path("/opt/AutoTyper.exe")):
            install("C:/Temp/AutoTyper.exe")
        installer.assert_called_once_with("C:/Temp/AutoTyper.exe", Path("/opt/AutoTyper.exe"))
        self.assertEqual(self.app.quit_calls, 1)
        self.assertEqual(self.messagebox.calls[-1][0], "showinfo")

    def test_install_failure_is_surfaced_and_does_not_quit(self):
        install = types.MethodType(self.mod.AutoTyperApp._install_downloaded_update, self.app)
        self.app._quit_for_restart = lambda: setattr(self.app, "quit_calls", self.app.quit_calls + 1)
        with mock.patch.object(self.mod, "install_update_and_restart",
                               side_effect=self.mod.DownloadError("no permission")), \
             mock.patch.object(self.mod, "running_executable", return_value=Path("/opt/AutoTyper.exe")):
            install("C:/Temp/AutoTyper.exe")
        self.assertEqual(self.app.quit_calls, 0)
        self.assertEqual(self.messagebox.calls[-1][0], "showerror")


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------
class CliTests(unittest.TestCase):
    def _run(self, argv, release):
        with mock.patch.object(at.UpdateChecker, "fetch_latest_release", return_value=release), \
             mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            code = at.main(argv)
        return code, out.getvalue()

    def _release(self, version, with_exe=True):
        assets = (at.UpdateAsset(at.EXE_ASSET_NAME, "https://example.invalid/AutoTyper.exe"),) \
            if with_exe else ()
        return at.ReleaseInfo(version=version, assets=assets)

    def test_reports_available_update_with_the_exe_url(self):
        code, out = self._run(["--check-update"], self._release("9.9.9"))
        self.assertEqual(code, 0)
        self.assertIn("Update available", out)
        self.assertIn("https://example.invalid/AutoTyper.exe", out)

    def test_available_update_without_exe_points_at_the_release_page(self):
        code, out = self._run(["--check-update"], self._release("9.9.9", with_exe=False))
        self.assertEqual(code, 0)
        self.assertIn(at.RELEASES_PAGE_URL, out)

    def test_reports_up_to_date(self):
        code, out = self._run(["--check-update"], self._release(at.APP_VERSION))
        self.assertEqual(code, 0)
        self.assertIn("up to date", out)

    def test_unreachable_is_graceful(self):
        code, out = self._run(["--check-update"], None)
        self.assertEqual(code, 1)
        self.assertIn("Could not check for updates", out)

    def test_download_exe_saves_the_executable(self):
        with tempfile.TemporaryDirectory() as tmp:
            release = self._release("9.9.9")
            with mock.patch.object(at.UpdateChecker, "fetch_latest_release", return_value=release), \
                 mock.patch.object(at.urllib.request, "urlopen",
                                   return_value=FakeResponse(make_exe())), \
                 mock.patch("sys.stdout", new_callable=io.StringIO) as out:
                code = at.main(["--download-exe", tmp])
            self.assertEqual(code, 0)
            self.assertTrue((Path(tmp) / at.EXE_ASSET_NAME).is_file())
            self.assertIn(at.EXE_ASSET_NAME, out.getvalue())

    def test_download_exe_reports_when_the_release_has_no_exe(self):
        with tempfile.TemporaryDirectory() as tmp:
            err = io.StringIO()
            with mock.patch.object(at.UpdateChecker, "fetch_latest_release",
                                   return_value=self._release("9.9.9", with_exe=False)), \
                 mock.patch("sys.stdout", new_callable=io.StringIO), \
                 mock.patch("sys.stderr", new=err):
                code = at.main(["--download-exe", tmp])
            self.assertEqual(code, 1)
            self.assertIn("no .exe", err.getvalue())

    def test_self_update_from_source_only_downloads(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(at.UpdateChecker, "fetch_latest_release",
                                   return_value=self._release("9.9.9")), \
                 mock.patch.object(at, "default_download_dir", return_value=Path(tmp)), \
                 mock.patch.object(at.urllib.request, "urlopen", return_value=FakeResponse(make_exe())), \
                 mock.patch.object(at, "install_update_and_restart") as installer, \
                 mock.patch("sys.stdout", new_callable=io.StringIO) as out:
                code = at.main(["--self-update"])
            self.assertEqual(code, 0)
            installer.assert_not_called()
            self.assertIn("run the .exe", out.getvalue())


# ---------------------------------------------------------------------------
# Helpers used by the GUI at large
# ---------------------------------------------------------------------------
class DefaultDownloadDirTests(unittest.TestCase):
    def test_prefers_an_existing_downloads_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / "Downloads").mkdir()
            with mock.patch.object(at.Path, "home", return_value=home):
                self.assertEqual(at.default_download_dir(), home / "Downloads")

    def test_falls_back_to_the_home_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(at.Path, "home", return_value=Path(tmp)):
                self.assertEqual(at.default_download_dir(), Path(tmp))


class SettingsMigrationTests(unittest.TestCase):
    def test_legacy_settings_file_is_still_honoured(self):
        mod, _ = _load_module_with_tk_stub()
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / ".pascal_typing_v2_settings.json").write_text(
                json.dumps({"palette": "Nord Winter", "topmost": False}), encoding="utf-8")
            with mock.patch.object(mod.Path, "home", return_value=home):
                self.assertEqual(mod.AutoTyperApp._ui_settings_path(), home / ".autotyper_settings.json")
                loaded = mod.AutoTyperApp._load_ui_settings(object.__new__(mod.AutoTyperApp))
        self.assertEqual(loaded["palette"], "Nord Winter")


if __name__ == "__main__":
    unittest.main()
