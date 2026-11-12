import ast
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import desktop_pet


class DesktopStartupTests(unittest.TestCase):
    def test_main_block_resolves_path_without_creating_the_pet_ui(self):
        tree = ast.parse((SRC / "desktop_pet.py").read_text(encoding="utf-8"))
        main_block = next(
            node for node in tree.body
            if isinstance(node, ast.If)
            and isinstance(node.test, ast.Compare)
            and isinstance(node.test.left, ast.Name)
            and node.test.left.id == "__name__"
        )
        namespace = dict(desktop_pet.__dict__)
        namespace["__name__"] = "__main__"
        pet_class = mock.Mock()
        namespace["DesktopPet"] = pet_class
        first_access = mock.Mock(return_value=True)
        namespace["run_first_access_if_needed"] = first_access
        with tempfile.TemporaryDirectory() as tmpdir, \
             mock.patch.object(Path, "home", return_value=Path(tmpdir)), \
             mock.patch.object(desktop_pet.logging, "basicConfig"), \
             mock.patch.object(desktop_pet.logging, "FileHandler"):
            exec(compile(ast.Module(body=[main_block], type_ignores=[]), str(SRC / "desktop_pet.py"), "exec"), namespace)
        pet_class.return_value.run.assert_called_once()
        first_access.assert_called_once()
    def test_maintenance_subprocesses_use_the_filtered_environment(self):
        tree = ast.parse((SRC / "preferences_computer_ui.py").read_text(encoding="utf-8"))
        functions = {
            node.name: node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        maintenance_calls = [
            node for node in ast.walk(functions["run_maintenance"])
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "run_streaming_command"
        ]
        self.assertEqual(len(maintenance_calls), 1)
        streaming_env = next(
            keyword.value for keyword in maintenance_calls[0].keywords
            if keyword.arg == "env"
        )
        self.assertTrue(any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "_child_process_env"
            for node in ast.walk(streaming_env)
        ))

        autoremove_calls = [
            node for node in ast.walk(functions["preview_autoremove"])
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "subprocess"
            and node.func.attr == "run"
        ]
        self.assertEqual(len(autoremove_calls), 1)
        env_arg = next(
            keyword.value for keyword in autoremove_calls[0].keywords
            if keyword.arg == "env"
        )
        self.assertIsInstance(env_arg, ast.Call)
        self.assertIsInstance(env_arg.func, ast.Attribute)
        self.assertEqual(env_arg.func.attr, "_child_process_env")
    def test_missing_pillow_or_opencv_shows_installer_hint_without_traceback(self):
        script = '''
import builtins, runpy, sys
sys.path.insert(0, sys.argv[1])
missing = sys.argv[2]
original_import = builtins.__import__
def import_without_dependency(name, *args, **kwargs):
    if name == missing:
        raise ModuleNotFoundError(f"No module named '{missing}'", name=missing)
    return original_import(name, *args, **kwargs)
builtins.__import__ = import_without_dependency
try:
    runpy.run_path(sys.argv[3], run_name="__main__")
except SystemExit as exc:
    raise SystemExit(exc.code)
'''
        for missing, label in (("cv2", "OpenCV"), ("PIL", "Pillow"), ("numpy", "NumPy")):
            with self.subTest(dependency=label):
                result = desktop_pet.subprocess.run(
                    [sys.executable, "-c", script, str(SRC), missing, str(SRC / "desktop_pet.py")],
                    capture_output=True, text=True, check=False,
                )
                self.assertEqual(result.returncode, 1)
                self.assertIn(label, result.stderr)
                self.assertIn("./install.sh", result.stderr)
                self.assertNotIn("Traceback", result.stderr)

    def test_child_process_env_filters_common_secrets(self):
        with mock.patch.dict(
            desktop_pet.os.environ,
            {
                "PATH": "/usr/bin",
                "SERVICE_API_KEY": "secret",
                "SERVICE_TOKEN": "token-value",
                "HOME": "/tmp",
                "DISPLAY": ":0",
            },
            clear=True,
        ):
            env = desktop_pet.DesktopPet._child_process_env()
            self.assertEqual(env["PATH"], "/usr/bin")
            self.assertEqual(env["HOME"], "/tmp")
            self.assertEqual(env["DISPLAY"], ":0")
            self.assertNotIn("SERVICE_API_KEY", env)
            self.assertNotIn("SERVICE_TOKEN", env)
