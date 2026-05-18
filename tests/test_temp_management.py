import tempfile
import threading
import unittest
from pathlib import Path

import app


class TempManagementTests(unittest.TestCase):
    def test_page_temp_dir_uses_system_temp(self):
        output_dir = Path(tempfile.mkdtemp(prefix="auto_ocr_output_", dir="/private/tmp"))
        temp_dir = app.make_page_temp_dir()
        try:
            self.assertNotEqual(temp_dir.parent.resolve(), output_dir.resolve())
            self.assertEqual(temp_dir.parent.resolve(), Path(tempfile.gettempdir()).resolve())
        finally:
            app.cleanup_temp_tree(temp_dir, lambda _: None, attempts=1, delay_seconds=0)
            output_dir.rmdir()

    def test_cleanup_temp_tree_removes_files_and_directory(self):
        temp_dir = app.make_page_temp_dir()
        (temp_dir / "page_00001.pdf").write_bytes(b"pdf")
        (temp_dir / "page_00001.png").write_bytes(b"png")

        removed = app.cleanup_temp_tree(temp_dir, lambda _: None, attempts=1, delay_seconds=0)

        self.assertTrue(removed)
        self.assertFalse(temp_dir.exists())

    def test_close_waits_for_worker_before_destroying_window(self):
        class RootStub:
            def __init__(self):
                self.destroyed = False
                self.quit_called = False
                self.after_calls = []

            def after_cancel(self, _after_id):
                pass

            def after(self, delay_ms, callback):
                self.after_calls.append((delay_ms, callback))
                return "after-close"

            def destroy(self):
                self.destroyed = True

            def quit(self):
                self.quit_called = True

        class AliveWorkerStub:
            def is_alive(self):
                return True

        app_instance = app.AutoOCRApp.__new__(app.AutoOCRApp)
        app_instance.root = RootStub()
        app_instance.worker_thread = AliveWorkerStub()
        app_instance.active_worker_threads = {app_instance.worker_thread}
        app_instance.cancel_event = threading.Event()
        app_instance.closing = False
        app_instance.after_ids = set()

        app.AutoOCRApp.close_app(app_instance)

        self.assertTrue(app_instance.cancel_event.is_set())
        self.assertFalse(app_instance.root.destroyed)
        self.assertEqual(len(app_instance.root.after_calls), 1)


if __name__ == "__main__":
    unittest.main()
