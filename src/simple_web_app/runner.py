import subprocess


def run_uvicorn():
    subprocess.run(["uvicorn", "simple_web_app.app:app"])

