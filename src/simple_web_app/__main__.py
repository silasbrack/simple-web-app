import subprocess


def run_uvicorn():
    subprocess.run(["uvicorn", "simple_web_app.app:app"])


if __name__ == "__main__":
    run_uvicorn()

