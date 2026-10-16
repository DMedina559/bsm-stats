"""Package the static dashboard and published data without modifying sources."""

import argparse
import json
import shutil
from pathlib import Path


def build(root: Path, output: Path) -> None:
    root = root.resolve()
    output = output.resolve()
    # Only permit a dedicated build directory inside this checkout.
    if (
        output == root
        or root not in output.parents
        or output.parts[len(root.parts)] != "dist"
    ):
        raise ValueError("Output must be inside the repository's dist/ directory")
    if not (root / "stats.json").is_file():
        raise ValueError(
            "Run update_stats.py successfully before building the dashboard"
        )
    stats = json.loads((root / "stats.json").read_text(encoding="utf-8"))
    if stats.get("schema_version") != 1:
        raise ValueError("Unsupported statistics schema")
    if output.exists():
        shutil.rmtree(output)
    shutil.copytree(root / "web", output)
    for filename in ("stats.json", "downloads.json", "history.csv"):
        shutil.copy2(root / filename, output / filename)
    for dirname in ("history", "badges"):
        shutil.copytree(root / dirname, output / dirname)
    (output / ".nojekyll").touch()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    build(args.root, args.output or args.root / "dist/site")
