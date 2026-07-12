import os
import sys
import ctypes

def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False

if not is_admin():
    # Relaunch the process with admin privileges
    script_path = os.path.abspath(sys.argv[0])
    directory = os.path.dirname(script_path)
    params = ' '.join([f'"{script_path}"'] + sys.argv[1:])
    ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, directory, 1)
    sys.exit()

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

import threading
import time
import webview
import uvicorn
from server import app

def start_server():
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="error")

if __name__ == '__main__':
    # Start the FastAPI server in a background daemon thread
    server_thread = threading.Thread(target=start_server, daemon=True)
    server_thread.start()
    
    # Wait a moment for the server to bind to the port
    time.sleep(1)
    
    # Open the native desktop window pointing to the local server
    webview.create_window("Macro Auto Clicker", "http://127.0.0.1:8000", width=1200, height=800)
    webview.start()
