import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QFileDialog

from app import MainWindow


def project_record(record_id=None):
    record = {
        "use": True,
        "export": True,
        "condition": "C1",
        "sample_id": "C1-1",
        "temperature": 300.0,
        "direction": "Isothermal",
        "code": "sample",
        "path": r"D:\Run\sample.asc",
        "x": "Wavelength_nm",
        "y": "PL_Intensity",
        "status": "Ready",
    }
    if record_id is not None:
        record["record_id"] = record_id
    return record


class TestProjectRecordIdCompatibility(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def test_old_project_without_id_gets_id_and_saves_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_path = Path(tmp) / "old.plproj"
            saved_path = Path(tmp) / "saved.plproj"
            old_path.write_text(json.dumps({"version": "0.3.0", "records": [project_record()]}), encoding="utf-8")
            window = MainWindow()
            with patch.object(QFileDialog, "getOpenFileName", return_value=(str(old_path), "")):
                window.open_project()
            generated = window.records[0]["record_id"]
            self.assertTrue(generated)
            with patch.object(QFileDialog, "getSaveFileName", return_value=(str(saved_path), "")):
                window.save_project()
            saved = json.loads(saved_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["records"][0]["record_id"], generated)
            window.close()

    def test_new_project_preserves_existing_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "new.plproj"
            path.write_text(json.dumps({"version": "0.4.0", "records": [project_record("stable-record-id")]}), encoding="utf-8")
            window = MainWindow()
            with patch.object(QFileDialog, "getOpenFileName", return_value=(str(path), "")):
                window.open_project()
            self.assertEqual(window.records[0]["record_id"], "stable-record-id")
            window.close()


if __name__ == "__main__":
    unittest.main()
