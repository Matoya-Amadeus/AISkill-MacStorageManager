import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import mac_storage_manager as msm  # type: ignore
from mac_storage_manager import CleanupTarget, StorageContext, StorageManager  # type: ignore


def _write(path: Path, text: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


class FakeRunner:
    def which(self, name: str) -> str | None:
        return None

    def run(self, args, *, capture_output=True, text=True, check=False, cwd=None):  # noqa: ANN001
        class Result:
            returncode = 0
            stdout = ""
        return Result()


def _manager(home: Path, **kwargs) -> StorageManager:
    ctx = StorageContext(
        home=home,
        root=kwargs.pop("root", home),
        days_to_keep=kwargs.pop("days_to_keep", 7),
        dry_run=kwargs.pop("dry_run", True),
        apply=kwargs.pop("apply", False),
        yes=kwargs.pop("yes", False),
        include_system=kwargs.pop("include_system", False),
        confirm_targets=frozenset(kwargs.pop("confirm_targets", ())),
        approved_targets=frozenset(kwargs.pop("approved_targets", ())),
        include_hidden_home=kwargs.pop("include_hidden_home", False),
        flutter_search_root=kwargs.pop("flutter_search_root", None),
        app_path=kwargs.pop("app_path", None),
        system_roots=kwargs.pop("system_roots", msm.DEFAULT_SYSTEM_ROOTS),
    )
    return StorageManager(ctx, runner=kwargs.pop("runner", FakeRunner()))


class MacStorageManagerTests(unittest.TestCase):
    def test_hidden_home_scan_does_not_special_case_codex(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="mac-storage-open-source-"))
        home = tmp / "home"
        _write(home / ".codex" / ".tmp" / "a.txt")
        manager = _manager(home, include_hidden_home=True)
        target_ids = {target.target_id for target in manager.discover_targets()}
        self.assertNotIn("home-codex-temp", target_ids)
        self.assertIn("hidden-home:codex", target_ids)

    def test_public_display_path_redacts_private_absolute_paths(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="mac-storage-paths-"))
        home = tmp / "home"
        root = home / "workspace"
        secret = home / "Library" / "Caches" / "pip"
        self.assertEqual(
            msm.public_display_path(secret, home=home, root=root, public_roots=msm.DEFAULT_PUBLIC_ROOTS),
            "~/Library/Caches/pip",
        )
        external = Path("/opt/private-demo/file.txt")
        self.assertEqual(
            msm.public_display_path(external, home=home, root=root, public_roots=msm.DEFAULT_PUBLIC_ROOTS),
            "<external>/file.txt",
        )

    def test_public_note_redacts_sensitive_diagnostics(self) -> None:
        self.assertEqual(msm.public_note("container_bundle_id=com.example.demo"), "container_bundle_id=<redacted>")
        self.assertEqual(msm.public_note("non_owner_path=/Users/demo/.npm/a"), "non_owner_path=<redacted>")
        self.assertEqual(msm.public_note("allocated_bytes=512"), "allocated_bytes=512")

    def test_report_redacts_home_root_paths_and_notes(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="mac-storage-report-"))
        home = tmp / "home"
        root = home / "workspace"
        cache_dir = home / "Library" / "Caches" / "pip"
        _write(cache_dir / "cache.bin", "cache")
        manager = _manager(home, root=root)
        target = CleanupTarget(
            target_id="probe",
            name="Probe",
            category="test",
            kind="purge_tree",
            paths=(cache_dir,),
        )
        scans = manager.scan_targets([target])
        report = manager._make_report(  # type: ignore[attr-defined]
            mode="audit",
            before_scans=scans,
            after_scans=scans,
            plan_items=manager.plan_targets(scans),
            actual_reclaimed_bytes=0,
            before_free_bytes=0,
            after_free_bytes=0,
            notes=["container_bundle_id=com.example.demo", "non_owner_path=/tmp/private"],
        )
        data = report.to_dict()
        self.assertEqual(data["home"], "~")
        self.assertEqual(data["root"], "<root>")
        self.assertEqual(data["top_consumers"][0]["paths"], ["~/Library/Caches/pip"])
        self.assertEqual(data["top_consumers"][0]["notes"], [])
        self.assertEqual(data["notes"], ["container_bundle_id=<redacted>", "non_owner_path=<redacted>"])

    def test_custom_system_roots_are_accepted(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="mac-storage-system-roots-"))
        home = tmp / "home"
        custom_roots = tuple((tmp / f"sys{i}") for i in range(4))
        manager = _manager(home, system_roots=custom_roots)
        self.assertEqual(manager.context.system_roots, custom_roots)

    def test_custom_system_roots_are_public_in_reports(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="mac-storage-public-system-roots-"))
        home = tmp / "home"
        external_root = tmp / "sys0"
        target_path = external_root / "Caches" / "demo"
        _write(target_path / "cache.bin", "cache")
        manager = _manager(home, system_roots=(external_root, tmp / "sys1", tmp / "sys2", tmp / "sys3"))
        target = CleanupTarget(
            target_id="external-probe",
            name="External Probe",
            category="test",
            kind="purge_tree",
            paths=(target_path,),
        )
        scans = manager.scan_targets([target])
        report = manager._make_report(  # type: ignore[attr-defined]
            mode="audit",
            before_scans=scans,
            after_scans=scans,
            plan_items=manager.plan_targets(scans),
            actual_reclaimed_bytes=0,
            before_free_bytes=0,
            after_free_bytes=0,
            notes=[],
        )
        data = report.to_dict()
        self.assertEqual(data["top_consumers"][0]["paths"], [target_path.resolve().as_posix()])


if __name__ == "__main__":
    unittest.main()
