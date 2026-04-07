#!/usr/bin/env python3
import os
import shutil
import tarfile
import tempfile
from pathlib import Path


HOME = Path("/home/huazi")
LOCAL = HOME / ".local"
OUT = Path("/home/huazi/auto-rpm-builder/assets/ghostty-rhel10-bundle.tar.gz")


def copy_file(src: Path, dest: Path, mode=None):
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest, follow_symlinks=False)
    if mode is not None:
        os.chmod(dest, mode)


def copy_tree(src: Path, dest: Path):
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest, symlinks=True)


def rewrite_wrapper(src: Path, dest: Path):
    content = src.read_text()
    content = content.replace('libdir="$HOME/.local/lib"', 'libdir="/usr/lib64/ghostty"')
    content = content.replace('bindir="$HOME/.local/libexec/ghostty-bin"', 'bindir="/usr/libexec/ghostty/ghostty-bin"')
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(content)
    os.chmod(dest, 0o755)


def rewrite_desktop(src: Path, dest: Path):
    text = src.read_text()
    text = text.replace("/home/huazi/.local/bin/ghostty", "/usr/bin/ghostty")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text)
    os.chmod(dest, 0o644)


def build_bundle():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ghostty-bundle-") as tempdir:
        root = Path(tempdir) / "ghostty-root"
        (root / "usr").mkdir(parents=True, exist_ok=True)

        rewrite_wrapper(LOCAL / "bin/ghostty", root / "usr/bin/ghostty")
        copy_file(LOCAL / "libexec/ghostty-bin", root / "usr/libexec/ghostty/ghostty-bin", 0o755)

        libdir = root / "usr/lib64/ghostty"
        libdir.mkdir(parents=True, exist_ok=True)
        for name in [
            "libgtk4-layer-shell.so",
            "libghostty-vt.so",
            "libghostty-vt.so.0",
            "libghostty-vt.so.0.1.0",
        ]:
            src = LOCAL / "lib" / name
            if src.is_symlink():
                target = os.readlink(src)
                link = libdir / name
                link.symlink_to(target)
            else:
                copy_file(src, libdir / name, 0o755)

        rewrite_desktop(
            LOCAL / "share/applications/com.mitchellh.ghostty.desktop",
            root / "usr/share/applications/com.mitchellh.ghostty.desktop",
        )
        copy_file(
            LOCAL / "share/metainfo/com.mitchellh.ghostty.metainfo.xml",
            root / "usr/share/metainfo/com.mitchellh.ghostty.metainfo.xml",
            0o644,
        )

        copy_tree(LOCAL / "share/ghostty", root / "usr/share/ghostty")
        copy_tree(LOCAL / "share/terminfo", root / "usr/share/terminfo")
        copy_tree(LOCAL / "share/icons/hicolor", root / "usr/share/icons/hicolor")
        copy_tree(LOCAL / "share/locale", root / "usr/share/locale")
        copy_file(
            LOCAL / "share/bash-completion/completions/ghostty.bash",
            root / "usr/share/bash-completion/completions/ghostty.bash",
            0o644,
        )
        copy_file(
            LOCAL / "share/fish/vendor_completions.d/ghostty.fish",
            root / "usr/share/fish/vendor_completions.d/ghostty.fish",
            0o644,
        )
        copy_file(
            LOCAL / "share/zsh/site-functions/_ghostty",
            root / "usr/share/zsh/site-functions/_ghostty",
            0o644,
        )

        with tarfile.open(OUT, "w:gz") as tf:
            tf.add(root, arcname="ghostty-root")

    print(OUT)


if __name__ == "__main__":
    build_bundle()
