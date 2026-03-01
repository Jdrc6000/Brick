#!/usr/bin/env python3
import os, sys, subprocess, tempfile

REPO = "https://github.com/Jdrc6000/Brick"

def bootstrap():
    tmp = tempfile.mkdtemp()
    subprocess.run(["git", "clone", "--depth=1", REPO, tmp], check=True, capture_output=True)
    os.chdir(tmp)
    try:
        subprocess.run([sys.executable, "brick-client.py"], check=True)
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)

bootstrap()