"""
OpenCode Go Switch — 桌面 GUI 版
同进程内直接运行 FastAPI 服务 + pywebview 原生窗口 + 系统托盘。
"""
import sys, os, json, socket, threading, time, traceback
from pathlib import Path

# ── 错误日志到文件（方便排查闪退） ──────────────────────
BASE_DIR = Path(__file__).parent
LOG_FILE = BASE_DIR / "gui_error.log"

def log_error(msg):
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
    except Exception:
        pass

try:
    import webview
    import pystray
    from PIL import Image, ImageDraw
    # Windows 任务栏图标：设独立 AppUserModelID，避免被归到 python.exe
    import ctypes
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ruichou.opencodegoswitch")
except Exception as e:
    log_error(f"导入失败: {e}\n{traceback.format_exc()}")
    raise

# ── 配置 ───────────────────────────────────────────────
CONFIG_FILE = BASE_DIR / "config.json"
_cfg = json.loads(CONFIG_FILE.read_text()) if CONFIG_FILE.exists() else {}
PORT = _cfg.get("port", 7878)

server_thread = None
tray_icon = None
window_ref = None


# ── 同进程内启动 FastAPI 服务 ──────────────────────────
def run_server_in_thread():
    """在后台线程里直接跑 uvicorn，不依赖 subprocess/sys.executable"""
    import uvicorn
    from server import app  # 同目录下的 server.py
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning", access_log=False)


def is_server_running():
    try:
        s = socket.socket()
        s.settimeout(0.5)
        s.connect(("127.0.0.1", PORT))
        s.close()
        return True
    except Exception:
        return False


def ensure_server():
    """确保服务在运行；同进程内启动"""
    if is_server_running():
        log_error("服务已在运行")
        return
    log_error("正在启动内嵌服务…")
    t = threading.Thread(target=run_server_in_thread, daemon=True)
    t.start()
    for _ in range(30):
        time.sleep(0.3)
        if is_server_running():
            log_error("服务启动成功")
            return
    log_error("⚠️ 服务启动超时")


# ── 图标 ───────────────────────────────────────────────
def get_icon_image():
    ico_path = BASE_DIR / "icon.ico"
    if ico_path.exists():
        return Image.open(ico_path)
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([4, 4, 60, 60], radius=14, fill="#4f46e5")
    draw.text((16, 18), "OG", fill="white")
    return img


# ── Windows 窗口图标设置 ───────────────────────────────
def set_window_icon():
    """用 Windows API 给窗口标题栏和任务栏设图标"""
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        WM_SETICON = 0x80
        ICON_SMALL = 0
        ICON_BIG = 1
        LR_LOADFROMFILE = 0x00000040
        IMAGE_ICON = 1

        ico_path = str(BASE_DIR / "icon.ico")
        if not os.path.exists(ico_path):
            return

        # 加载图标
        hicon = user32.LoadImageW(
            0, ico_path, IMAGE_ICON, 32, 32, LR_LOADFROMFILE
        )
        if not hicon:
            return

        # 通过 EnumWindows 找标题匹配窗口
        found = [None]
        EnumWindowsProc = ctypes.WINFUNCTYPE(
            wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
        )

        def cb(hwnd, _):
            buf = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, buf, 256)
            if "OpenCode Go Switch" in buf.value:
                found[0] = hwnd
                return False
            return True

        user32.EnumWindows(EnumWindowsProc(cb), 0)
        if found[0]:
            user32.SendMessageW(found[0], WM_SETICON, ICON_SMALL, hicon)
            user32.SendMessageW(found[0], WM_SETICON, ICON_BIG, hicon)
    except Exception as e:
        log_error(f"设图标失败: {e}")


def icon_setter_thread():
    """等窗口显示出来再设图标"""
    time.sleep(1.5)
    set_window_icon()



# ── 系统托盘 ───────────────────────────────────────────
def on_tray_show(icon, item):
    global window_ref
    if window_ref:
        try:
            window_ref.show()
            window_ref.restore()
        except Exception:
            pass


def on_tray_quit(icon, item):
    global tray_icon
    if tray_icon:
        tray_icon.stop()
    os._exit(0)


def create_tray():
    global tray_icon
    if tray_icon:
        return
    icon_img = get_icon_image()
    menu = pystray.Menu(
        pystray.MenuItem("显示窗口", on_tray_show, default=True),
        pystray.MenuItem("退出", on_tray_quit),
    )
    tray_icon = pystray.Icon("opencode_switch", icon_img, "OpenCode Go Switch", menu)


def run_tray():
    if tray_icon:
        tray_icon.run()


# ── 窗口事件 ───────────────────────────────────────────
def on_closing():
    global window_ref
    if window_ref:
        window_ref.hide()
    return False  # 阻止关闭，改为最小化到托盘


def on_closed():
    global tray_icon
    if tray_icon:
        tray_icon.stop()
    os._exit(0)


# ── 主入口 ─────────────────────────────────────────────
def main():
    global window_ref
    try:
        log_error("=== 启动 ===")
        log_error(f"端口: {PORT}, Python: {sys.executable}")

        # 1. 启动服务
        ensure_server()

        # 2. 系统托盘
        create_tray()
        threading.Thread(target=run_tray, daemon=True).start()

        # 3. 创建窗口
        url = f"http://127.0.0.1:{PORT}/"
        window = webview.create_window(
            title="OpenCode Go Switch",
            url=url,
            width=760,
            height=620,
            min_size=(600, 450),
            resizable=True,
            confirm_close=True,
        )
        window_ref = window
        window.events.closing += on_closing
        window.events.closed += on_closed

        # 窗口显示后设图标（pywebview 6.x 不支持 create_window(icon=)）
        threading.Thread(target=icon_setter_thread, daemon=True).start()

        log_error("窗口已启动")
        webview.start(gui="edgechromium", http_server=True)

    except Exception as e:
        log_error(f"CRASH: {e}\n{traceback.format_exc()}")
        # 弹个消息框让用户看到错误
        try:
            import tkinter.messagebox as mb
            mb.showerror("OpenCode Go Switch 错误", f"启动失败:\n{e}\n\n详情见 gui_error.log")
        except Exception:
            pass
        raise


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    main()
