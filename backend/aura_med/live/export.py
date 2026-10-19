"""Human-readable and machine-readable session export bundles."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import zipfile
from typing import Any


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


def samples_csv(samples: list[dict[str, Any]]) -> str:
    channels: list[str] = []
    for sample in samples:
        for channel in sample.get("values", {}):
            if channel not in channels:
                channels.append(channel)
    output = io.StringIO(newline="")
    fields = ["sessionId", "streamId", "sensorId", "sampleId", "sequenceNumber", "sourceTimestamp", "receivedTimestamp", "processingTimestamp", "relativeTimeSec", *channels, "qualityFlags"]
    writer = csv.DictWriter(output, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for sample in samples:
        row = {field: sample.get(field, "") for field in fields}
        for channel in channels:
            row[channel] = sample.get("values", {}).get(channel, "")
        row["qualityFlags"] = ";".join(sample.get("qualityFlags", []))
        writer.writerow(row)
    return output.getvalue()


def failures_csv(failures: list[dict[str, Any]]) -> str:
    output = io.StringIO(newline="")
    fields = ["failureId", "sessionId", "streamId", "sensorId", "type", "relativeTimeSec", "affectedChannels", "technicalSeverity", "status", "reviewState", "detector", "detectorVersion", "observed", "expected", "contextIds", "recoveryInfo"]
    writer = csv.DictWriter(output, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for failure in failures:
        row = dict(failure)
        row["affectedChannels"] = ";".join(row.get("affectedChannels", []))
        for field in ("observed", "expected", "contextIds", "recoveryInfo"):
            row[field] = json.dumps(row.get(field, {}), sort_keys=True)
        writer.writerow({field: row.get(field, "") for field in fields})
    return output.getvalue()


def report_markdown(report: dict[str, Any], metadata: dict[str, Any]) -> str:
    metrics = report.get("metrics", {})
    return "\n".join(
        [
            f"# Session report: {report.get('sessionId', '')}",
            "",
            f"**Status:** `{report.get('state', '')}`  ",
            f"**Scenario:** `{metadata.get('scenario', '')}`  ",
            "",
            "## Plain-English summary",
            "",
            report.get("summary", "No summary available."),
            "",
            "## Technical details",
            "",
            report.get("technicalSummary", "No technical summary available."),
            "",
            "| Metric | Value |",
            "| --- | ---: |",
            f"| Expected sequence extent | {metrics.get('expected', 0)} |",
            f"| Received samples | {metrics.get('received', 0)} |",
            f"| Missing samples/values | {metrics.get('missing', 0)} |",
            f"| Duplicate packets | {metrics.get('duplicates', 0)} |",
            f"| Out-of-order packets | {metrics.get('outOfOrder', 0)} |",
            f"| Reconnects | {metrics.get('reconnects', 0)} |",
            "",
            "## Technical review flags",
            "",
            *( [f"- {flag}" for flag in report.get("reviewFlags", [])] or ["- none recorded"] ),
            "",
            "This report describes simulated stream reliability and technical review flags. It does not provide a diagnosis or clinical interpretation.",
            "",
        ]
    )


def build_export_zip(data: dict[str, Any]) -> bytes:
    report = data["report"]
    metadata = data["metadata"]
    files: dict[str, bytes] = {
        "manifest.json": _json_bytes(data["manifest"]),
        "session-report.md": report_markdown(report, metadata).encode("utf-8"),
        "session-report.json": _json_bytes(report),
        "session-metadata.json": _json_bytes(metadata),
        "sensor-metadata.json": _json_bytes(data.get("sensorMetadata", {})),
        "normalized-samples.csv": samples_csv(data["samples"]).encode("utf-8"),
        "failure-events.json": _json_bytes(data["failures"]),
        "failure-events.csv": failures_csv(data["failures"]).encode("utf-8"),
        "quality-events.json": _json_bytes([event for event in data["events"] if event.get("type") == "quality"]),
        "algorithm-events.json": _json_bytes([event for event in data["events"] if event.get("type") == "algorithm"]),
        "raw-records.json": _json_bytes(data.get("raw", [])),
    }
    checksums = {
        name: hashlib.sha256(content).hexdigest()
        for name, content in sorted(files.items())
    }
    files["checksums.json"] = _json_bytes(checksums)
    # The manifest inside the archive names the checksum file and every data
    # artifact.  Rewrite it after the final file set is known.
    manifest = dict(data["manifest"])
    manifest["files"] = sorted(files)
    files["manifest.json"] = _json_bytes(manifest)
    checksums["manifest.json"] = hashlib.sha256(files["manifest.json"]).hexdigest()
    files["checksums.json"] = _json_bytes(checksums)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in sorted(files.items()):
            archive.writestr(name, content)
    return output.getvalue()


__all__ = ["build_export_zip", "failures_csv", "report_markdown", "samples_csv"]
