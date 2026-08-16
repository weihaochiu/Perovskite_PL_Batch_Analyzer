from __future__ import annotations

import json
import os
import threading
import traceback
from pathlib import Path
from time import perf_counter
from typing import Any

import numpy as np
from PySide6.QtCore import QObject, Signal, Slot

from pl_core import (
    CompletedFit,
    capture_fit_settings,
    fit_best_model,
    fit_spectrum,
    fit_temperature,
    prepare_spectrum,
    read_table,
    result_to_dict,
)


def append_jsonl(path: str | Path, payload: dict[str, Any], *, reset: bool = False) -> None:
    """Write one durable JSON line so earlier batch entries survive a later failure."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "w" if reset else "a"
    with path.open(mode, encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


class BatchFitWorker(QObject):
    item_started = Signal(object)
    item_completed = Signal(object)
    item_failed = Signal(object)
    progress = Signal(object)
    warning = Signal(str)
    finished = Signal(object)

    def __init__(self, tasks, settings, checkpoint_path, timing_log_path):
        super().__init__()
        self.tasks = [(int(index), dict(record)) for index, record in tasks]
        self.settings = dict(settings)
        self.checkpoint_path = str(checkpoint_path)
        self.timing_log_path = str(timing_log_path)
        self._cancel_requested = threading.Event()

    def request_cancel(self) -> None:
        """Thread-safe cooperative cancellation, checked between spectrum fits."""
        self._cancel_requested.set()

    def _write_initial_logs(self) -> None:
        header = {
            "type": "batch_start",
            "total": len(self.tasks),
            "settings": self.settings,
            "files": [record["path"] for _, record in self.tasks],
            "record_ids": [record["record_id"] for _, record in self.tasks],
        }
        append_jsonl(self.checkpoint_path, header, reset=True)
        append_jsonl(
            self.timing_log_path,
            {"type": "batch_start", "total": len(self.tasks)},
            reset=True,
        )

    def _checkpoint_completed(self, payload: dict[str, Any]) -> None:
        append_jsonl(
            self.checkpoint_path,
            {
                "type": "completed",
                "row_index": payload["row_index"],
                "record_id": payload["record_id"],
                "label": payload["label"],
                "source": payload["source"],
                "spectrum": result_to_dict(payload["spectrum"]),
                "fit": result_to_dict(payload["result"]),
                "timings": payload["timings"],
            },
        )

    def _checkpoint_failed(self, payload: dict[str, Any]) -> None:
        append_jsonl(
            self.checkpoint_path,
            {
                "type": "failed",
                "row_index": payload["row_index"],
                "record_id": payload["record_id"],
                "label": payload["label"],
                "source": payload["source"],
                "error": payload["error"],
                "traceback": payload["traceback"],
                "timings": payload["timings"],
            },
        )

    def _fit_one(self, record: dict[str, Any], timings: dict[str, float]):
        started = perf_counter()
        try:
            frame = read_table(record["path"])
        finally:
            timings["parse"] = perf_counter() - started

        started = perf_counter()
        try:
            spectrum = prepare_spectrum(
                frame,
                record["x"],
                record["y"],
                x_type=self.settings["x_type"],
                temperature_k=record["temperature"],
                condition=record["condition"],
                sample_id=record["sample_id"],
                source_name=Path(record["path"]).name,
            )
        finally:
            timings["preprocess"] = perf_counter() - started

        model = self.settings["model"]
        npeaks = self.settings["npeaks"]
        if model == "Automatic" or str(npeaks).startswith("Auto"):
            models = ("Gaussian", "Pseudo-Voigt", "Voigt") if model == "Automatic" else (model,)
            max_peaks = 2 if str(npeaks).startswith("Auto") else int(npeaks)
            result, _ = fit_best_model(
                spectrum,
                models=models,
                max_peaks=max_peaks,
                baseline_mode=self.settings["baseline"],
                fit_range_ev=self.settings["fit_range"],
                use_jacobian=self.settings["jacobian"],
                timings=timings,
            )
        else:
            result = fit_spectrum(
                spectrum,
                model=model,
                n_peaks=int(npeaks),
                baseline_mode=self.settings["baseline"],
                fit_range_ev=self.settings["fit_range"],
                use_jacobian=self.settings["jacobian"],
                instrument_fwhm_mev=self.settings["instrument_fwhm_mev"],
                timings=timings,
            )
        automatic = model == "Automatic" or str(npeaks).startswith("Auto")
        applied_instrument_fwhm = 0.0 if automatic else self.settings["instrument_fwhm_mev"]
        capture_fit_settings(
            result,
            spectrum,
            requested_model=model,
            requested_n_peaks=npeaks,
            baseline_mode=self.settings["baseline"],
            jacobian_corrected=self.settings["jacobian"],
            instrument_fwhm_mev=applied_instrument_fwhm,
            automatic_model_selection=automatic,
        )
        return spectrum, result

    def _temperature_fits(self, rows, errors):
        output = {}
        groups = {}
        for label, spectrum, result in rows:
            groups.setdefault(spectrum.condition, []).append((label, spectrum, result))
        for condition, items in groups.items():
            if self._cancel_requested.is_set():
                break
            if len({spectrum.temperature_k for _, spectrum, _ in items}) < 3:
                continue
            items = sorted(items, key=lambda item: item[1].temperature_k)
            temperatures = np.array([spectrum.temperature_k for _, spectrum, _ in items])
            energy = np.array([result.peaks[0].center_ev for _, _, result in items])
            fwhm = np.array([result.peaks[0].fwhm_mev for _, _, result in items])
            area = np.array([sum(peak.area for peak in result.peaks) for _, _, result in items])
            output[condition] = {}
            fits = (
                ("Peak energy", energy, self.settings["energy_model"]),
                ("FWHM", fwhm, self.settings["fwhm_model"]),
                ("Integrated intensity", area, self.settings["intensity_model"]),
            )
            for kind, values, model in fits:
                try:
                    output[condition][kind] = fit_temperature(temperatures, values, kind, model)
                except Exception as exc:
                    errors.append(f"{condition} {kind}: {exc}")
        return output

    @Slot()
    def run(self) -> None:
        batch_started = perf_counter()
        rows = []
        errors = []
        processed = 0
        total = len(self.tasks)
        try:
            self._write_initial_logs()
        except Exception as exc:
            self.warning.emit(f"無法建立 checkpoint/timing log：{exc}")

        for row_index, record in self.tasks:
            if self._cancel_requested.is_set():
                break
            source = Path(record["path"]).name
            self.item_started.emit(
                {
                    "row_index": row_index,
                    "record_id": record["record_id"],
                    "source": source,
                    "completed": processed,
                    "total": total,
                }
            )
            item_started = perf_counter()
            timings = {"parse": 0.0, "preprocess": 0.0, "initial_guess": 0.0, "optimization": 0.0}
            try:
                spectrum, result = self._fit_one(record, timings)
                elapsed = perf_counter() - item_started
                timings["total"] = elapsed
                payload = {
                    "row_index": row_index,
                    "record_id": record["record_id"],
                    "label": record["code"],
                    "source": source,
                    "spectrum": spectrum,
                    "result": result,
                    "timings": timings,
                }
                rows.append(
                    CompletedFit(
                        record_id=record["record_id"],
                        output_name=record["code"],
                        spectrum=spectrum,
                        result=result,
                    )
                )
                try:
                    self._checkpoint_completed(payload)
                    append_jsonl(self.timing_log_path, {"type": "file", **{k: v for k, v in payload.items() if k not in {"spectrum", "result"}}})
                except Exception as exc:
                    self.warning.emit(f"{source} checkpoint 寫入失敗：{exc}")
                self.item_completed.emit(payload)
            except Exception as exc:
                elapsed = perf_counter() - item_started
                timings["total"] = elapsed
                message = f"檔案 {source}：{exc}"
                errors.append(message)
                payload = {
                    "row_index": row_index,
                    "record_id": record["record_id"],
                    "label": record["code"],
                    "source": source,
                    "error": str(exc),
                    "traceback": traceback.format_exc(),
                    "timings": timings,
                }
                try:
                    self._checkpoint_failed(payload)
                    append_jsonl(self.timing_log_path, {"type": "file", **payload})
                except Exception as checkpoint_exc:
                    self.warning.emit(f"{source} checkpoint 寫入失敗：{checkpoint_exc}")
                self.item_failed.emit(payload)

            processed += 1
            batch_elapsed = perf_counter() - batch_started
            eta = batch_elapsed / processed * (total - processed) if processed else 0.0
            self.progress.emit(
                {
                    "source": source,
                    "completed": processed,
                    "total": total,
                    "percent": 100.0 * processed / total if total else 100.0,
                    "file_elapsed": elapsed,
                    "elapsed": batch_elapsed,
                    "eta": eta,
                }
            )

        cancelled = self._cancel_requested.is_set()
        tempfits = {}
        temperature_fit_elapsed = 0.0
        if not cancelled:
            started = perf_counter()
            tempfits = self._temperature_fits(rows, errors)
            temperature_fit_elapsed = perf_counter() - started
            try:
                append_jsonl(
                    self.timing_log_path,
                    {"type": "batch_stage", "stage": "temperature_fit", "seconds": temperature_fit_elapsed},
                )
            except Exception as exc:
                self.warning.emit(f"timing log 寫入失敗：{exc}")

        summary = {
            "cancelled": cancelled,
            "processed": processed,
            "total": total,
            "succeeded": len(rows),
            "errors": errors,
            "tempfits": tempfits,
            "elapsed": perf_counter() - batch_started,
            "temperature_fit_elapsed": temperature_fit_elapsed,
            "checkpoint_path": self.checkpoint_path,
            "timing_log_path": self.timing_log_path,
        }
        try:
            append_jsonl(self.checkpoint_path, {"type": "batch_end", **{k: v for k, v in summary.items() if k != "tempfits"}})
            append_jsonl(self.timing_log_path, {"type": "batch_end", **{k: v for k, v in summary.items() if k != "tempfits"}})
        except Exception as exc:
            self.warning.emit(f"batch 結尾紀錄寫入失敗：{exc}")
        self.finished.emit(summary)
