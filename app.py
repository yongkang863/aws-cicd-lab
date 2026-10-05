from flask import Flask

app = Flask(__name__)
VERSION = "1.0.1"


@app.get("/")
def home():
    return (
        "<h1>My CI/CD Lab</h1>"
        f"<p>Version: {VERSION}</p>"
    )


@app.get("/health")
def health():
    return {"status": "ok", "version": VERSION}
