def build_rtsp_url(ip: str, port: int, path: str | None, username: str | None, password: str | None) -> str:
    auth = f"{username}:{password}@" if username and password else ""
    suffix = path if path and path.startswith("/") else f"/{path}" if path else "/"
    return f"rtsp://{auth}{ip}:{port}{suffix}"
