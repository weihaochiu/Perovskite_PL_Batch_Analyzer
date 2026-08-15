import os
import re
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


REPOSITORY = Path(__file__).resolve().parents[1]


class WindowsBatchFileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._compiler_temp = tempfile.TemporaryDirectory()
        compiler_root = Path(cls._compiler_temp.name)
        source_path = compiler_root / "StubPython.cs"
        cls.stub_executable = compiler_root / "stub-python.exe"
        source_path.write_text(
            textwrap.dedent(
                r"""
                using System;
                using System.Diagnostics;
                using System.IO;
                using System.Reflection;

                internal static class StubPython
                {
                    private static int EnvInt(string name, int fallback)
                    {
                        int value;
                        return int.TryParse(Environment.GetEnvironmentVariable(name), out value)
                            ? value
                            : fallback;
                    }

                    private static void Log(string[] args)
                    {
                        string logPath = Environment.GetEnvironmentVariable("STUB_LOG");
                        if (!String.IsNullOrEmpty(logPath))
                            File.AppendAllText(logPath, String.Join("\t", args) + Environment.NewLine);
                    }

                    public static int Main(string[] args)
                    {
                        Log(args);
                        string joined = String.Join(" ", args);
                        int moduleIndex = Array.IndexOf(args, "-m");

                        if (moduleIndex >= 0 && moduleIndex + 1 < args.Length && args[moduleIndex + 1] == "venv")
                        {
                            int exitCode = EnvInt("STUB_VENV_EXIT", 0);
                            if (exitCode != 0)
                                return exitCode;
                            string target = Path.GetFullPath(args[moduleIndex + 2]);
                            string scripts = Path.Combine(target, "Scripts");
                            Directory.CreateDirectory(scripts);
                            File.Copy(Assembly.GetExecutingAssembly().Location, Path.Combine(scripts, "python.exe"), true);
                            return 0;
                        }

                        if (moduleIndex >= 0 && moduleIndex + 1 < args.Length && args[moduleIndex + 1] == "pip")
                            return EnvInt("STUB_PIP_EXIT", 0);

                        if (joined.Contains("version_info"))
                            return EnvInt("STUB_VERSION_EXIT", 0);

                        if (joined.Contains("normcase"))
                            return EnvInt("STUB_PATH_EXIT", 0);

                        if (joined.Contains("import numpy"))
                            return EnvInt("STUB_IMPORT_EXIT", 0);

                        if (Array.IndexOf(args, "--version") >= 0)
                        {
                            Console.WriteLine("Python 3.11.9");
                            return 0;
                        }

                        if (joined.Contains("sys.version.split"))
                        {
                            Console.WriteLine("3.11.9");
                            return 0;
                        }

                        if (args.Length > 0 && args[args.Length - 1].EndsWith("app.py", StringComparison.OrdinalIgnoreCase))
                            return EnvInt("STUB_APP_EXIT", 0);

                        return EnvInt("STUB_EXECUTABLE_EXIT", 0);
                    }
                }
                """
            ),
            encoding="ascii",
        )

        windows_directory = Path(os.environ["WINDIR"])
        compiler_candidates = (
            windows_directory / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe",
            windows_directory / "Microsoft.NET" / "Framework" / "v4.0.30319" / "csc.exe",
        )
        compiler = next((path for path in compiler_candidates if path.is_file()), None)
        if compiler is None:
            raise unittest.SkipTest("The Windows C# compiler required for batch-file stubs is unavailable.")

        completed = subprocess.run(
            [
                str(compiler),
                "/nologo",
                "/target:exe",
                f"/out:{cls.stub_executable}",
                str(source_path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if completed.returncode != 0:
            raise RuntimeError(f"Failed to compile batch-file stub:\n{completed.stdout}\n{completed.stderr}")

    @classmethod
    def tearDownClass(cls):
        cls._compiler_temp.cleanup()

    def make_fixture(self, include_venv=True):
        temporary_directory = tempfile.TemporaryDirectory()
        root = Path(temporary_directory.name) / "Perovskite PL Batch Analyzer Test"
        root.mkdir()
        shutil.copy2(REPOSITORY / "run_windows.bat", root / "run_windows.bat")
        shutil.copy2(REPOSITORY / "setup_windows.bat", root / "setup_windows.bat")
        (root / "requirements.txt").write_text("example-package\n", encoding="ascii")
        (root / "app.py").write_text("raise SystemExit(0)\n", encoding="ascii")
        if include_venv:
            scripts = root / ".venv" / "Scripts"
            scripts.mkdir(parents=True)
            shutil.copy2(self.stub_executable, scripts / "python.exe")
        return temporary_directory, root

    def run_batch(self, root, filename, **environment_overrides):
        environment = os.environ.copy()
        environment.update({key: str(value) for key, value in environment_overrides.items()})
        return subprocess.run(
            ["cmd.exe", "/d", "/c", str(root / filename)],
            cwd=root,
            env=environment,
            input="\n\n",
            capture_output=True,
            text=True,
            timeout=30,
        )

    def test_launcher_rejects_missing_venv(self):
        temporary_directory, root = self.make_fixture(include_venv=False)
        with temporary_directory:
            completed = self.run_batch(root, "run_windows.bat")
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("Run setup_windows.bat", completed.stdout)

    def test_launcher_handles_spaces_and_preserves_zero_exit(self):
        temporary_directory, root = self.make_fixture()
        with temporary_directory:
            completed = self.run_batch(root, "run_windows.bat", STUB_APP_EXIT=0)
            self.assertEqual(completed.returncode, 0, completed.stdout)
            self.assertIn(str(root / ".venv" / "Scripts" / "python.exe"), completed.stdout)
            self.assertIn("Application closed normally.", completed.stdout)

    def test_launcher_rejects_wrong_python_version(self):
        temporary_directory, root = self.make_fixture()
        with temporary_directory:
            completed = self.run_batch(root, "run_windows.bat", STUB_VERSION_EXIT=4)
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("does not use Python 3.11", completed.stdout)
            self.assertIn("Run setup_windows.bat", completed.stdout)

    def test_launcher_rejects_missing_runtime_dependency(self):
        temporary_directory, root = self.make_fixture()
        with temporary_directory:
            completed = self.run_batch(root, "run_windows.bat", STUB_IMPORT_EXIT=5)
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("Required runtime dependencies", completed.stdout)
            self.assertIn("Run setup_windows.bat", completed.stdout)

    def test_launcher_preserves_nonzero_app_exit(self):
        temporary_directory, root = self.make_fixture()
        with temporary_directory:
            completed = self.run_batch(root, "run_windows.bat", STUB_APP_EXIT=23)
            self.assertEqual(completed.returncode, 23, completed.stdout)
            self.assertIn("Application exited with an error.", completed.stdout)
            self.assertIn("Exit code: 23", completed.stdout)

    def test_setup_creates_local_venv_and_installs_with_local_python(self):
        temporary_directory, root = self.make_fixture(include_venv=False)
        with temporary_directory:
            fake_bin = root / "Fake Python Commands"
            fake_bin.mkdir()
            shutil.copy2(self.stub_executable, fake_bin / "py.exe")
            shutil.copy2(self.stub_executable, fake_bin / "python.exe")
            log_path = root / "stub.log"
            completed = self.run_batch(
                root,
                "setup_windows.bat",
                PATH=fake_bin,
                STUB_LOG=log_path,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout)
            self.assertTrue((root / ".venv" / "Scripts" / "python.exe").is_file())
            self.assertIn("Setup completed successfully.", completed.stdout)
            log = log_path.read_text(encoding="utf-8")
            self.assertIn("normcase", log)
            self.assertIn("-m\tpip\tinstall\t-r", log)
            self.assertIn(str(root / "requirements.txt"), log)

    def test_setup_rejects_existing_wrong_version_without_overwriting(self):
        temporary_directory, root = self.make_fixture()
        with temporary_directory:
            interpreter = root / ".venv" / "Scripts" / "python.exe"
            original_size = interpreter.stat().st_size
            completed = self.run_batch(root, "setup_windows.bat", STUB_VERSION_EXIT=6)
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("does not use Python 3.11", completed.stdout)
            self.assertEqual(interpreter.stat().st_size, original_size)

    def test_setup_preserves_requirements_install_exit_code(self):
        temporary_directory, root = self.make_fixture()
        with temporary_directory:
            completed = self.run_batch(root, "setup_windows.bat", STUB_PIP_EXIT=31)
            self.assertEqual(completed.returncode, 31, completed.stdout)
            self.assertIn("Failed to install requirements.txt", completed.stdout)
            self.assertIn("Exit code: 31", completed.stdout)

    def test_setup_rejects_when_python_311_is_unavailable(self):
        temporary_directory, root = self.make_fixture(include_venv=False)
        with temporary_directory:
            fake_bin = root / "Fake Python Commands"
            fake_bin.mkdir()
            shutil.copy2(self.stub_executable, fake_bin / "py.exe")
            shutil.copy2(self.stub_executable, fake_bin / "python.exe")
            completed = self.run_batch(
                root,
                "setup_windows.bat",
                PATH=fake_bin,
                STUB_VERSION_EXIT=7,
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("Install 64-bit Python 3.11", completed.stdout)
            self.assertFalse((root / ".venv").exists())

    def test_batch_files_do_not_use_unsafe_runtime_commands(self):
        run_text = (REPOSITORY / "run_windows.bat").read_text(encoding="ascii")
        setup_text = (REPOSITORY / "setup_windows.bat").read_text(encoding="ascii")
        combined = run_text + "\n" + setup_text

        self.assertNotIn("activate.bat", combined.lower())
        self.assertIsNone(re.search(r"(?im)^\s*pip(?:\.exe)?\b", combined))
        self.assertNotIn("pip install", run_text.lower())
        self.assertIsNone(re.search(r"(?im)^\s*(?:python|py)\s+.*app\.py", run_text))
        self.assertIn(
            '"%~dp0.venv\\Scripts\\python.exe" "%~dp0app.py"',
            run_text,
        )
        self.assertIn(
            '"%~dp0.venv\\Scripts\\python.exe" -m pip install -r "%~dp0requirements.txt"',
            setup_text,
        )


if __name__ == "__main__":
    unittest.main()
