"""Check decoder processes without connecting to the single-client SDR socket."""

from pathlib import Path
import sys

running = set()
for path in Path('/proc').glob('[0-9]*/cmdline'):
    try:
        command = path.read_bytes().split(b'\0', 1)[0].decode()
        running.add(Path(command).name)
    except (OSError, UnicodeDecodeError):
        # Processes can exit while /proc is being inspected.
        continue

sys.exit(0 if {'rtl_tcp', 'rtlamr'} <= running else 1)
