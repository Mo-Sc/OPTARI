"""Per-scan outcome record for a batch run.

Written out after every scan rather than at the end: a run over a whole study can
take hours, and a crash four hours in must not take the record of the first three
with it. The same reason the ROI table autosaves.
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd

from optari.io.export_pipeline import ROI_TABLE_META_SHEET, file_origin
from optari.utils.files import atomic_destination

logger = logging.getLogger(__name__)

REPORT_SHEET = "batch_report"

REPORT_COLUMNS = [
    "study",
    "scan",
    "scan_name",
    "kind",
    "status",
    "failed_step",
    "message",
    "source_layer",
    "analysis_frame",
    "n_rows",
    "duration_s",
    "hdf5_path",
    "ipasc_path",
    "overlay_path",
    "started_at",
    "finished_at",
]


@dataclass
class _Entry:
    """One scan's row in the report: identity, outcome, output paths, and timings."""

    study: str
    scan: str
    scan_name: str
    kind: str
    started_at: dt.datetime
    status: str = "running"
    failed_step: str = ""
    message: str = ""
    source_layer: str = ""
    analysis_frame: int | None = None
    n_rows: int = 0
    hdf5_path: str = ""
    ipasc_path: str = ""
    overlay_path: str = ""
    finished_at: dt.datetime | None = None

    def as_row(self) -> dict:
        """Every field, plus the elapsed time. REPORT_COLUMNS decides the order."""
        row = asdict(self)
        row["started_at"] = self.started_at.isoformat(timespec="seconds")
        if self.finished_at is None:
            row["finished_at"] = ""
            row["duration_s"] = None
        else:
            row["finished_at"] = self.finished_at.isoformat(timespec="seconds")
            row["duration_s"] = round(
                (self.finished_at - self.started_at).total_seconds(), 2
            )
        return row


class BatchReport:
    """What happened to every scan in a run, mirrored to *destination* as it goes."""

    def __init__(
        self, destination: Path | None = None, plan_source: dict | None = None
    ):
        """Track scan outcomes, mirroring the report to *destination* after each update.

        Args:
            destination: Path to write batch_report.xlsx to, or None to keep the report in memory only.
            plan_source: The batch preset this run came from, recorded in the report's provenance sheet.
        """
        self._entries: dict[str, _Entry] = {}
        self._destination = destination
        self._plan_source = plan_source or {}

    def __len__(self) -> int:
        """Number of scans recorded so far, regardless of outcome."""
        return len(self._entries)

    @property
    def rows(self) -> pd.DataFrame:
        """All recorded scans as a DataFrame, in REPORT_COLUMNS order."""
        frame = pd.DataFrame([e.as_row() for e in self._entries.values()])
        return (
            frame.reindex(columns=REPORT_COLUMNS)
            if not frame.empty
            else pd.DataFrame(columns=REPORT_COLUMNS)
        )

    def counts(self) -> dict[str, int]:
        """How many scans ended in each status, for the run summary."""
        counts: dict[str, int] = {}
        for entry in self._entries.values():
            counts[entry.status] = counts.get(entry.status, 0) + 1
        return counts

    @property
    def failures(self) -> list[_Entry]:
        """Entries for scans that ended with status "failed"."""
        return [e for e in self._entries.values() if e.status == "failed"]

    # ============ recording ============
    def start(self, job) -> None:
        """Begin tracking *job*, recording its start time, and mirror the report to disk."""
        self._entries[job.key] = _Entry(
            study=job.study_path.name,
            scan=job.scan_path.name,
            scan_name=job.scan_name,
            kind=job.scan_info.kind,
            started_at=dt.datetime.now(),
        )
        self._write()

    def note(self, job, **fields) -> None:
        """Attach details to a scan still being processed (frame, output paths, row count)."""
        entry = self._entries.get(job.key)
        if entry is None:
            return
        for key, value in fields.items():
            # A typo here would otherwise vanish silently: asdict only reports fields.
            if not hasattr(entry, key):
                raise AttributeError(f"batch report has no field '{key}'")
            setattr(entry, key, value)

    def succeed(self, job) -> None:
        """Mark *job* as completed successfully."""
        self._finish(job, "ok")

    def fail(self, job, message: str, step: str = "") -> None:
        """Mark *job* as failed, recording the reason and which step it failed on."""
        self._finish(job, "failed", message=message, failed_step=step)

    def skip(self, job, message: str = "") -> None:
        """Mark *job* as skipped without being attempted."""
        self._finish(job, "skipped", message=message)

    def cancel(self, job) -> None:
        """Mark *job* as cancelled by the user."""
        self._finish(job, "cancelled")

    def _finish(
        self, job, status: str, *, message: str = "", failed_step: str = ""
    ) -> None:
        entry = self._entries.get(job.key)
        if entry is None:
            self.start(job)
            entry = self._entries[job.key]
        entry.status = status
        entry.message = message
        entry.failed_step = failed_step
        entry.finished_at = dt.datetime.now()
        self._write()

    # ============ persistence ============
    def _write(self) -> None:
        """Overwrite the report file. Never raises: losing the report must not stop a run."""
        if self._destination is None:
            return
        path = self._destination
        meta = file_origin(batch_plan=self._plan_source)
        meta_df = pd.DataFrame(
            {
                "key": list(meta.keys()),
                "value": [str(v) for v in meta.values()],
            }
        )
        try:
            with (
                atomic_destination(path) as temporary,
                pd.ExcelWriter(temporary) as writer,
            ):
                self.rows.to_excel(
                    writer, sheet_name=REPORT_SHEET, index=False
                )
                meta_df.to_excel(
                    writer, sheet_name=ROI_TABLE_META_SHEET, index=False
                )
        except OSError:
            logger.exception("could not write the batch report to %s", path)

    def summary(self) -> str:
        """One line for the batch window once the run ends."""
        counts = self.counts()
        parts = [
            f"{count} {status}" for status, count in sorted(counts.items())
        ]
        return (
            f"{len(self)} scan(s): {', '.join(parts)}"
            if parts
            else "nothing to do"
        )
