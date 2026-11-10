from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class InstallScriptTests(unittest.TestCase):
    def test_incomplete_virtualenv_is_recreated_inside_the_project(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            app_dir = temporary_path / "project"
            fake_bin = temporary_path / "bin"
            home = temporary_path / "home"
            data_home = temporary_path / "data"
            app_dir.mkdir()
            fake_bin.mkdir()
            home.mkdir()
            shutil.copy(ROOT / "install.sh", app_dir / "install.sh")
            (app_dir / "launchers").mkdir()
            (app_dir / "launchers" / "nova.desktop.in").write_text(
                "[Desktop Entry]\nExec=@APP_DIR@/launchers/run-nova.sh\n",
                encoding="utf-8",
            )
            (app_dir / "requirements.txt").write_text("", encoding="utf-8")
            incomplete_venv = app_dir / ".venv"
            incomplete_venv.mkdir()
            (incomplete_venv / "partial-install").write_text("stale", encoding="utf-8")

            call_log = temporary_path / "calls.log"
            fake_python = fake_bin / "python3"
            fake_python.write_text(
                "#!/bin/sh\n"
                "if [ \"$1\" = \"-m\" ] && [ \"$2\" = \"venv\" ] && "
                "[ \"$3\" != \"--help\" ]; then\n"
                "  mkdir -p \"$3/bin\"\n"
                "  cat > \"$3/bin/python\" <<'PYTHON'\n"
                "#!/bin/sh\n"
                "printf 'venv %s\\n' \"$*\" >> \"$CALL_LOG\"\n"
                "exit 0\n"
                "PYTHON\n"
                "  chmod +x \"$3/bin/python\"\n"
                "  printf 'home = /usr/bin\\n' > \"$3/pyvenv.cfg\"\n"
                "fi\n"
                "printf 'system %s\\n' \"$*\" >> \"$CALL_LOG\"\n"
                "exit 0\n",
                encoding="utf-8",
            )
            fake_python.chmod(0o755)
            environment = os.environ.copy()
            environment.update({
                "CALL_LOG": str(call_log),
                "HOME": str(home),
                "PATH": f"{fake_bin}:/usr/bin:/bin",
                "XDG_DATA_HOME": str(data_home),
            })

            result = subprocess.run(
                ["/bin/sh", str(app_dir / "install.sh"), "--yes"],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse((incomplete_venv / "partial-install").exists())
            self.assertTrue((incomplete_venv / "bin" / "python").is_file())
            self.assertTrue((incomplete_venv / "pyvenv.cfg").is_file())
            self.assertTrue((data_home / "applications" / "nova.desktop").is_file())

    def test_missing_python_prints_manual_apt_commands_on_mint_based_systems(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            app_dir = temporary_path / "project"
            fake_bin = temporary_path / "bin"
            app_dir.mkdir()
            fake_bin.mkdir()
            script = app_dir / "install.sh"
            shutil.copy(ROOT / "install.sh", script)
            for command, executable in (("dirname", "/usr/bin/dirname"), ("grep", "/usr/bin/grep")):
                wrapper = fake_bin / command
                wrapper.write_text(
                    f"#!/bin/sh\nexec {executable} \"$@\"\n",
                    encoding="utf-8",
                )
                wrapper.chmod(0o755)

            environment = os.environ.copy()
            environment["PATH"] = str(fake_bin)
            result = subprocess.run(
                ["/bin/sh", str(script)],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("sudo apt update", result.stderr)
        self.assertIn("sudo apt install python3 python3-venv python3-tk", result.stderr)

    def test_graphical_launcher_prints_manual_commands_when_python_is_missing(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            app_dir = temporary_path / "project"
            launchers = app_dir / "launchers"
            fake_bin = temporary_path / "bin"
            launchers.mkdir(parents=True)
            fake_bin.mkdir()
            shutil.copy(ROOT / "launchers" / "run-nova.sh", launchers / "run-nova.sh")
            for command, executable in (("dirname", "/usr/bin/dirname"), ("grep", "/usr/bin/grep")):
                wrapper = fake_bin / command
                wrapper.write_text(
                    f"#!/bin/sh\nexec {executable} \"$@\"\n",
                    encoding="utf-8",
                )
                wrapper.chmod(0o755)

            environment = os.environ.copy()
            environment["PATH"] = str(fake_bin)
            result = subprocess.run(
                ["/bin/sh", str(launchers / "run-nova.sh")],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("sudo apt update", result.stderr)
        self.assertIn("python3 python3-venv python3-tk", result.stderr)
        self.assertIn("não executa comandos administrativos", result.stderr)

    def test_virtualenv_symlink_is_rejected_before_marker_or_external_access(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            app_dir = temporary_path / "project"
            outside_dir = temporary_path / "outside"
            fake_bin = temporary_path / "bin"
            home = temporary_path / "home"
            app_dir.mkdir()
            outside_dir.mkdir()
            fake_bin.mkdir()
            home.mkdir()

            shutil.copy(ROOT / "install.sh", app_dir / "install.sh")
            (app_dir / "launchers").mkdir()
            (app_dir / "launchers" / "nova.desktop.in").write_text(
                "[Desktop Entry]\nExec=@APP_DIR@/launchers/run-nova.sh\n",
                encoding="utf-8",
            )
            (app_dir / "requirements.txt").write_text("", encoding="utf-8")

            virtualenv = outside_dir / "virtualenv"
            (virtualenv / "bin").mkdir(parents=True)
            marker = virtualenv / ".nova-desktop-file-path"
            marker.write_text("/outside/launcher.desktop\n", encoding="utf-8")
            (virtualenv / "pyvenv.cfg").write_text("home = /usr/bin\n", encoding="utf-8")
            call_log = temporary_path / "external-calls.log"
            fake_python = fake_bin / "python3"
            fake_python.write_text(
                "#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$CALL_LOG\"\nexit 0\n",
                encoding="utf-8",
            )
            fake_python.chmod(0o755)
            venv_python = virtualenv / "bin" / "python"
            venv_python.write_text(
                "#!/bin/sh\nprintf 'venv %s\\n' \"$*\" >> \"$CALL_LOG\"\nexit 0\n",
                encoding="utf-8",
            )
            venv_python.chmod(0o755)
            (app_dir / ".venv").symlink_to(virtualenv, target_is_directory=True)

            environment = os.environ.copy()
            environment.update({
                "CALL_LOG": str(call_log),
                "HOME": str(home),
                "PATH": f"{fake_bin}:/usr/bin:/bin",
                "XDG_DATA_HOME": str(temporary_path / "data"),
            })
            result = subprocess.run(
                ["/bin/sh", "-x", str(app_dir / "install.sh"), "--yes"],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("link simbólico", result.stderr)
            self.assertNotIn(".nova-desktop-file-path", result.stderr)
            self.assertFalse(call_log.exists())
            self.assertTrue((app_dir / ".venv").is_symlink())
            self.assertEqual(marker.read_text(encoding="utf-8"), "/outside/launcher.desktop\n")
            self.assertFalse((temporary_path / "data").exists())


if __name__ == "__main__":
    unittest.main()
