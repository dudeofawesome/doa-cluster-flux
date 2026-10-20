"""Keep the upstream Wyoming model loaded between client connections."""

import argparse
import asyncio
from pathlib import Path
import sys

# Preserve the pinned image's package layout when bypassing start.sh.
sys.path.insert(0, "/wd")


async def serve(model_path):
    from wyoming_parakeet import __main__ as server
    from wyoming_parakeet.utils import _SharedModel

    # Hold an extra reference across HA connections; upstream releases the
    # model when its last client disconnects. Load before opening the listener.
    retained_model = _SharedModel(model_path)
    retained_model.acquire()
    try:
        # Let upstream parse the Deployment's original command-line arguments.
        await server.main()
    finally:
        retained_model.release()


def main():
    from wyoming_parakeet.download import download_model

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--model", required=True)
    parser.add_argument("--data-dir", required=True)
    args, _ = parser.parse_known_args()
    model_path = Path(args.data_dir) / f"{args.model}.gguf"
    if not model_path.is_file():
        download_model(args.model, args.data_dir)
    asyncio.run(serve(model_path))


if __name__ == "__main__":
    main()
