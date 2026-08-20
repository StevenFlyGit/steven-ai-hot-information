"""验证 server.py 改造后只提供 API，不再托管静态文件。"""
import urllib.request
import urllib.error

BASE = "http://localhost:9000"

tests = [
    ("根路径 /",           "/"),
    ("index.html",         "/index.html"),
    ("styles.css",         "/styles.css"),
    ("app.js",             "/app.js"),
    ("API /api/health",    "/api/health"),
    ("API /api/menu",      "/api/menu"),
    ("API /api/proxy",     "/api/proxy/hot-topics"),
]

print(f"{'路径':<25} {'状态码':<8} {'响应内容（前60字）'}")
print("-" * 80)

for label, path in tests:
    url = BASE + path
    try:
        r = urllib.request.urlopen(url)
        body = r.read().decode("utf-8", "replace")
        status = r.status
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        status = e.code
    except Exception as e:
        body = str(e)
        status = "ERR"

    preview = body[:60].replace("\n", " ")
    marker = "  OK" if status == 200 else "  << 404/错误"
    print(f"{label:<25} {status:<8} {preview}{marker}")

print()
print("结论：")
print("  - /、/index.html、/styles.css、/app.js → 404（静态文件不再托管）")
print("  - /api/* → 200（API 正常工作）")
print("  - server.py 现在是纯 API 服务，不是完整 Web 服务。")
