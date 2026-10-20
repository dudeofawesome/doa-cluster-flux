"""Startup contract tests; run with the pinned image's wyoming_parakeet package."""

import asyncio
import ctypes
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

import run


class Function:
    def __init__(self, implementation):
        self.implementation = implementation

    def __call__(self, *args):
        return self.implementation(*args)


class NativeLibrary:
    """Exercise the real upstream refcount and handler with a fake native ABI."""

    def __init__(self):
        self.loads = 0
        self.frees = 0
        self.feeds = 0
        self.text = ctypes.create_string_buffer(b"")
        self.parakeet_capi_load = Function(self.load)
        self.parakeet_capi_free = Function(self.free)
        self.parakeet_capi_stream_feed = Function(self.feed)
        self.parakeet_capi_stream_begin_lang = Function(lambda *args: 2)
        self.parakeet_capi_stream_finalize = Function(
            lambda *args: ctypes.addressof(self.text)
        )
        for name in ["stream_free", "free_string", "transcribe_pcm_lang", "last_error"]:
            setattr(self, f"parakeet_capi_{name}", Function(lambda *args: None))

    def load(self, path):
        self.loads += 1
        return 1

    def free(self, context):
        self.frees += 1

    def feed(self, *args):
        self.feeds += 1
        return ctypes.addressof(self.text)


class StartupTests(unittest.TestCase):
    def test_download_once_and_reuse_cached_model(self):
        from wyoming_parakeet import download

        with tempfile.TemporaryDirectory() as directory:
            model = Path(directory) / "realtime_eou_120m-v1-f16.gguf"
            arguments = [
                "run.py", "--model", model.stem, "--data-dir", directory,
                "--device", "cpu", "--uri", "tcp://0.0.0.0:10300",
            ]

            def fetch(name, destination):
                self.assertEqual(name, model.stem)
                self.assertEqual(destination, directory)
                model.write_bytes(b"downloaded model")

            with patch.object(download, "download_model", side_effect=fetch) as fetch_model, patch.object(
                run, "serve", new_callable=AsyncMock
            ) as serve, patch.object(run.sys, "argv", arguments):
                run.main()
                run.main()
                fetch_model.assert_called_once()
                self.assertEqual(serve.await_count, 2)
                serve.assert_awaited_with(model)
                self.assertEqual(run.sys.argv, arguments)

    def test_loaded_model_survives_client_disconnects(self):
        from argparse import Namespace
        import numpy as np
        from wyoming.info import Info
        from wyoming.audio import AudioChunk, AudioStop
        from wyoming_parakeet import __main__ as server
        from wyoming_parakeet.streaming_handler import ParakeetEventHandler
        from wyoming_parakeet import utils

        native = NativeLibrary()
        config = {"model": "realtime_eou_120m-v1-f16", "language": "en"}
        with tempfile.TemporaryDirectory() as directory:
            model = Path(directory) / f'{config["model"]}.gguf'
            model.write_bytes(b"fake model")

            async def accept_connections():
                # The model is loaded before the server accepts connections.
                self.assertEqual(native.loads, 1)
                self.assertEqual(native.feeds, 0)
                self.assertEqual(native.frees, 0)
                for index in range(2):
                    handler = ParakeetEventHandler(
                        Info(), Namespace(**config, device="cpu"), model, None, None
                    )
                    handler.write_event = AsyncMock()
                    chunk = AudioChunk(
                        rate=16000, width=2, channels=1,
                        audio=np.zeros(2560, dtype=np.int16).tobytes(),
                    )
                    await handler.handle_event(chunk.event())
                    # Audio reaches inference before the end-of-audio event.
                    self.assertEqual(native.feeds, index + 1)
                    handler.write_event.assert_not_awaited()
                    await handler.handle_event(AudioStop().event())
                    self.assertEqual(
                        handler.write_event.await_args.args[0].type, "transcript"
                    )
                    await handler.__aexit__(None, None, None)
                    self.assertEqual(native.loads, 1)
                    self.assertEqual(native.frees, 0)

            with patch.object(ctypes, "CDLL", return_value=native), patch.object(
                server, "main", accept_connections
            ), patch.object(run.sys, "argv", []):
                asyncio.run(run.serve(model))
        self.assertEqual(native.frees, 1)
        self.assertIsNone(utils._SHARED_CONTEXT)


if __name__ == "__main__":
    unittest.main()
