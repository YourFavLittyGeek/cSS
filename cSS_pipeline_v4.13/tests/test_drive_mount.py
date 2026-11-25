"""2026-11-25: the Pensieve drive plugged in but unmounted (after Eject / a macOS unmount) is found and mounted again.
diskutil is never run: an injected runner answers with real-format plists."""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import _isolation; _isolation.activate()  # Phase 0: test isolation (must stay first)
import os
import plistlib
import sys
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "app"))
import drive_mount as DM                                                     # noqa: E402


def lst(mount_point=None):
    part = dict(DeviceIdentifier="disk4s2", VolumeName="Percival", Size=4000000000000)
    if mount_point: part["MountPoint"] = mount_point
    return plistlib.dumps(dict(AllDisksAndPartitions=[dict(DeviceIdentifier="disk4", Partitions=[
        dict(DeviceIdentifier="disk4s1", VolumeName="EFI"), part])]))


class Runner:
    def __init__(self, listing, mount_rc=0):
        self.listing, self.mount_rc, self.calls = listing, mount_rc, []

    def __call__(self, cmd):
        self.calls.append(cmd)
        if cmd[:2] == ["diskutil", "list"]:
            return types.SimpleNamespace(returncode=0, stdout=self.listing, stderr=b"")
        return types.SimpleNamespace(returncode=self.mount_rc, stdout=b"Volume Percival on disk4s2 mounted\n" if not self.mount_rc else b"",
                                     stderr=b"" if not self.mount_rc else b"Volume on disk4s2 failed to mount\n")


class TestDriveMount(unittest.TestCase):
    def setUp(self):
        DM._CACHE.update(t=0.0, name="", dev=None)

    def test_volume_name_from_the_vault_path(self):
        self.assertEqual(DM.volume_name("/Volumes/Percival/PERCIVAL_VAULT", "/Volumes"), "Percival")
        self.assertEqual(DM.volume_name("/Users/x/PERCIVAL_VAULT", "/Volumes"), "")

    def test_unmounted_partition_is_found_and_mounted(self):
        r = Runner(lst())
        self.assertEqual(DM.find_unmounted("Percival", run=r), "disk4s2")
        ok, msg = DM.mount("disk4s2", run=r)
        self.assertTrue(ok)
        self.assertIn("mounted", msg)
        self.assertEqual(r.calls[-1], ["diskutil", "mount", "disk4s2"])

    def test_mounted_or_absent_drive_is_left_alone(self):
        self.assertIsNone(DM.find_unmounted("Percival", run=Runner(lst("/Volumes/Percival"))))
        self.assertIsNone(DM.find_unmounted("Other", run=Runner(lst())))
        self.assertIsNone(DM.find_unmounted("", run=Runner(lst())))

    def test_mount_failure_and_bad_identifiers(self):
        ok, msg = DM.mount("disk4s2", run=Runner(lst(), mount_rc=1))
        self.assertFalse(ok)
        self.assertIn("failed", msg)
        self.assertFalse(DM.mount("disk4s2; rm -rf /", run=Runner(lst()))[0])

    def test_never_runs_diskutil_under_isolation(self):
        with self.assertRaises(RuntimeError):
            DM._real_run(["diskutil", "list"])
        self.assertIsNone(DM.find_unmounted("Percival"))                          # swallowed -> None, nothing ran


if __name__ == "__main__":
    unittest.main()
