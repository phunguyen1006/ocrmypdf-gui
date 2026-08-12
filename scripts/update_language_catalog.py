"""Generate the bundled Tesseract language catalogue.

This is a maintainer tool, not a runtime network dependency. It snapshots the
official tessdata_fast tree and the Tesseract documentation's language names
into app/data/tesseract_languages.json.
"""
from __future__ import annotations

import argparse
import base64
import json
import re
import urllib.request
from pathlib import Path


REPOSITORY = "tesseract-ocr/tessdata_fast"
DOC_REPOSITORY = "tesseract-ocr/tessdoc"
DEFAULT_COMMIT = "87416418657359cb625c412a48b6e1d6d41c29bd"
LANGUAGE_ROW = re.compile(r"^\s*([A-Za-z0-9_]+)\s*\|\s*([^|]+?)\s*\|")


def fetch_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": "ocrmypdf-gui-catalog-generator"})
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 - pinned HTTPS source
        return json.loads(response.read().decode("utf-8"))


def fetch_text(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "ocrmypdf-gui-catalog-generator"})
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 - pinned HTTPS source
        return response.read().decode("utf-8")


def parse_language_names(markdown: str) -> dict[str, str]:
    names: dict[str, str] = {}
    for line in markdown.splitlines():
        match = LANGUAGE_ROW.match(line)
        if match:
            names[match.group(1)] = " ".join(match.group(2).split())
    return names


def script_name(code: str) -> str:
    return code.replace("_vert", " (vertical)") + " script"


def build_catalog(commit: str) -> dict:
    tree_url = f"https://api.github.com/repos/{REPOSITORY}/git/trees/{commit}?recursive=1"
    tree = fetch_json(tree_url).get("tree", [])
    docs_url = f"https://api.github.com/repos/{DOC_REPOSITORY}/contents/Data-Files.md"
    encoded = fetch_json(docs_url).get("content", "")
    names = parse_language_names(base64.b64decode(encoded).decode("utf-8")) if encoded else {}

    models = []
    for item in tree:
        path = str(item.get("path", ""))
        if not path.endswith(".traineddata"):
            continue
        relative = path[:-len(".traineddata")]
        if path.startswith("script/"):
            code = relative
            name = script_name(Path(relative).name)
            kind = "script"
            script = Path(relative).name.replace("_vert", "")
        else:
            code = relative
            name = names.get(code, code)
            kind = "language"
            script = ""
        models.append(
            {
                "code": code,
                "name": name,
                "kind": kind,
                "script": script,
                "remote_path": path,
                "size_bytes": int(item.get("size", 0) or 0),
                "checksum": item.get("sha", ""),
                "checksum_type": "git-blob-sha1",
            }
        )
    models.sort(key=lambda model: (model["kind"], model["name"].casefold(), model["code"]))
    return {
        "source": {
            "repository": f"https://github.com/{REPOSITORY}",
            "raw_base": f"https://raw.githubusercontent.com/{REPOSITORY}/{commit}",
            "commit": commit,
            "license": "Apache-2.0",
        },
        "models": models,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--commit", default=DEFAULT_COMMIT)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "app" / "data" / "tesseract_languages.json",
    )
    args = parser.parse_args()
    catalog = build_catalog(args.commit)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    counts = {}
    for model in catalog["models"]:
        counts[model["kind"]] = counts.get(model["kind"], 0) + 1
    print(f"Wrote {len(catalog['models'])} models ({counts}) to {args.output}")


if __name__ == "__main__":
    main()
