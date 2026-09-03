"""Shared mutation harness. Copies config/ and fixtures/ beside src/, because `cli.py`
resolves ROOT from its own __file__ — so a snapshot holding only `src` makes any test that
touches the CLI fail for reasons unrelated to the mutation, and `-x` then reports that as
'CAUGHT'."""

import os
import pathlib
import shutil
import subprocess

REPO = pathlib.Path("/home/user/draft-intel")


def snapshot(name):
    snap = pathlib.Path(f"/tmp/{name}")
    if snap.exists():
        shutil.rmtree(snap)
    shutil.copytree(REPO / "src", snap / "src")
    for extra in ("config", "fixtures"):
        shutil.copytree(REPO / extra, snap / extra)
    return snap


def run(snap, suite="", timeout=1200):
    args = ["uv", "run", "python", "-m", "pytest", "-q", "--no-cov", "-p", "no:randomly"]
    if suite:
        args.insert(5, suite)
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        cwd=REPO,
        env={**os.environ, "PYTHONPATH": str(snap / "src")},
        timeout=timeout,
    )


def verify(name, muts, suite=""):
    snap = snapshot(name)
    base = snap / "src/draft_intel"
    clean = run(snap, suite)
    if clean.returncode != 0:
        print("!! BASELINE IS RED under this harness — every result below is meaningless")
        print(clean.stdout[-600:])
        return
    print(f"baseline green ({clean.stdout.strip().splitlines()[-1]})")
    for rel, label, old, new in muts:
        p = base / rel
        orig = p.read_text()
        if old not in orig:
            print(f"SKIP    {label}")
            continue
        p.write_text(orig.replace(old, new, 1))
        r = run(snap, suite)
        print(("CAUGHT  " if r.returncode != 0 else "ESCAPED ") + label)
        p.write_text(orig)
