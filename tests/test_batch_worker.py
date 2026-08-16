import ctypes
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QThread, QTimer
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

import batch_worker
from app import MainWindow


def write_synthetic_asc(path: Path, index: int) -> None:
    wavelength = np.linspace(700.0, 900.0, 256)
    energy = 1239.841984 / wavelength
    center = 1.53 + (index % 7) * 0.002
    intensity = 1200.0 + 9000.0 * np.exp(-4 * np.log(2) * ((energy - center) / 0.075) ** 2)
    rows = [f"{x:.6f}\t{y:.8f}" for x, y in zip(wavelength, intensity)]
    rows.extend(["", f"Synthetic index: {index}"])
    path.write_text("\r\n".join(rows) + "\r\n", encoding="ascii", newline="")


class ProcessMemoryCounters(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.c_ulong),
        ("PageFaultCount", ctypes.c_ulong),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


def working_set_bytes() -> int:
    counters = ProcessMemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    get_current_process = ctypes.windll.kernel32.GetCurrentProcess
    get_current_process.restype = ctypes.c_void_p
    get_memory_info = ctypes.windll.psapi.GetProcessMemoryInfo
    get_memory_info.argtypes = [ctypes.c_void_p, ctypes.POINTER(ProcessMemoryCounters), ctypes.c_ulong]
    get_memory_info.restype = ctypes.c_int
    handle = get_current_process()
    if not get_memory_info(handle, ctypes.byref(counters), counters.cb):
        raise ctypes.WinError()
    return int(counters.WorkingSetSize)


class TestBatchWorkerStress(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def make_window(self, root: Path) -> MainWindow:
        paths = []
        for index in range(79):
            path = root / f"Stress_300K_{index:03d}.asc"
            write_synthetic_asc(path, index)
            paths.append(path)
        window = MainWindow()
        window.batch_log_directory = root / "logs"
        window.add_paths(paths)
        self.assertEqual(len(window.records), 79)
        window.model.setCurrentText("Gaussian")
        window.npeaks.setCurrentText("1")
        window.jacobian.setChecked(False)
        return window

    def run_batch(self, window: MainWindow, *, cancel_after_ms=None, close_after_ms=None, timeout_ms=120000):
        loop = QEventLoop()
        outcome = {}
        heartbeat = []
        progress = []
        progress_on_gui_thread = []
        memory_samples = [working_set_bytes()]
        timer = QTimer()
        timer.setInterval(5)

        def on_timer():
            heartbeat.append(time.perf_counter())
            memory_samples.append(working_set_bytes())

        def on_progress(payload):
            progress.append(payload["completed"])
            progress_on_gui_thread.append(QThread.currentThread() is self.application.thread())

        def on_finished(summary):
            outcome["summary"] = summary
            loop.quit()

        timer.timeout.connect(on_timer)
        window.batch_progressed.connect(on_progress)
        window.batch_completed.connect(on_finished)
        timer.start()
        started = time.perf_counter()
        window.analyze()
        if cancel_after_ms is not None:
            QTimer.singleShot(cancel_after_ms, window.cancel_batch)
        if close_after_ms is not None:
            QTimer.singleShot(close_after_ms, window.close)
        QTimer.singleShot(timeout_ms, loop.quit)
        loop.exec()
        elapsed = time.perf_counter() - started
        timer.stop()
        self.assertIn("summary", outcome, "batch timed out")

        wait_loop = QEventLoop()
        QTimer.singleShot(20, wait_loop.quit)
        deadline = time.perf_counter() + 10
        while window._batch_thread is not None and time.perf_counter() < deadline:
            wait_loop.exec()
            wait_loop = QEventLoop()
            QTimer.singleShot(20, wait_loop.quit)
        self.assertIsNone(window._batch_thread, "worker thread did not shut down")
        return outcome["summary"], heartbeat, progress, progress_on_gui_thread, memory_samples, elapsed

    def test_79_files_keep_event_loop_responsive_continue_after_bad_file_and_bound_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            window = self.make_window(root)
            window.model.setCurrentText("Automatic")
            window.npeaks.setCurrentText("Auto (1–2)")
            window.jacobian.setChecked(True)
            (root / "Stress_300K_037.asc").write_text("broken after import", encoding="ascii")
            with patch.object(QMessageBox, "warning"):
                summary, heartbeat, progress, gui_threads, samples, elapsed = self.run_batch(window)

            self.assertFalse(summary["cancelled"])
            self.assertEqual(summary["processed"], 79)
            self.assertEqual(summary["succeeded"], 78)
            self.assertEqual(len(window.results), 78)
            self.assertEqual(window.records[37]["status"], "Failed")
            self.assertEqual(window.records[78]["status"], "OK")
            self.assertGreater(len(heartbeat), 3)
            self.assertEqual(progress[-1], 79)
            self.assertEqual(progress, sorted(progress))
            self.assertTrue(all(gui_threads))
            self.assertTrue(window.batch_action.isEnabled())

            checkpoint_rows = [json.loads(line) for line in Path(window.checkpoint_path).read_text(encoding="utf-8").splitlines()]
            self.assertEqual(sum(row["type"] == "completed" for row in checkpoint_rows), 78)
            self.assertEqual(sum(row["type"] == "failed" for row in checkpoint_rows), 1)
            attempted = [row for row in checkpoint_rows if row["type"] in {"completed", "failed"}]
            self.assertTrue(all(row.get("record_id") for row in attempted))
            self.assertEqual(
                {row["record_id"] for row in attempted},
                {record["record_id"] for record in window.records},
            )
            self.assertEqual(
                {completed.record_id for completed in window.results},
                set(window.results_by_record_id),
            )
            timing_rows = [json.loads(line) for line in Path(window.timing_log_path).read_text(encoding="utf-8").splitlines()]
            file_timings = [row for row in timing_rows if row["type"] == "file"]
            self.assertEqual(len(file_timings), 79)
            for row in file_timings:
                self.assertTrue({"parse", "preprocess", "initial_guess", "optimization"}.issubset(row["timings"]))
            self.assertTrue(any(row.get("stage") == "plot" for row in timing_rows))

            baseline = samples[0]
            peak = max(samples)
            growth_per_file = (peak - baseline) / 79
            self.assertLess(peak - baseline, 320 * 1024 * 1024)
            self.assertLess(growth_per_file, 4 * 1024 * 1024)
            print(
                f"STRESS_METRICS files=79 elapsed_seconds={elapsed:.3f} "
                f"peak_working_set_mib={peak / 1024 / 1024:.2f} "
                f"working_set_growth_mib={(peak - baseline) / 1024 / 1024:.2f}"
            )
            window.close()
        self.application.processEvents()

    def test_cancel_79_file_batch_keeps_completed_results_and_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            window = self.make_window(root)
            original_fit = batch_worker.fit_spectrum

            def delayed_fit(*args, **kwargs):
                time.sleep(0.025)
                return original_fit(*args, **kwargs)

            with patch("batch_worker.fit_spectrum", side_effect=delayed_fit), patch.object(QMessageBox, "warning"):
                summary, heartbeat, progress, gui_threads, _, _ = self.run_batch(window, cancel_after_ms=180)

            self.assertTrue(summary["cancelled"])
            self.assertGreater(summary["processed"], 0)
            self.assertLess(summary["processed"], 79)
            self.assertEqual(len(window.results), summary["succeeded"])
            self.assertEqual(summary["processed"], summary["succeeded"])
            self.assertGreater(len(heartbeat), 3)
            self.assertTrue(all(gui_threads))
            self.assertTrue(window.batch_action.isEnabled())
            checkpoint_rows = [json.loads(line) for line in Path(window.checkpoint_path).read_text(encoding="utf-8").splitlines()]
            self.assertEqual(sum(row["type"] == "completed" for row in checkpoint_rows), summary["succeeded"])
            window.close()
        self.application.processEvents()

    def test_close_requests_safe_worker_shutdown(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            window = self.make_window(root)
            window.show()
            original_fit = batch_worker.fit_spectrum

            def delayed_fit(*args, **kwargs):
                time.sleep(0.05)
                return original_fit(*args, **kwargs)

            with patch("batch_worker.fit_spectrum", side_effect=delayed_fit), patch.object(QMessageBox, "warning"):
                summary, _, _, _, _, _ = self.run_batch(window, close_after_ms=30)

            self.assertTrue(summary["cancelled"])
            self.application.processEvents()
            self.assertFalse(window.isVisible())

    def test_export_keeps_excel_columns_and_records_export_timing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "Single_300K.asc"
            write_synthetic_asc(path, 0)
            window = MainWindow()
            window.batch_log_directory = root / "logs"
            window.add_paths([path])
            window.model.setCurrentText("Gaussian")
            window.npeaks.setCurrentText("1")
            with patch.object(QMessageBox, "warning"):
                self.run_batch(window)

            output = root / "export"
            window.model.setCurrentText("Lorentzian")
            window.jacobian.setChecked(False)
            window.table.item(0, 6).setText("Renamed_After_Fit")
            window.export_timestamped_folder.setChecked(False)
            with patch.object(QFileDialog, "getExistingDirectory", return_value=str(output)), patch.object(QMessageBox, "information"):
                window.export()

            self.assertTrue((output / "PL_batch_results.xlsx").is_file())
            self.assertTrue((output / "Individual_Fit_Data" / "Renamed_After_Fit.csv").is_file())
            index_rows = json.loads((output / "Individual_Fit_Data" / "Index.json").read_text(encoding="utf-8"))
            self.assertEqual(index_rows[0]["Requested_Model"], "Gaussian")
            self.assertTrue(index_rows[0]["Jacobian_Corrected"])
            timing_rows = [json.loads(line) for line in Path(window.timing_log_path).read_text(encoding="utf-8").splitlines()]
            self.assertTrue(any(row.get("stage") == "export" for row in timing_rows))
            window.close()
        self.application.processEvents()


if __name__ == "__main__":
    unittest.main()
