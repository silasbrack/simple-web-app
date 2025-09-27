import uvicorn


def run():
    uvicorn.run("simple_web_app.main:app")
