"""uengine/transfer/tree.py - Phase 1b: what a tree transfer contains, decided explicitly and reported.

plan_tree(src, dst) walks the source WITHOUT following any symbolic link and classifies every entry:
  files       regular files to copy (hidden / dot files included - they can be data, e.g. volume markers)
  empty_dirs  folders with no copyable content, recreated at the destination
  skipped     never copied, each with a reason (the job report lists them; a move leaves them at the source):
              symlink            file or folder link (never followed - it could point at originals or outside the tree)
              finder_metadata    .DS_Store, AppleDouble ._* files, .Spotlight-V100, .Trashes, .fseventsd
              transfer_artifact  *.part, *.part-<job>, *.replaced-<job>, *.incoming-<job> (left by earlier transfers)
              special_file       FIFO, socket, device
              unreadable         permission denied while listing
list_stale_artifacts(root) reports leftover transfer artifacts with the job that left them; it never deletes anything.
"""
import os
import re
import stat
from dataclasses import dataclass, field
from typing import Dict, List, Optional

FINDER_METADATA = {".DS_Store", ".Spotlight-V100", ".Trashes", ".fseventsd", ".TemporaryItems", ".DocumentRevisions-V100"}
ARTIFACT_RE = re.compile(r"^(?P<name>.+)\.(?P<kind>part|replaced|incoming)-(?P<job>[A-Za-z0-9][A-Za-z0-9_-]{0,63})$")


@dataclass
class TreeEntry:
    rel: str
    src: str
    dst: str
    size: int


@dataclass
class TreePlan:
    src_root: str
    dst_root: str
    is_file: bool
    files: List[TreeEntry] = field(default_factory=list)
    empty_dirs: List[str] = field(default_factory=list)
    skipped: List[Dict[str, str]] = field(default_factory=list)

    @property
    def total_bytes(self) -> int:
        return sum(f.size for f in self.files)


def classify_name(name: str) -> Optional[str]:
    """reason a name is never copied, or None"""
    if name in FINDER_METADATA or name.startswith("._"):
        return "finder_metadata"
    if name.endswith(".part") or ARTIFACT_RE.match(name):
        return "transfer_artifact"
    return None


def plan_tree(src: str, dst: str) -> TreePlan:
    """the explicit content of a transfer of src (file or folder) to dst. src itself must not be a symlink."""
    if os.path.islink(src):
        raise ValueError(f"the source {src} is a symbolic link; links are never followed")
    if os.path.isfile(src):
        p = TreePlan(src, dst, True)
        why = classify_name(os.path.basename(src))
        if why:
            p.skipped.append(dict(rel=os.path.basename(src), reason=why))
        else:
            p.files.append(TreeEntry(os.path.basename(src), src, dst, os.lstat(src).st_size))
        return p
    if not os.path.isdir(src):
        raise ValueError(f"the source {src} is not a file or folder")
    plan = TreePlan(src, dst, False)

    def walk(d: str, rel: str) -> bool:
        """returns True if anything copyable was found below d"""
        found = False
        try:
            entries = sorted(os.scandir(d), key=lambda e: e.name)
        except PermissionError:
            plan.skipped.append(dict(rel=rel or ".", reason="unreadable"))
            return True                                    # not "empty": we cannot tell
        for e in entries:
            r = os.path.join(rel, e.name) if rel else e.name
            if e.is_symlink():
                plan.skipped.append(dict(rel=r, reason="symlink", target=os.readlink(e.path)))
                found = True
                continue
            why = classify_name(e.name)
            if why:
                plan.skipped.append(dict(rel=r, reason=why))
                continue
            if e.is_dir(follow_symlinks=False):
                if walk(e.path, r):
                    found = True
                else:
                    plan.empty_dirs.append(r)
                    found = True
            elif e.is_file(follow_symlinks=False):
                plan.files.append(TreeEntry(r, e.path, os.path.join(dst, r), e.stat(follow_symlinks=False).st_size))
                found = True
            else:
                mode = e.stat(follow_symlinks=False).st_mode
                kind = "fifo" if stat.S_ISFIFO(mode) else "socket" if stat.S_ISSOCK(mode) else "device"
                plan.skipped.append(dict(rel=r, reason="special_file", kind=kind))
                found = True
        return found

    if not walk(src, ""):
        plan.empty_dirs.append("")                         # the source folder itself is empty
    return plan


def list_stale_artifacts(root: str) -> List[Dict[str, str]]:
    """transfer artifacts below root (never follows links, never deletes): path, kind, job, target"""
    out = []
    for r, ds, fs in os.walk(root, followlinks=False):
        for n in fs + ds:
            m = ARTIFACT_RE.match(n)
            if m:
                out.append(dict(path=os.path.join(r, n), kind=m.group("kind"), job=m.group("job"),
                                target=os.path.join(r, m.group("name"))))
            elif n.endswith(".part"):
                out.append(dict(path=os.path.join(r, n), kind="legacy_part", job="", target=os.path.join(r, n[:-5])))
    return out
