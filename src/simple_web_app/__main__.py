import subprocess
import sys


def run_uvicorn():
    subprocess.run([sys.executable, "-m", "uvicorn", "simple_web_app.app:app"])


if __name__ == "__main__":
    run_uvicorn()

