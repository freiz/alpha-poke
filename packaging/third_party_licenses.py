"""THIRD_PARTY_LICENSES.txt for the desktop app's zip: the license texts of what is frozen into it.
The Python packages by pip-licenses, the Rust crates compiled into our two extensions by cargo
metadata (their normal dependencies on this platform, each crate's own license files).

  uv run --no-sync python packaging/third_party_licenses.py dist/alpha-poke-review/THIRD_PARTY_LICENSES.txt
"""

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUST = ("rust/alpha_search/Cargo.toml", "rust/patches/poke-engine-py-0.0.48/binding/Cargo.toml")
OURS = {"alpha-poke", "alpha-search", "alpha_search"}
# (poke-engine's binding, Python package and crate: its license is the poke-engine crate's)
BINDING_PY, BINDING_CRATE = "poke-engine", "poke_engine"
# (build tools in the environment, not frozen into the app)
BUILD_ONLY = ("pyinstaller", "pyinstaller-hooks-contrib", "altgraph", "pefile", "macholib",
              "pywin32-ctypes", "pip-licenses", "prettytable", "wcwidth", "tomli")  # fmt: skip
LICENSE_FILE = re.compile(r"(?i)^(licen[cs]e|copying|notice)")
HEADER = """Third-party software in this app.

alpha-poke's own code: MIT (LICENSE, beside this file). The model files in _internal/assets are
for non-commercial research use (README.txt). Python itself is under the PSF license
(https://docs.python.org/3/license.html); the launcher is PyInstaller's bootloader (GPL-2.0 with
an exception that puts no terms on the frozen program). Showdown's client (AGPL-3.0) is not in
this zip: the app downloads it unmodified from play.pokemonshowdown.com on first use.
"""


def section(name: str, license_id: str, url: str, text: str) -> str:
    return f"\n{'=' * 78}\n{name} -- {license_id}\n{url}\n{'=' * 78}\n\n{text.strip()}\n"


def python_packages() -> list[str]:
    out = subprocess.run(
        [sys.executable, "-m", "piplicenses", "--format=json", "--with-license-file",
         "--no-license-path", "--with-urls", "--ignore-packages", *OURS, BINDING_PY, *BUILD_ONLY],
        capture_output=True, text=True, encoding="utf-8", check=True,
    ).stdout  # fmt: skip
    rows = sorted(json.loads(out), key=lambda r: r["Name"].lower())
    return [section(f"{r['Name']} {r['Version']}", r["License"], r["URL"], r["LicenseText"])
            for r in rows]  # fmt: skip


def rust_crates() -> list[str]:
    host = subprocess.run(["rustc", "-vV"], capture_output=True, text=True, check=True).stdout
    host = re.search(r"host: (\S+)", host).group(1)
    found = {}
    for manifest in RUST:
        meta = json.loads(subprocess.run(
            ["cargo", "metadata", "--format-version", "1", "--filter-platform", host,
             "--manifest-path", str(ROOT / manifest)],
            capture_output=True, text=True, encoding="utf-8", check=True,
        ).stdout)  # fmt: skip
        packages = {p["id"]: p for p in meta["packages"]}
        nodes = {n["id"]: n for n in meta["resolve"]["nodes"]}
        todo = [meta["resolve"]["root"]]
        seen = set()
        while todo:  # (normal dependencies only: no build scripts' or tests')
            n = todo.pop()
            if n in seen:
                continue
            seen.add(n)
            for d in nodes[n]["deps"]:
                if any(k["kind"] is None for k in d["dep_kinds"]):
                    todo.append(d["pkg"])
        for n in seen:
            found.setdefault((packages[n]["name"], packages[n]["version"]), packages[n])
    out = []
    for (name, version), p in sorted(found.items()):
        if name in OURS or name == BINDING_CRATE:
            continue
        folder = Path(p["manifest_path"]).parent
        files = sorted(f for f in folder.iterdir() if f.is_file() and LICENSE_FILE.match(f.name))
        text = "\n\n".join(f.read_text(encoding="utf-8", errors="replace") for f in files)
        url = p.get("repository") or p.get("homepage") or ""
        out.append(section(f"{name} {version} (Rust)", p.get("license") or "see the text", url,
                           text or f"License: {p.get('license')} (no license file in the crate)"))  # fmt: skip
    return out


if __name__ == "__main__":
    parts = [HEADER, *python_packages(), *rust_crates()]
    Path(sys.argv[1]).write_text("".join(parts), encoding="utf-8")
    print(f"{sys.argv[1]}: {len(parts) - 1} packages")
