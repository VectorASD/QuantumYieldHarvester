from aiohttp import web

from pathlib import Path


basepath = Path(__file__).parent

def route_file(app: web.Application, urlpath: str, filepath: str|Path, content_type: str):
    """Serve a static file at the given URL path with the specified content type."""
    if isinstance(filepath, str):
        filepath = basepath / filepath
    filepath = filepath.resolve()

    async def handler(request: web.Request) -> web.Response:
        try:
            with filepath.open("rb") as file:
                body = file.read()
            return web.Response(body=body, content_type=content_type)
        except FileNotFoundError:
            rel_path = filepath.relative_to(basepath) if filepath.is_relative_to(basepath) else filepath
            return web.Response(text=f"{rel_path} not found", status=404)
    app.router.add_get(urlpath, handler)

app = web.Application()
route_file(app, '/', "index.html", "text/html")
route_file(app, "/fingerprint.js", "fingerprint.js", "application/javascript")


if __name__ == "__main__":
    print("Stating server...")
    web.run_app(app, host="127.0.0.1", port=8000)
