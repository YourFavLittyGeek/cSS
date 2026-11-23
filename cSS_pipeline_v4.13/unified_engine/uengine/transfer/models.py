"""uengine/transfer/models.py - Phase 1a: job / file states, allowed transitions, replacement policies.

Pure data: no I/O. The journal (journal.py) refuses every transition that is not listed here, so the persisted state of
a job is always one of these values and can only move along these edges.

Job lifecycle (docs/engineering/PHASE1_TRANSFER_ENGINE_PLAN.md section 6):
    queued -> preparing -> copying -> flushing -> verifying -> committing -> (copying ... next file)
           -> [removing_sources] -> completed | completed_with_retained_sources
    side states: paused, cancel_requested -> cancelled, failed, needs_attention, interrupted
"""
from enum import Enum
from typing import Dict, FrozenSet


class JobState(str, Enum):
    QUEUED = "queued"
    PREPARING = "preparing"
    COPYING = "copying"
    FLUSHING = "flushing"
    VERIFYING = "verifying"
    COMMITTING = "committing"
    REMOVING_SOURCES = "removing_sources"
    COMPLETED = "completed"
    COMPLETED_WITH_RETAINED_SOURCES = "completed_with_retained_sources"
    PAUSED = "paused"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELLED = "cancelled"
    FAILED = "failed"
    NEEDS_ATTENTION = "needs_attention"
    INTERRUPTED = "interrupted"
    ROLLING_BACK = "rolling_back"      # 1c: undoing this job's own commits (write-ahead: every undo step is logged first)
    RECOVERING = "recovering"          # 1c: a user-chosen recovery (resume / discard) is in progress


class FileState(str, Enum):
    PENDING = "pending"
    COPYING = "copying"
    STAGED = "staged"                  # job-owned .part written and flushed
    VERIFIED = "verified"              # .part read back (uncached) and equal to the source hash
    COMMITTED = "committed"            # destination replaced / created, directory flushed
    SOURCE_REMOVED = "source_removed"  # move: source removed after the committed copy was re-confirmed
    SKIPPED_IDENTICAL = "skipped_identical"
    CONFLICT = "conflict"              # destination exists with different content and the policy forbids overwriting
    FAILED = "failed"
    SOURCE_CHANGED = "source_changed"  # source modified while it was being copied
    ROLLED_BACK = "rolled_back"        # committed, then undone because a later commit of the same job failed (1b)
    COMMITTING = "committing"          # 1c write-ahead: about to move the old version aside / publish
    ROLLING_BACK = "rolling_back"      # 1c write-ahead: about to undo this file's commit / remove its .part
    REMOVING_SOURCE = "removing_source"  # 1c write-ahead: about to remove the (verified) move source


class Operation(str, Enum):
    COPY = "copy"
    MOVE = "move"
    STAGE = "stage"        # Vault -> SSD work area
    ARCHIVE = "archive"    # SSD -> Vault studies/
    SYNC = "sync"          # SSD -> Vault studies/ (policy driven)
    RESTORE = "restore"    # Vault -> SSD, never overwrites


class CommitMode(str, Enum):
    """what happens when the destination already exists (plan section 4). Identical content is always skipped."""
    NEVER_OVERWRITE = "never_overwrite"          # different content -> CONFLICT, destination untouched (archive / sync)
    PRESERVE_PREVIOUS = "preserve_previous"      # old file kept as <dst>.replaced-<job> until the whole job is verified (stage)
    REPLACE_AFTER_VERIFY = "replace_after_verify"  # verified copy atomically replaces the old file (File Manager "replace")
    NEW_NAME = "new_name"                        # different content -> written under a new free name (restore / keep both)


DEFAULT_COMMIT_MODE: Dict[Operation, CommitMode] = {
    Operation.ARCHIVE: CommitMode.NEVER_OVERWRITE,
    Operation.SYNC: CommitMode.NEVER_OVERWRITE,
    Operation.STAGE: CommitMode.PRESERVE_PREVIOUS,
    Operation.RESTORE: CommitMode.NEW_NAME,
    Operation.COPY: CommitMode.NEW_NAME,
    Operation.MOVE: CommitMode.NEW_NAME,
}

J = JobState
_ACTIVE = (J.PREPARING, J.COPYING, J.FLUSHING, J.VERIFYING, J.COMMITTING, J.REMOVING_SOURCES, J.ROLLING_BACK,
           J.RECOVERING)
_STOP = (J.FAILED, J.NEEDS_ATTENTION, J.INTERRUPTED)

JOB_TRANSITIONS: Dict[JobState, FrozenSet[JobState]] = {
    J.QUEUED: frozenset({J.PREPARING, J.PAUSED, J.CANCELLED, J.INTERRUPTED}),
    J.PREPARING: frozenset({J.COPYING, J.COMMITTING, J.COMPLETED, J.PAUSED, J.CANCEL_REQUESTED, *_STOP}),
    J.COPYING: frozenset({J.FLUSHING, J.COPYING, J.COMMITTING, J.REMOVING_SOURCES, J.COMPLETED, J.PAUSED,
                          J.CANCEL_REQUESTED, J.ROLLING_BACK, *_STOP}),
    J.FLUSHING: frozenset({J.VERIFYING, J.PAUSED, J.CANCEL_REQUESTED, J.ROLLING_BACK, *_STOP}),
    J.VERIFYING: frozenset({J.COPYING, J.COMMITTING, J.PAUSED, J.CANCEL_REQUESTED, J.ROLLING_BACK, *_STOP}),
    J.COMMITTING: frozenset({J.COPYING, J.REMOVING_SOURCES, J.COMPLETED, J.CANCEL_REQUESTED, J.ROLLING_BACK, *_STOP}),
    J.REMOVING_SOURCES: frozenset({J.COMPLETED, J.COMPLETED_WITH_RETAINED_SOURCES, *_STOP}),
    J.ROLLING_BACK: frozenset({J.CANCELLED, *_STOP}),
    # 1c: recovery (resume or discard, chosen by the user and persisted) ends in a terminal state, or back in
    # interrupted (non-ambiguous failure, safe to retry) / needs_attention (a human must look)
    J.RECOVERING: frozenset({J.COMPLETED, J.COMPLETED_WITH_RETAINED_SOURCES, J.CANCELLED, J.NEEDS_ATTENTION, J.INTERRUPTED}),
    J.PAUSED: frozenset({J.QUEUED, J.CANCEL_REQUESTED, J.CANCELLED, J.INTERRUPTED}),
    J.CANCEL_REQUESTED: frozenset({J.CANCELLED, J.FAILED, J.INTERRUPTED}),
    J.INTERRUPTED: frozenset({J.RECOVERING}),           # 1c: only through recovery - never silently cancelled or re-run
    J.NEEDS_ATTENTION: frozenset({J.RECOVERING, J.CANCELLED}),
    J.FAILED: frozenset({J.RECOVERING, J.CANCELLED}),
    J.COMPLETED: frozenset(),
    J.COMPLETED_WITH_RETAINED_SOURCES: frozenset(),
    J.CANCELLED: frozenset(),
}

F = FileState
FILE_TRANSITIONS: Dict[FileState, FrozenSet[FileState]] = {
    F.PENDING: frozenset({F.COPYING, F.SKIPPED_IDENTICAL, F.CONFLICT, F.FAILED, F.SOURCE_CHANGED}),
    F.COPYING: frozenset({F.STAGED, F.SKIPPED_IDENTICAL, F.CONFLICT, F.FAILED, F.SOURCE_CHANGED, F.PENDING, F.ROLLING_BACK}),
    F.STAGED: frozenset({F.VERIFIED, F.FAILED, F.SOURCE_CHANGED, F.PENDING, F.ROLLING_BACK}),
    F.VERIFIED: frozenset({F.COMMITTING, F.SKIPPED_IDENTICAL, F.CONFLICT, F.FAILED, F.SOURCE_CHANGED, F.PENDING,
                           F.ROLLING_BACK, F.ROLLED_BACK}),
    F.COMMITTING: frozenset({F.COMMITTED, F.SKIPPED_IDENTICAL, F.CONFLICT, F.ROLLING_BACK, F.FAILED,
                             F.VERIFIED}),          # VERIFIED: intent abandoned before any rename (recovery)
    F.COMMITTED: frozenset({F.REMOVING_SOURCE, F.ROLLING_BACK}),
    F.REMOVING_SOURCE: frozenset({F.SOURCE_REMOVED, F.COMMITTED}),       # COMMITTED: source retained (changed)
    F.SOURCE_REMOVED: frozenset(),
    F.ROLLING_BACK: frozenset({F.ROLLED_BACK, F.CONFLICT, F.COMMITTED}),  # CONFLICT: a foreign file was left in place
    F.SKIPPED_IDENTICAL: frozenset(),
    F.CONFLICT: frozenset({F.PENDING}),
    F.FAILED: frozenset({F.PENDING, F.ROLLING_BACK, F.ROLLED_BACK}),
    F.SOURCE_CHANGED: frozenset({F.PENDING}),
    F.ROLLED_BACK: frozenset({F.PENDING}),
}

TERMINAL_JOB_STATES = frozenset(s for s, nxt in JOB_TRANSITIONS.items() if not nxt)
ACTIVE_JOB_STATES = frozenset(_ACTIVE) | {J.CANCEL_REQUESTED}
NON_TERMINAL_JOB_STATES = frozenset(JobState) - TERMINAL_JOB_STATES


class TransitionError(ValueError):
    """a state change that the state machine does not allow"""


def check_job_transition(cur, new) -> None:
    cur, new = JobState(cur), JobState(new)
    if new not in JOB_TRANSITIONS[cur]:
        raise TransitionError(f"job state {cur.value} -> {new.value} is not allowed")


def check_file_transition(cur, new) -> None:
    cur, new = FileState(cur), FileState(new)
    if new not in FILE_TRANSITIONS[cur]:
        raise TransitionError(f"file state {cur.value} -> {new.value} is not allowed")
