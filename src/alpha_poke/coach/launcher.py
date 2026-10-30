"""The packaged review app's entry (packaging/windows): nothing to install for the user.

Frozen (PyInstaller): the data under %LOCALAPPDATA%\\alpha-poke (ALPHA_DATA, set before any
alpha_poke module reads it), the bundled model, belief models and usage statistics copied there
on first run (assets/, the data directory's layout); then the app on a free port from 8090 and
the browser opened at its home page. Closing the console window stops it. From a checkout (not
frozen) the same with the repository's data/.
"""

import os
import shutil
import sys
from pathlib import Path


def install(assets: Path, data: Path) -> None:
    """The bundled files into the data directory, where missing or of another size."""
    for src in assets.rglob("*"):
        if src.is_file():
            dst = data / src.relative_to(assets)
            if not dst.exists() or dst.stat().st_size != src.stat().st_size:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(src, dst)


def main() -> None:
    # (the console or a redirected file may not take the Chinese messages in its code page --
    # cp1252 on an English Windows: 2026-10-30, the first build's smoke test)
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    if getattr(sys, "frozen", False):
        data = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "alpha-poke"
        os.environ.setdefault("ALPHA_DATA", str(data))
        install(Path(sys._MEIPASS) / "assets", Path(os.environ["ALPHA_DATA"]))
    from alpha_poke.coach import app, server

    port = app.free_port()
    url = f"http://127.0.0.1:{port}/"
    if server.running(port):  # (the app is open already: just show it)
        server.open_page(url)
        return
    httpd = app.make(port)
    print(
        f"对局复盘已启动：{url}\n浏览器没有自动打开的话，请手动打开这个地址。关闭这个窗口即可退出。",
        flush=True,
    )
    server.open_page(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
