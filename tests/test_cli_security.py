import io
import unittest
from contextlib import redirect_stderr

import cli


class CliSecurityTests(unittest.TestCase):
    def test_file_error_does_not_echo_path_or_exception_body(self):
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            code = cli.main(["--csv", "PRIVATE_MARKER_DO_NOT_ECHO.csv", "--demo"])
        self.assertEqual(2, code)
        self.assertIn("Ошибка:", stderr.getvalue())
        self.assertNotIn("PRIVATE_MARKER_DO_NOT_ECHO", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
