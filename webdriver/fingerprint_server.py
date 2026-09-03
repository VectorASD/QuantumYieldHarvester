from aiohttp import web

from pathlib import Path
import errno
import re


basepath = Path(__file__).parent
parts = {
    b"CHALLENGE_BLOCK": basepath / "polygon" / "challenge_block.html",
}
def sub_part(match):
    comment = match.group(0)
    name = comment[len(b"<!--"):-len(b"-->")].strip()
    if name in parts:
        try:
            return parts[name].read_bytes()
        except FileNotFoundError:
            pass
    return comment
COMMENT_PATTERN = re.compile(rb"<!--(.*?)-->", re.DOTALL)

def route_file(app: web.Application, urlpath: str, filepath: str|Path, content_type: str):
    """Serve a static file at the given URL path with the specified content type."""
    if isinstance(filepath, str):
        filepath = basepath / filepath
    filepath = filepath.resolve()

    async def handler(request: web.Request) -> web.Response:
        try:
            body = filepath.read_bytes()
        except FileNotFoundError:
            rel_path = filepath.relative_to(basepath) if filepath.is_relative_to(basepath) else filepath
            return web.Response(text=f"{rel_path} not found", status=404)
        if filepath.suffix == ".html":
            body = COMMENT_PATTERN.sub(sub_part, body)
        return web.Response(body=body, content_type=content_type)
    app.router.add_get(urlpath, handler)

app = web.Application()
route_file(app, '/',               "index.html",     "text/html")
route_file(app, "/fingerprint.js", "fingerprint.js", "application/javascript")
route_file(app, "/challenge.js",   "polygon/challenge.js",     "application/javascript")
route_file(app, "/challenge2.js",  "polygon/challenge2.js",    "application/javascript")


if __name__ == "__main__":
    print("Starting server...")
    try: web.run_app(app, host="127.0.0.1", port=8000)
    except OSError as e:
        if e.errno == errno.EADDRINUSE:
            print("Error: port 8000 is already in use. Perhaps a previous instance of the server is still running.")
            print("netstat -ano | findstr :8000")
            print("taskkill /PID <pid> /F")
        else:
            print(f"Failed to start server: {e}")
