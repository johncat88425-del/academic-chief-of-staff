"""Launcher for Academic Chief of Staff Web Dashboard."""

import webbrowser
import time
import threading
import socket
import uvicorn

def get_local_ip():
    try:
        import subprocess
        res = subprocess.run(["ipconfig", "getifaddr", "en0"], capture_output=True, text=True, timeout=2)
        ip = res.stdout.strip()
        if ip:
            return ip
    except Exception:
        pass
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

def open_browser():
    time.sleep(1.2)
    webbrowser.open("http://127.0.0.1:8400")

if __name__ == "__main__":
    local_ip = get_local_ip()
    threading.Thread(target=open_browser, daemon=True).start()
    print("\n" + "=" * 65)
    print("🎓 智慧學業幕僚 Web 儀表板已啟動！")
    print(f"👉 電腦本機瀏覽：http://127.0.0.1:8400")
    print(f"📱 手機連線填寫：http://{local_ip}:8400/mobile-input")
    print("=" * 65 + "\n")
    uvicorn.run("src.web.app:app", host="0.0.0.0", port=8400, log_level="info")
