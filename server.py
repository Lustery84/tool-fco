import threading
import time
import ctypes
import cv2
import numpy as np
import mss
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Dict, Any, Optional

# --- Macro Engine (State Machine) ---

class MacroEngine:
    def __init__(self):
        self.script = {}
        self.is_running = False
        self.current_step = None
        self.thread = None
        self.stop_event = threading.Event()

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
            # Special 'end' keyword stops the machine
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
                
                # Move mouse
                ctypes.windll.user32.SetCursorPos(x, y)
                time.sleep(0.05)
                
                # Mouse Down (0x0002)
                ctypes.windll.user32.mouse_event(0x0002, 0, 0, 0, 0)
                time.sleep(0.05)
                
                # Mouse Up (0x0004)
                ctypes.windll.user32.mouse_event(0x0004, 0, 0, 0, 0)
                
                # Wait for the delay specified in the step, break if stopped
                if self.stop_event.wait(delay):
                    break
                    
                self.current_step = step_data.get("next")
                
            elif step_type == "check_image":
                bbox = step_data.get("bbox")
                baseline_data = step_data.get("baseline")
                tolerance = step_data.get("tolerance", 5.0)
                
                if not bbox or not baseline_data:
                    print("Error: Missing bbox or baseline in check_image step.")
                    self.current_step = step_data.get("next_if_false")
                    continue
                    
                try:
                    # Convert list back to numpy array
                    baseline = np.array(baseline_data, dtype=np.uint8)
                    
                    with mss.MSS() as sct:
                        sct_img = sct.grab(bbox)
                        current_img = np.array(sct_img)
                        current_gray = cv2.cvtColor(current_img, cv2.COLOR_BGRA2GRAY)
                        
                        thresh_val = 150
                        _, baseline_thresh = cv2.threshold(baseline, thresh_val, 255, cv2.THRESH_BINARY)
                        _, current_thresh = cv2.threshold(current_gray, thresh_val, 255, cv2.THRESH_BINARY)
                        
                        diff = cv2.absdiff(baseline_thresh, current_thresh)
                        chunks = np.array_split(diff, 5, axis=1)
                        max_chunk_diff = 0.0
                        
                        for chunk in chunks:
                            chunk_diff = (np.mean(chunk) / 255.0) * 100.0
                            if chunk_diff > max_chunk_diff:
                                max_chunk_diff = chunk_diff
                        
                        # Branching logic based on image match
                        if max_chunk_diff > tolerance:
                            self.current_step = step_data.get("next_if_true")
                        else:
                            self.current_step = step_data.get("next_if_false")
                            
                except Exception as e:
                    print(f"Image check error: {e}")
                    self.current_step = step_data.get("next_if_false")
                    
                # Small delay to prevent high CPU usage on fast loops
                if self.stop_event.wait(0.1):
                    break
            else:
                print(f"Error: Unknown step type '{step_type}'.")
                break
                
        self.is_running = False
        self.current_step = None


# --- FastAPI Application ---

app = FastAPI(title="Macro Engine Server")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # For dev only. Restrict this in production.
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

engine = MacroEngine()

class ScriptRequest(BaseModel):
    script: Dict[str, Any]

class StartRequest(BaseModel):
    start_step: str = "step_1"

@app.post("/load_script")
def load_script(req: ScriptRequest):
    engine.load_script(req.script)
    return {"message": "Script loaded successfully", "total_steps": len(req.script)}

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

import os
from fastapi.staticfiles import StaticFiles

frontend_dist = os.path.join(os.path.dirname(__file__), "frontend", "dist")
if os.path.exists(frontend_dist):
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")

if __name__ == "__main__":
    import uvicorn
    # Run the server on port 8000
    uvicorn.run("server:app", host="127.0.0.1", port=8000, reload=False)
