from urllib.parse import quote


def build_rtsp_url(ip: str, port: int, path: str | None, username: str | None, password: str | None) -> str:
    if username and password:
        auth = f"{quote(username, safe='')}:{quote(password, safe='')}@"
    elif username:
        auth = f"{quote(username, safe='')}@"
    else:
        auth = ""
    suffix = path if path and path.startswith("/") else f"/{path}" if path else "/"
    return f"rtsp://{auth}{ip}:{port}{suffix}"
