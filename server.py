import threading
import time
import ctypes
import cv2
import numpy as np
import mss
import tkinter as tk
import os
import json
import pydirectinput
import telebot
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
            # Remove Canny to avoid noise, save raw grayscale instead
            result['baseline'] = gray.tolist()
            
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
        self.rest_interval_sec = 0.0
        self.rest_duration_sec = 0.0
        self.last_rest_time = 0.0
        self.on_finish_callback = None
        self.pending_stop = False
        self.pending_rest = False
        self.stop_delay_steps = 0
        self.steps_until_stop = 0
        self.schedule_config = None
        self.waiting_for_check_to_stop = False

    def log_msg(self, msg: str):
        ts = time.strftime("%H:%M:%S")
        full_msg = f"[{ts}] {msg}"
        print(full_msg)
        self.logs.append(full_msg)
        if len(self.logs) > 100:
            self.logs.pop(0)

    def load_script(self, script_data: dict):
        self.script = script_data

    def start(self, start_step_id: str, rest_interval_min: float = 0.0, rest_duration_sec: float = 0.0, stop_delay_steps: int = 0, schedule_config: dict = None):
        if not self.script:
            return False
        if start_step_id not in self.script:
            return False
            
        self.rest_interval_sec = rest_interval_min * 60.0
        self.rest_duration_sec = rest_duration_sec
        self.stop_delay_steps = stop_delay_steps
        self.last_rest_time = time.time()
        self.schedule_config = schedule_config
        
        self.stop_event.clear()
        self.is_running = True
        self.current_step = start_step_id
        self.pending_stop = False
        self.pending_rest = False
        self.steps_until_stop = 0
        
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()
        return True

    def stop(self):
        if self.is_running:
            if self.stop_delay_steps > 0 and not self.pending_stop and not getattr(self, 'waiting_for_check_to_stop', False):
                self.waiting_for_check_to_stop = True
                self.log_msg(f"Stop requested. Waiting for next 'check_image' step, then running {self.stop_delay_steps} more steps...")
                return
                
            self.stop_event.set()
            self.is_running = False
            if self.thread:
                self.thread.join(timeout=2.0)

    def _run_loop(self):
        import datetime
        while not self.stop_event.is_set() and self.current_step:
            if self.schedule_config:
                now = datetime.datetime.now()
                is_odd = (now.hour % 2 != 0)
                curr_type = 'l' if is_odd else 'c'
                curr_min = now.minute
                
                is_active = False
                for rule in self.schedule_config['rules']:
                    if rule['type'] == curr_type:
                        start_min = rule['start_min']
                        end_min = start_min + self.schedule_config['duration']
                        
                        # Check if current minute is within the window (handle minute overflow)
                        if end_min < 60:
                            if start_min <= curr_min < end_min:
                                is_active = True
                                break
                        else:
                            if (curr_min >= start_min) or (curr_min < (end_min % 60)):
                                is_active = True
                                break
                    
                if not is_active:
                    if getattr(self, 'waiting_for_check_to_stop', False) or self.pending_stop:
                        self.log_msg("Stop requested during scheduled sleep. Stopping immediately.")
                        self.stop_event.set()
                        break
                    # Not active time, just sleep and wait
                    time.sleep(1)
                    continue

            if self.pending_stop or self.pending_rest:
                if self.steps_until_stop <= 0:
                    if self.pending_stop:
                        self.log_msg("Graceful stop completed.")
                        self.stop_event.set()
                        break
                    elif self.pending_rest:
                        self.log_msg(f"Graceful Anti-Ban: Resting for {self.rest_duration_sec} seconds...")
                        if self.stop_event.wait(self.rest_duration_sec):
                            break
                        self.last_rest_time = time.time()
                        self.pending_rest = False
                else:
                    self.steps_until_stop -= 1
                    
            if self.rest_interval_sec > 0 and self.rest_duration_sec > 0 and not self.pending_rest:
                if time.time() - self.last_rest_time >= self.rest_interval_sec:
                    if self.stop_delay_steps > 0:
                        self.pending_rest = True
                        self.steps_until_stop = self.stop_delay_steps
                        self.log_msg(f"Anti-Ban triggered. Running {self.steps_until_stop} more steps...")
                    else:
                        self.log_msg(f"Anti-Ban: Resting for {self.rest_duration_sec} seconds...")
                        if self.stop_event.wait(self.rest_duration_sec):
                            break
                        self.last_rest_time = time.time()
                    
            if self.current_step == "end":
                self.log_msg("Macro reached end.")
                if self.on_finish_callback:
                    self.on_finish_callback()
                break
                
            step_data = self.script.get(self.current_step)
            if not step_data:
                print(f"Error: Step '{self.current_step}' not found in script.")
                break
                
            step_type = step_data.get("type")
            
            if getattr(self, 'waiting_for_check_to_stop', False) and step_type == "check_image":
                self.waiting_for_check_to_stop = False
                self.pending_stop = True
                self.steps_until_stop = self.stop_delay_steps
                self.log_msg(f"Hit 'check_image'. Now running {self.steps_until_stop} more steps before stopping.")
            
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
                    baseline_gray = np.array(baseline_data, dtype=np.uint8)
                    edges_base = cv2.Canny(baseline_gray, 50, 150)
                    ink_base = np.count_nonzero(edges_base)
                    
                    valid_capture = False
                    # Dynamically wait up to 5 seconds if the screen doesn't match the general "text density" of our baseline (lag/wrong tab)
                    for _ in range(50):
                        if self.stop_event.is_set():
                            break
                            
                        with mss.MSS() as sct:
                            sct_img = sct.grab(bbox)
                            current_gray = cv2.cvtColor(np.array(sct_img), cv2.COLOR_BGRA2GRAY)
                            
                        if baseline_gray.shape != current_gray.shape:
                            current_gray = cv2.resize(current_gray, (baseline_gray.shape[1], baseline_gray.shape[0]))
                            
                        edges_curr = cv2.Canny(current_gray, 50, 150)
                        ink_curr = np.count_nonzero(edges_curr)
                        
                        if ink_base < 10:
                            valid_capture = True
                            break
                            
                        ratio = ink_curr / ink_base
                        # If the amount of text/edges is between 40% and 250% of the baseline, it's the right tab
                        if 0.4 <= ratio <= 2.5:
                            valid_capture = True
                            break
                        else:
                            self.log_msg(f"Lag/Wrong Tab detected (Ink Ratio: {ratio:.2f}). Waiting...")
                            if self.stop_event.wait(0.1):
                                break
                    
                    if not valid_capture and not self.stop_event.is_set():
                        self.log_msg("Timeout waiting for correct tab. Proceeding anyway.")
                        
                    # Apply Gaussian Blur to reduce noise
                    blur_base = cv2.GaussianBlur(baseline_gray, (3, 3), 0)
                    blur_curr = cv2.GaussianBlur(current_gray, (3, 3), 0)
                    
                    # Absolute difference
                    diff = cv2.absdiff(blur_base, blur_curr)
                    
                    # Threshold the difference (only differences > 30 out of 255 count as a change)
                    _, thresh_diff = cv2.threshold(diff, 30, 255, cv2.THRESH_BINARY)
                    
                    num_chunks = max(5, thresh_diff.shape[1] // 10)
                    chunks = np.array_split(thresh_diff, num_chunks, axis=1)
                    max_chunk_diff = 0.0
                    
                    for chunk in chunks:
                        chunk_diff = (np.count_nonzero(chunk) / chunk.size) * 100.0
                        if chunk_diff > max_chunk_diff:
                            max_chunk_diff = chunk_diff
                    
                    self.log_msg(f"Image Check: Max Diff = {max_chunk_diff:.2f}% | Tol = {tolerance:.2f}%")
                    
                    # Save debugging images
                    os.makedirs("debug_images", exist_ok=True)
                    cv2.imwrite("debug_images/1_baseline.png", baseline_gray)
                    cv2.imwrite("debug_images/2_current.png", current_gray)
                    cv2.imwrite("debug_images/3_diff.png", thresh_diff)
                    
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
                key = step_data.get("key", "enter").lower()
                delay = step_data.get("delay", 1.0)
                
                # Map common key names to pydirectinput format
                if key == "esc":
                    key = "escape"
                
                self.log_msg(f"Pressing key: '{key}' (DirectInput)")
                try:
                    pydirectinput.press(key)
                except Exception as e:
                    self.log_msg(f"Keypress error: {e}")
                    
                if delay > 0:
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

# --- Telegram Bot Setup ---
telegram_config = {"bot_token": "", "chat_id": ""}
bot = None

def load_telegram_config():
    global telegram_config, bot
    config_path = "telegram_config.json"
    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            telegram_config.update(json.load(f))
    if telegram_config.get("bot_token"):
        try:
            bot = telebot.TeleBot(telegram_config["bot_token"])
            setup_telegram_handlers(bot)
        except Exception as e:
            print(f"Failed to init bot: {e}")

def send_debug_images(chat_id):
    if not bot: return
    try:
        media = []
        for img_name in ["1_baseline.png", "2_current.png", "3_diff.png"]:
            path = os.path.join("debug_images", img_name)
            if os.path.exists(path):
                media.append(telebot.types.InputMediaPhoto(open(path, 'rb')))
        if media:
            bot.send_media_group(chat_id, media)
    except Exception as e:
        print(f"Error sending images: {e}")

def setup_telegram_handlers(tbot):
    @tbot.message_handler(commands=['stop', 'status', 'anh'])
    def handle_commands(message):
        chat_id = str(message.chat.id)
        cfg_chat_id = str(telegram_config.get("chat_id", ""))
        if not cfg_chat_id:
            tbot.reply_to(message, f"Chat ID is not set in UI. Your Chat ID is: {chat_id}")
            return
        if chat_id != cfg_chat_id:
            tbot.reply_to(message, f"Unauthorized user. Your Chat ID: {chat_id}")
            return
            
        cmd = message.text.split()[0].lower()
        if cmd == '/stop':
            engine.stop()
            tbot.reply_to(message, "Macro stopped remotely.")
        elif cmd in ['/status', '/anh']:
            state = "RUNNING" if engine.is_running else "IDLE"
            tbot.reply_to(message, f"Status: {state}\nCurrent Step: {engine.current_step}\nSending debug images...")
            threading.Thread(target=send_debug_images, args=(chat_id,), daemon=True).start()

    @tbot.message_handler(func=lambda msg: msg.text and msg.text.startswith('/'))
    def handle_startbot(message):
        chat_id = str(message.chat.id)
        cfg_chat_id = str(telegram_config.get("chat_id", ""))
        if not cfg_chat_id or chat_id != cfg_chat_id:
            return
            
        cmd_text = message.text.split()[0].lower()
        import re, os, json
        raw_cmd = cmd_text[1:] # Remove '/'
        
        # Pattern for /<macro_name>-L30-C20-15 or /<macro_name>-L05-L55-10
        match = re.match(r'^(.+)-([lc])(\d+)-([lc])(\d+)-(\d+)$', raw_cmd)
        
        macro_name = ""
        schedule_cfg = None
        
        if match:
            macro_name = match.group(1)
            schedule_cfg = {
                'rules': [
                    {'type': match.group(2), 'start_min': int(match.group(3))},
                    {'type': match.group(4), 'start_min': int(match.group(5))}
                ],
                'duration': int(match.group(6))
            }
        else:
            macro_name = raw_cmd
            
        if macro_name == "startbot":
            if not engine.script:
                tbot.reply_to(message, "No script loaded. Use /<macro_name> to load and run a specific macro.")
                return
        else:
            # Try to load the specified macro
            filepath = os.path.join(SCRIPTS_DIR, f"{macro_name}.json")
            if os.path.exists(filepath):
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        script_data = json.load(f)
                    engine.load_script(script_data)
                except Exception as e:
                    tbot.reply_to(message, f"Failed to load macro {macro_name}: {e}")
                    return
            else:
                tbot.reply_to(message, f"Macro '{macro_name}' not found. Check if it's saved in '{SCRIPTS_DIR}'.")
                return
        
        if engine.is_running:
            tbot.reply_to(message, "Macro is already running. Please /stop first.")
            return

        success = engine.start("step_1", schedule_config=schedule_cfg)
        if success:
            display_name = "current script" if macro_name == "startbot" else macro_name
            if schedule_cfg:
                rules_str = " | ".join([f"{r['type'].upper()}{r['start_min']}" for r in schedule_cfg['rules']])
                tbot.reply_to(message, f"✅ Macro '{display_name}' scheduled.\nSlots: {rules_str}\nDuration: {schedule_cfg['duration']}m")
            else:
                tbot.reply_to(message, f"✅ Macro '{display_name}' started remotely.")
        else:
            tbot.reply_to(message, "Failed to start. Script might be invalid or missing 'step_1'.")

def run_bot_polling():
    while True:
        if bot:
            try:
                bot.polling(none_stop=True, timeout=20)
            except Exception as e:
                print(f"Telegram polling error: {e}")
                time.sleep(5)
        else:
            time.sleep(5)
            
load_telegram_config()
bot_thread = threading.Thread(target=run_bot_polling, daemon=True)
bot_thread.start()

def on_macro_finish():
    chat_id = telegram_config.get("chat_id")
    if bot and chat_id:
        try:
            bot.send_message(chat_id, "✅ Macro has finished running!")
            threading.Thread(target=send_debug_images, args=(chat_id,), daemon=True).start()
        except Exception:
            pass

engine.on_finish_callback = on_macro_finish

class TelegramConfigRequest(BaseModel):
    bot_token: str
    chat_id: str

@app.post("/save_telegram_config")
def save_telegram_config(req: TelegramConfigRequest):
    global bot
    telegram_config["bot_token"] = req.bot_token
    telegram_config["chat_id"] = req.chat_id
    with open("telegram_config.json", "w", encoding="utf-8") as f:
        json.dump(telegram_config, f, indent=4)
    if req.bot_token:
        if bot:
            try:
                bot.stop_polling()
            except Exception:
                pass
        bot = telebot.TeleBot(req.bot_token)
        setup_telegram_handlers(bot)
    return {"message": "Telegram config saved"}

@app.get("/get_telegram_config")
def get_telegram_config():
    return telegram_config

class ScriptRequest(BaseModel):
    script: Dict[str, Any]

class SaveScriptRequest(BaseModel):
    filename: str
    script: Dict[str, Any]

class StartRequest(BaseModel):
    start_step: str = "step_1"
    rest_interval_min: float = 0.0
    rest_duration_sec: float = 0.0
    stop_delay_steps: int = 0

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
    
    success = engine.start(req.start_step, req.rest_interval_min, req.rest_duration_sec, req.stop_delay_steps)
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
