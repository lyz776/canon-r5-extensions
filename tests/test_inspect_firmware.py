import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import inspect_firmware as inspector


class InspectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.input = self.root / "R5_1.5.2.FIR"
        self.input.write_bytes(b"abc")

    def cli(self, *args):
        output, errors = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            code = inspector.main([str(arg) for arg in args])
        return code, output.getvalue(), errors.getvalue()

    def assert_unverified(self, report):
        for key in ("firmware_format", "camera_model", "firmware_version", "camera_compatibility"):
            self.assertEqual(report[key], "unverified")
        self.assertIs(report["safe_to_flash"], False)

    def test_known_sha256_vector(self):
        report = inspector.inspect_file(self.input)
        self.assertEqual(report["sha256"], "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")
        self.assertEqual(report["size_bytes"], 3)
        self.assertIsNone(report["hash_match"])
        self.assert_unverified(report)

    def test_success_exit_does_not_approve_matching_file(self):
        expected = hashlib.sha256(b"abc").hexdigest().upper()
        code, output, errors = self.cli(self.input, "--expect-sha256", expected)
        report = json.loads(output)
        self.assertEqual(code, 0)
        self.assertEqual(errors, "")
        self.assertIs(report["hash_match"], True)
        self.assertEqual(report["expected_sha256"], expected.lower())
        self.assert_unverified(report)

    def test_hash_mismatch_returns_nonzero_with_report(self):
        code, output, errors = self.cli(self.input, "--expect-sha256", "0" * 64)
        self.assertEqual(code, 1)
        self.assertEqual(errors, "")
        report = json.loads(output)
        self.assertIs(report["hash_match"], False)
        self.assert_unverified(report)

    def test_invalid_hash_rejected_before_file_access(self):
        for value in ("", "0" * 63, "0" * 65, "z" * 64, " " + "0" * 64, "0" * 64 + "\n"):
            with self.subTest(value=value), patch.object(Path, "stat", side_effect=AssertionError("unexpected read")):
                code, output, errors = self.cli(self.input, "--expect-sha256", value)
                self.assertEqual(code, 2)
                self.assertEqual(output, "")
                self.assertIn("64 hexadecimal", errors)

    def test_empty_missing_and_directory_inputs_fail_without_report(self):
        empty = self.root / "empty.FIR"
        empty.touch()
        for path in (empty, self.root / "missing.FIR", self.root):
            with self.subTest(path=path):
                code, output, errors = self.cli(path)
                self.assertEqual(code, 2)
                self.assertEqual(output, "")
                self.assertIn("error:", errors)

    def test_device_input_rejected(self):
        code, output, errors = self.cli(os.devnull)
        self.assertEqual(code, 2)
        self.assertEqual(output, "")
        self.assertIn("error:", errors)

    def test_unreadable_input_fails_without_report(self):
        with patch.object(Path, "open", side_effect=PermissionError("access denied")):
            code, output, errors = self.cli(self.input)
        self.assertEqual(code, 2)
        self.assertEqual(output, "")
        self.assertIn("access denied", errors)

    def test_multiblock_input_bytes_and_mtime_preserved(self):
        payload = bytes(range(256)) * (inspector.CHUNK_SIZE // 128 + 17)
        self.input.write_bytes(payload)
        before = self.input.stat()
        report = inspector.inspect_file(self.input)
        after = self.input.stat()
        self.assertEqual(report["sha256"], hashlib.sha256(payload).hexdigest())
        self.assertEqual(report["size_bytes"], len(payload))
        self.assertEqual(self.input.read_bytes(), payload)
        self.assertEqual(before.st_mtime_ns, after.st_mtime_ns)

    def test_name_header_and_truncation_cannot_prove_firmware_identity(self):
        for payload in (b"\x00", b"Canon EOS R5 Firmware Version 1.5.2", b"\xff" * 31):
            with self.subTest(payload=payload):
                self.input.write_bytes(payload)
                self.assert_unverified(inspector.inspect_file(self.input))

    def test_unicode_filename_real_cli_and_no_created_files(self):
        path = self.root / "固件 副本.data"
        path.write_bytes(b"abc")
        before = sorted(self.root.iterdir())
        process = subprocess.run(
            [sys.executable, "-B", str(Path(inspector.__file__).resolve()), str(path)],
            cwd=self.root, capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assert_unverified(json.loads(process.stdout))
        self.assertEqual(sorted(self.root.iterdir()), before)

    def test_read_error_does_not_emit_partial_fingerprint(self):
        original_open = Path.open

        def failing_open(path, *args, **kwargs):
            source = original_open(path, *args, **kwargs)
            wrapper = unittest.mock.MagicMock(wraps=source)
            wrapper.__enter__.return_value = wrapper
            wrapper.__exit__.side_effect = source.__exit__
            wrapper.read.side_effect = OSError("simulated I/O failure")
            return wrapper

        with patch.object(Path, "open", failing_open):
            code, output, errors = self.cli(self.input)
        self.assertEqual(code, 2)
        self.assertEqual(output, "")
        self.assertIn("I/O failure", errors)

    def test_detects_file_change_during_read(self):
        original_open = Path.open
        for mutation in ("truncate", "append", "rewrite"):
            with self.subTest(mutation=mutation):
                self.input.write_bytes(b"a" * (inspector.CHUNK_SIZE + 8))
                before = self.input.stat()
                changes = []

                def changing_open(path, *args, **kwargs):
                    source = original_open(path, *args, **kwargs)
                    wrapper = unittest.mock.MagicMock(wraps=source)
                    wrapper.__enter__.return_value = wrapper
                    wrapper.__exit__.side_effect = source.__exit__
                    changed = False

                    def read(size):
                        nonlocal changed
                        data = source.read(size)
                        if not changed:
                            changed = True
                            changes.append(mutation)
                            with original_open(path, "r+b") as writer:
                                if mutation == "truncate":
                                    writer.truncate(1)
                                elif mutation == "append":
                                    writer.seek(0, 2)
                                    writer.write(b"b")
                                else:
                                    writer.write(b"b")
                            # Make the metadata change deterministic on coarse filesystems.
                            os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns + 2_000_000_000))
                        return data

                    wrapper.read.side_effect = read
                    return wrapper

                with patch.object(Path, "open", changing_open):
                    code, output, errors = self.cli(self.input)
                self.assertEqual(code, 2)
                self.assertEqual(output, "")
                self.assertIn("error:", errors)
                self.assertEqual(changes, [mutation])


if __name__ == "__main__":
    unittest.main()
