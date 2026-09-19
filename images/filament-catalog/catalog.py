"""Convert the OFD bulk export into a last-known-good Spoolman catalog.

Only the Python standard library is required. The refresh command is the sole
writer; Nginx serves the generated files from a read-only mount.
"""

import argparse
import fcntl
import gzip
import hashlib
import io
import json
import logging
import math
import os
from pathlib import Path
import re
import shutil
from statistics import median
import tempfile
import time
from datetime import datetime
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from uuid import UUID


VERSION = "0.1.0"
SOURCE_URL = (
    "https://github.com/OpenFilamentCollective/open-filament-database"
    "/releases/latest/download/all.json.gz"
)
MAX_DOWNLOAD = 32 * 1024 * 1024
MAX_JSON = 128 * 1024 * 1024


def number(value, name, minimum=0, inclusive=False):
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or (value < minimum if inclusive else value <= minimum)
    ):
        raise ValueError(f"Invalid {name}: {value!r}")
    return value


def nonempty(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Missing {name}")
    return value.strip()


def index(rows):
    result = {}
    for row in rows:
        key = nonempty(row["id"], "entity ID")
        if key in result:
            raise ValueError(f"Duplicate source ID: {key}")
        result[key] = row
    return result


def temperature(filament, prefix):
    low, high = (filament.get(f"{bound}_{prefix}_temperature") for bound in ("min", "max"))
    for value in (low, high):
        if value is not None:
            number(value, "temperature", inclusive=True)
    if low is not None and high is not None:
        if low > high:
            raise ValueError(f"Reversed {prefix} temperature range")
        return math.floor((low + high) / 2 + 0.5)
    value = low if low is not None else high
    return math.floor(value + 0.5) if value is not None else None


def convert(data):
    """Join the normalized export; never use OFD's rename-sensitive generated IDs."""
    brands = index(data["brands"])
    materials = index(data["materials"])
    filaments = index(data["filaments"])
    variants = index(data["variants"])
    sizes = index(data["sizes"])
    result, seen, densities = [], set(), {}
    skipped = 0
    for size in sizes.values():
        variant = variants[size["variant_id"]]
        filament = filaments[variant["filament_id"]]
        material = materials[filament["material_id"]]
        brand = brands[filament["brand_id"]]
        if material.get("material_class", "FFF") != "FFF":
            skipped += 1
            continue
        canonical = UUID(size["uuid"])
        if canonical.version != 4:
            raise ValueError("Size UUID must be a canonical OFD UUIDv4")
        external_id = f"ofd:{canonical}"
        if external_id in seen:
            raise ValueError(f"Duplicate size UUID: {canonical}")
        seen.add(external_id)
        name = f"{nonempty(filament['name'], 'product name')} — {nonempty(variant['name'], 'color name')}"
        if size.get("spool_refill"):
            name += " (refill)"
        row = {
            "id": external_id,
            "manufacturer": nonempty(brand["name"], "brand name"),
            "name": name,
            "material": nonempty(material["material"], "material"),
            "density": number(filament.get("density"), "density"),
            "weight": number(size.get("filament_weight"), "filament weight"),
            "diameter": number(size.get("diameter"), "diameter"),
        }
        densities.setdefault(row["material"], {})[filament["id"]] = row["density"]
        if size.get("empty_spool_weight") is not None:
            row["spool_weight"] = number(size["empty_spool_weight"], "empty spool weight", inclusive=True)
        for target, source in (("extruder_temp", "print"), ("bed_temp", "bed")):
            value = temperature(filament, source)
            if value is not None:
                row[target] = value
        colors = variant["color_hex"]
        colors = colors if isinstance(colors, list) else [colors]
        if not colors or any(not isinstance(c, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", c) for c in colors):
            raise ValueError(f"Invalid colors for {external_id}: {colors!r}")
        colors = [color[1:].lower() for color in colors]
        if len(colors) == 1:
            row["color_hex"] = colors[0]
        else:
            row["color_hexes"] = colors
        traits = variant.get("traits", {})
        row["translucent"] = bool(traits.get("translucent") or traits.get("transparent"))
        row["glow"] = bool(traits.get("glow"))
        if traits.get("matte"):
            row["finish"] = "matte"
        if traits.get("imitates_marble"):
            row["pattern"] = "marble"
        elif traits.get("glitter"):
            row["pattern"] = "sparkle"
        if traits.get("coextruded"):
            row["multi_color_direction"] = "coaxial"
        elif traits.get("gradual_color_change"):
            row["multi_color_direction"] = "longitudinal"
        result.append(row)
    generic = [
        {"material": material, "density": median(values.values())}
        for material, values in sorted(densities.items())
    ]
    return sorted(result, key=lambda row: row["id"]), generic, skipped


def read_limited(stream, limit):
    data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError(f"Source exceeds {limit} byte limit")
    return data


def download(url):
    if urlsplit(url).scheme != "https":
        raise ValueError("Source URL must use HTTPS")
    request = Request(url, headers={"User-Agent": f"spoolman-filament-catalog/{VERSION}"})
    with urlopen(request, timeout=90) as response:
        if urlsplit(response.url).scheme != "https":
            raise ValueError("Source redirected away from HTTPS")
        raw = read_limited(response, MAX_DOWNLOAD)
    if raw.startswith(b"\x1f\x8b"):
        with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
            raw = read_limited(stream, MAX_JSON)
    return raw


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n").encode()


def load_current(root):
    """Verify both files, including their hashes, before accepting an existing cache."""
    generation = (root / "current").resolve(strict=True)
    metadata = json.loads((generation / "metadata.json").read_bytes())
    for filename, expected in metadata["sha256"].items():
        if hashlib.sha256((generation / filename).read_bytes()).hexdigest() != expected:
            raise ValueError(f"Corrupt catalog: {filename}")
    if set(metadata["sha256"]) != {"filaments.json", "materials.json"}:
        raise ValueError("Incomplete catalog metadata")
    return generation, metadata


def timestamp(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Source timestamp must include a timezone")
    return parsed.timestamp()


def publish(root, raw, source_url, min_records=1000, max_drop=0.2):
    """Caller holds the writer lock. Failed validation never changes current."""
    root = root.resolve()
    data = json.loads(raw)
    source_time = timestamp(data["generated_at"])
    rows, materials, skipped = convert(data)
    if len(rows) < min_records:
        raise ValueError(f"Only {len(rows)} filaments; minimum is {min_records}")
    old_generation = None
    if (root / "current").is_symlink():
        old_generation, previous = load_current(root)
        if source_time < previous["source_generated_timestamp_seconds"]:
            raise ValueError("Refusing an older source snapshot")
        old_rows = json.loads((old_generation / "filaments.json").read_bytes())
        old_ids = {row["id"] for row in old_rows}
        new_ids = {row["id"] for row in rows}
        removed = len(old_ids - new_ids) / len(old_ids) if old_ids else 0
        if removed > max_drop:
            raise ValueError(f"Refusing removal of {removed:.1%} of existing IDs (limit {max_drop:.1%})")
    payloads = {"filaments.json": json_bytes(rows), "materials.json": json_bytes(materials)}
    metadata = {
        "converter_version": VERSION,
        "source_url": source_url,
        "source_version": nonempty(data["version"], "source version"),
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "source_generated_at": data["generated_at"],
        "source_generated_timestamp_seconds": source_time,
        "last_success_timestamp_seconds": time.time(),
        "filament_count": len(rows),
        "material_count": len(materials),
        "skipped_non_fff_sizes": skipped,
        "sha256": {name: hashlib.sha256(value).hexdigest() for name, value in payloads.items()},
    }
    payloads["metadata.json"] = json_bytes(metadata)
    generation = Path(tempfile.mkdtemp(prefix="generation-", dir=root))
    generation.chmod(0o755)
    try:
        for name, value in payloads.items():
            with (generation / name).open("wb") as stream:
                stream.write(value)
                stream.flush()
                os.fsync(stream.fileno())
        next_link = root / ".next"
        next_link.unlink(missing_ok=True)
        next_link.symlink_to(generation.name)
        os.replace(next_link, root / "current")
    except BaseException:
        # After publication the new generation must remain available.
        if (root / "current").resolve() != generation:
            shutil.rmtree(generation)
        raise
    # Retain the previous successful generation; also clear interrupted staging runs.
    for candidate in root.glob("generation-*"):
        if candidate not in (generation, old_generation):
            shutil.rmtree(candidate)
    logging.info("Published %s", json.dumps(metadata, sort_keys=True))
    return metadata


def refresh(args):
    root = args.data_dir
    root.mkdir(parents=True, exist_ok=True)
    # CronJobs may run more than once; the init container is also a writer.
    with (root / ".refresh.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if args.if_missing:
            try:
                load_current(root)
            except FileNotFoundError:
                pass
            else:
                logging.info("Existing catalog verified; skipping bootstrap")
                return
        raw = args.input.read_bytes() if args.input else download(args.source_url)
        publish(root, raw, args.source_url, args.min_records, args.max_drop)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("refresh",))
    parser.add_argument("--data-dir", type=Path, default=Path(os.getenv("CATALOG_DATA_DIR", "/data")))
    parser.add_argument("--source-url", default=os.getenv("OFD_SOURCE_URL", SOURCE_URL))
    parser.add_argument("--input", type=Path, help="Use a local bulk JSON snapshot for offline validation")
    parser.add_argument("--if-missing", action="store_true")
    parser.add_argument("--min-records", type=int, default=int(os.getenv("CATALOG_MIN_RECORDS", "1000")))
    parser.add_argument("--max-drop", type=float, default=float(os.getenv("CATALOG_MAX_DROP", "0.2")))
    args = parser.parse_args()
    if args.min_records < 1 or not 0 <= args.max_drop <= 1:
        parser.error("min-records must be positive and max-drop must be between 0 and 1")
    refresh(args)


if __name__ == "__main__":
    main()
