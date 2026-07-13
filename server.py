import threading
import time
import ctypes
import cv2
import numpy as np
import mss
import tkinter as tk
import os
import json
import keyboard
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Dict, Any, Optional

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

def get_click_coord():
    root = tk.Tk()
    result = {}
    with mss.MSS() as sct:
        mon = sct.monitors[0]
        
    root.geometry(f"{mon['width']}x{mon['height']}+{mon['left']}+{mon['top']}")
    root.overrideredirect(True)
    root.attributes('-alpha', 0.1)
    root.attributes('-topmost', True)
    root.config(cursor="crosshair")
    
    def on_click(event):
        result['x'] = event.x_root
        result['y'] = event.y_root
        root.quit()
        
    root.bind("<Button-1>", on_click)
    root.bind("<Escape>", lambda e: root.quit())
    root.mainloop()
    root.destroy()
    return result

def get_snip_region():
    root = tk.Tk()
    result = {}
    with mss.MSS() as sct:
        mon = sct.monitors[0]
        
    root.geometry(f"{mon['width']}x{mon['height']}+{mon['left']}+{mon['top']}")
    root.overrideredirect(True)
    root.attributes('-alpha', 0.3)
    root.attributes('-topmost', True)
    root.config(cursor="crosshair")
    
    canvas = tk.Canvas(root, bg='black', highlightthickness=0)
    canvas.pack(fill='both', expand=True)
    
    state = {'start_x': 0, 'start_y': 0, 'rect': None}
    
    def on_press(event):
        state['start_x'] = event.x
        state['start_y'] = event.y
        state['rect'] = canvas.create_rectangle(event.x, event.y, event.x, event.y, outline='red', width=3, fill='gray')
        
    def on_drag(event):
        if state['rect']:
            canvas.coords(state['rect'], state['start_x'], state['start_y'], event.x, event.y)
            
    def on_release(event):
        end_x = event.x_root
        end_y = event.y_root
        start_x_root = root.winfo_rootx() + state['start_x']
        start_y_root = root.winfo_rooty() + state['start_y']
        
        left = min(start_x_root, end_x)
        top = min(start_y_root, end_y)
        width = abs(start_x_root - end_x)
        height = abs(start_y_root - end_y)
        
        if width > 0 and height > 0:
            result['bbox'] = {'left': int(left), 'top': int(top), 'width': int(width), 'height': int(height)}
        root.quit()
        
    root.bind("<ButtonPress-1>", on_press)
    root.bind("<B1-Motion>", on_drag)
    root.bind("<ButtonRelease-1>", on_release)
    root.bind("<Escape>", lambda e: root.quit())
    
    root.mainloop()
    
    root.withdraw()
    if 'bbox' in result:
        time.sleep(0.2)
        with mss.MSS() as sct:
            sct_img = sct.grab(result['bbox'])
            current_img = np.array(sct_img)
            gray = cv2.cvtColor(current_img, cv2.COLOR_BGRA2GRAY)
            edges = cv2.Canny(gray, 50, 150)
            result['baseline'] = edges.tolist()
            
    root.destroy()
    return result

# --- Macro Engine (State Machine) ---

class MacroEngine:
    def __init__(self):
        self.script = {}
        self.is_running = False
        self.current_step = None
        self.thread = None
        self.stop_event = threading.Event()
        self.logs = []

    def log_msg(self, msg: str):
        ts = time.strftime("%H:%M:%S")
        full_msg = f"[{ts}] {msg}"
        print(full_msg)
        self.logs.append(full_msg)
        if len(self.logs) > 100:
            self.logs.pop(0)

    def load_script(self, script_data: dict):
        self.script = script_data

    def start(self, start_step_id: str):
        if not self.script:
            return False
        if start_step_id not in self.script:
            return False
            
        self.stop_event.clear()
        self.is_running = True
        self.current_step = start_step_id
        
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()
        return True

    def stop(self):
        if self.is_running:
            self.stop_event.set()
            self.is_running = False
            if self.thread:
                self.thread.join(timeout=2.0)

    def _run_loop(self):
        while not self.stop_event.is_set() and self.current_step:
            if self.current_step == "end":
                break
                
            step_data = self.script.get(self.current_step)
            if not step_data:
                print(f"Error: Step '{self.current_step}' not found in script.")
                break
                
            step_type = step_data.get("type")
            
            if step_type == "click":
                x = step_data.get("x", 0)
                y = step_data.get("y", 0)
                delay = step_data.get("delay", 1.0)
                
                self.log_msg(f"Clicking at (X:{x}, Y:{y})")
                
                ctypes.windll.user32.SetCursorPos(x, y)
                # Wait for game UI to register hover
                time.sleep(0.2)
                
                # Mouse Down
                ctypes.windll.user32.mouse_event(0x0002, 0, 0, 0, 0)
                # Human-like click duration
                time.sleep(0.1)
                
                # Mouse Up
                ctypes.windll.user32.mouse_event(0x0004, 0, 0, 0, 0)
                
                if self.stop_event.wait(delay):
                    break
                    
                self.current_step = step_data.get("next")
                
            elif step_type == "check_image":
                bbox = step_data.get("bbox")
                baseline_data = step_data.get("baseline")
                tolerance = step_data.get("tolerance", 5.0)
                delay = step_data.get("delay", 0.5)
                
                if not bbox or not baseline_data:
                    print("Error: Missing bbox or baseline in check_image step.")
                    self.current_step = step_data.get("next_if_false")
                    continue
                    
                if delay > 0:
                    if self.stop_event.wait(delay):
                        break
                        
                try:
                    baseline_edges = np.array(baseline_data, dtype=np.uint8)
                    with mss.MSS() as sct:
                        sct_img = sct.grab(bbox)
                        current_gray = cv2.cvtColor(np.array(sct_img), cv2.COLOR_BGRA2GRAY)
                        
                        if baseline_edges.shape != current_gray.shape:
                            current_gray = cv2.resize(current_gray, (baseline_edges.shape[1], baseline_edges.shape[0]))
                            
                        current_edges = cv2.Canny(current_gray, 50, 150)
                        
                        diff = cv2.absdiff(baseline_edges, current_edges)
                        num_chunks = max(5, diff.shape[1] // 10)
                        chunks = np.array_split(diff, num_chunks, axis=1)
                        max_chunk_diff = 0.0
                        
                        for chunk in chunks:
                            chunk_diff = (np.mean(chunk) / 255.0) * 100.0
                            if chunk_diff > max_chunk_diff:
                                max_chunk_diff = chunk_diff
                        
                        self.log_msg(f"Image Check: Max Diff = {max_chunk_diff:.2f}% | Tol = {tolerance:.2f}%")
                        
                        if max_chunk_diff > tolerance:
                            self.current_step = step_data.get("next_if_true")
                        else:
                            self.current_step = step_data.get("next_if_false")
                            
                        self.log_msg(f"Branching to: {self.current_step}")
                            
                except Exception as e:
                    print(f"Image check error: {e}")
                    self.current_step = step_data.get("next_if_false")
                    
                if self.stop_event.wait(0.1):
                    break
            elif step_type == "keypress":
                key = step_data.get("key", "enter")
                delay = step_data.get("delay", 1.0)
                
                self.log_msg(f"Pressing key: '{key}'")
                keyboard.press_and_release(key)
                
                if self.stop_event.wait(delay):
                    break
                    
                self.current_step = step_data.get("next")
            else:
                print(f"Error: Unknown step type '{step_type}'.")
                break
                
        self.is_running = False
        self.current_step = None


# --- FastAPI Application ---

app = FastAPI(title="Macro Engine Server")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SCRIPTS_DIR = "saved_macros"
os.makedirs(SCRIPTS_DIR, exist_ok=True)

engine = MacroEngine()

class ScriptRequest(BaseModel):
    script: Dict[str, Any]

class SaveScriptRequest(BaseModel):
    filename: str
    script: Dict[str, Any]

class StartRequest(BaseModel):
    start_step: str = "step_1"

@app.post("/load_script")
def load_script(req: ScriptRequest):
    engine.load_script(req.script)
    return {"message": "Script loaded successfully", "total_steps": len(req.script)}

@app.post("/save_script_file")
def save_script_file(req: SaveScriptRequest):
    if not req.filename.endswith(".json"):
        req.filename += ".json"
    filepath = os.path.join(SCRIPTS_DIR, req.filename)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(req.script, f, indent=4)
    return {"message": "Saved successfully"}

@app.get("/list_scripts")
def list_scripts():
    if not os.path.exists(SCRIPTS_DIR):
        return {"scripts": []}
    files = [f for f in os.listdir(SCRIPTS_DIR) if f.endswith(".json")]
    return {"scripts": files}

@app.get("/get_script/{filename}")
def get_script(filename: str):
    filepath = os.path.join(SCRIPTS_DIR, filename)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="File not found")
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data

@app.post("/start")
def start_engine(req: StartRequest):
    if engine.is_running:
        raise HTTPException(status_code=400, detail="Engine is already running")
    
    success = engine.start(req.start_step)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to start. Ensure script is loaded and start_step exists.")
        
    return {"message": f"Engine started at step '{req.start_step}'"}

@app.post("/stop")
def stop_engine():
    engine.stop()
    return {"message": "Engine stopped"}

@app.get("/status")
def get_status():
    return {
        "is_running": engine.is_running,
        "current_step": engine.current_step
    }

@app.get("/logs")
def get_logs():
    return {"logs": engine.logs}

@app.get("/capture_coord")
def capture_coord():
    res = get_click_coord()
    if 'x' in res:
        return {"x": res['x'], "y": res['y']}
    raise HTTPException(status_code=400, detail="Cancelled")

@app.get("/capture_region")
def capture_region():
    res = get_snip_region()
    if 'bbox' in res and 'baseline' in res:
        return {"bbox": res['bbox'], "baseline": res['baseline']}
    raise HTTPException(status_code=400, detail="Cancelled")


import os
from fastapi.staticfiles import StaticFiles

frontend_dist = os.path.join(os.path.dirname(__file__), "frontend", "dist")
if os.path.exists(frontend_dist):
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="127.0.0.1", port=8000, reload=False)
