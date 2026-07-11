import ctypes
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass


import threading
import time
import cv2
import numpy as np
import mss
import pyautogui
from pynput import keyboard, mouse
import customtkinter as ctk
import tkinter as tk

pyautogui.PAUSE = 0  # Maximum speed for clicks

# Set up customtkinter appearance
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

class BotLogic:
    def __init__(self, log_callback, get_coordinates, get_delay, get_loops, get_stop_region, get_tolerance):
        self.log_callback = log_callback
        self.get_coordinates = get_coordinates
        self.get_delay = get_delay
        self.get_loops = get_loops
        self.get_stop_region = get_stop_region
        self.get_tolerance = get_tolerance
        
        self.stop_event = threading.Event()
        self.clicker_thread = None
        self.watcher_thread = None
        self.is_running = False

    def start(self):
        if self.is_running:
            return
            
        coords = self.get_coordinates()
        if not coords:
            self.log_callback("Error: No coordinates recorded.")
            return
            
        self.is_running = True
        self.stop_event.clear()
        
        self.log_callback("Starting Bot...")
        
        # Start Watcher if region selected
        stop_region = self.get_stop_region()
        if stop_region and stop_region.get('bbox'):
            self.watcher_thread = threading.Thread(target=self._watcher_loop, daemon=True)
            self.watcher_thread.start()
        else:
            self.log_callback("Warning: No stop region selected. Watcher disabled.")
            
        # Start Clicker
        self.clicker_thread = threading.Thread(target=self._clicker_loop, daemon=True)
        self.clicker_thread.start()

    def stop(self, reason="Stopped by user"):
        if not self.is_running:
            return
        self.stop_event.set()
        self.is_running = False
        self.log_callback(f"Bot Stopped: {reason}")

    def _clicker_loop(self):
        coords = self.get_coordinates()
        delay = self.get_delay()
        loops = self.get_loops()
        
        current_loop = 0
        while not self.stop_event.is_set():
            if loops > 0 and current_loop >= loops:
                self.log_callback("Completed all loops.")
                self.is_running = False
                break
                
            self.log_callback(f"--- Loop {current_loop + 1} ---")
            for i, (x, y) in enumerate(coords):
                if self.stop_event.is_set():
                    break
                    
                self.log_callback(f"Clicking Point {i+1}: ({x}, {y})")
                pyautogui.click(x, y)
                
                # Use wait for timeout so we can exit instantly if stop_event is set
                if self.stop_event.wait(delay):
                    break # stop_event was set!
                    
            current_loop += 1
            
        self.is_running = False

    def _watcher_loop(self):
        region_info = self.get_stop_region()
        if not region_info or 'bbox' not in region_info:
            return
            
        bbox = region_info['bbox'] # {'left': x, 'top': y, 'width': w, 'height': h}
        baseline = region_info['baseline'] # grayscale numpy array
        
        with mss.mss() as sct:
            while not self.stop_event.is_set():
                try:
                    # Grab screen
                    sct_img = sct.grab(bbox)
                    
                    # Convert to numpy array and grayscale
                    current_img = np.array(sct_img)
                    current_gray = cv2.cvtColor(current_img, cv2.COLOR_BGRA2GRAY)
                    
                    # Compare using absolute difference
                    diff = cv2.absdiff(baseline, current_gray)
                    
                    # Calculate percentage difference
                    diff_mean = np.mean(diff)
                    diff_percentage = (diff_mean / 255.0) * 100.0
                    
                    tolerance = self.get_tolerance()
                    
                    if diff_percentage > tolerance:
                        self.log_callback(f"Image changed! Diff: {diff_percentage:.2f}% > Tol: {tolerance:.2f}%")
                        self.stop("Image Stop Condition Triggered")
                        break
                except Exception as e:
                    self.log_callback(f"Watcher Error: {e}")
                    self.stop("Watcher Thread Error")
                    break
                    
                # 20 FPS roughly -> 50ms wait
                if self.stop_event.wait(0.05):
                    break

class OverlayWindow(tk.Toplevel):
    def __init__(self, master, on_complete):
        super().__init__(master)
        self.on_complete = on_complete
        
        # Use mss to get the full virtual screen bounding box (across all monitors)
        with mss.MSS() as sct:
            mon = sct.monitors[0]
            
        self.geometry(f"{mon['width']}x{mon['height']}+{mon['left']}+{mon['top']}")
        self.overrideredirect(True)
        self.attributes('-alpha', 0.3)
        self.attributes('-topmost', True)
        self.config(cursor="cross")
        
        self.canvas = tk.Canvas(self, bg='black', highlightthickness=0)
        self.canvas.pack(fill='both', expand=True)
        
        self.start_x = None
        self.start_y = None
        self.rect = None
        
        self.canvas.bind("<ButtonPress-1>", self.on_button_press)
        self.canvas.bind("<B1-Motion>", self.on_move_press)
        self.canvas.bind("<ButtonRelease-1>", self.on_button_release)
        
        # Press escape to cancel
        self.bind("<Escape>", lambda e: self._cancel())

    def on_button_press(self, event):
        self.start_x = event.x
        self.start_y = event.y
        self.start_x_root = event.x_root
        self.start_y_root = event.y_root
        self.rect = self.canvas.create_rectangle(self.start_x, self.start_y, self.start_x, self.start_y, outline='red', width=3, fill='gray')

    def on_move_press(self, event):
        cur_x, cur_y = (event.x, event.y)
        self.canvas.coords(self.rect, self.start_x, self.start_y, cur_x, cur_y)

    def on_button_release(self, event):
        end_x_root = event.x_root
        end_y_root = event.y_root
        
        left = min(self.start_x_root, end_x_root)
        top = min(self.start_y_root, end_y_root)
        width = abs(self.start_x_root - end_x_root)
        height = abs(self.start_y_root - end_y_root)
        
        if width > 0 and height > 0:
            bbox = {'left': left, 'top': top, 'width': width, 'height': height}
            try:
                # Capture baseline image immediately
                with mss.MSS() as sct:
                    sct_img = sct.grab(bbox)
                    baseline_bgra = np.array(sct_img)
                    baseline = cv2.cvtColor(baseline_bgra, cv2.COLOR_BGRA2GRAY)
                    
                self.on_complete({'bbox': bbox, 'baseline': baseline})
            except Exception as e:
                print(f"Error capturing baseline: {e}")
                self.on_complete(None)
        else:
            self.on_complete(None)
            
        self.destroy()
        
    def _cancel(self):
        self.on_complete(None)
        self.destroy()

class AutoClickerApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Advanced Auto Clicker")
        self.geometry("650x750")
        self.resizable(False, False)

        # State
        self.coordinates = []
        self.recording_mode = False
        self.stop_region_info = None
        self.bot = BotLogic(
            log_callback=self.log_message,
            get_coordinates=lambda: self.coordinates,
            get_delay=self.get_delay,
            get_loops=self.get_loops,
            get_stop_region=lambda: self.stop_region_info,
            get_tolerance=self.get_tolerance
        )

        # UI Layout Setup
        self.grid_columnconfigure(0, weight=1)
        
        # --- COORDINATES SECTION ---
        self.coord_frame = ctk.CTkFrame(self)
        self.coord_frame.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
        
        ctk.CTkLabel(self.coord_frame, text="Sequence Setup (Press F2 to Record)", font=("Arial", 16, "bold")).pack(pady=5)
        
        self.listbox_frame = ctk.CTkScrollableFrame(self.coord_frame, height=150)
        self.listbox_frame.pack(fill="x", padx=10, pady=5)
        
        btn_frame = ctk.CTkFrame(self.coord_frame, fg_color="transparent")
        btn_frame.pack(fill="x", padx=10, pady=5)
        
        self.record_btn = ctk.CTkButton(btn_frame, text="Record Coordinates (F2)", command=self.manual_record_click)
        self.record_btn.pack(side="left", padx=5, expand=True, fill="x")
        
        self.clear_btn = ctk.CTkButton(btn_frame, text="Clear All", command=self.clear_coords)
        self.clear_btn.pack(side="left", padx=5, expand=True, fill="x")

        # --- SETTINGS SECTION ---
        self.settings_frame = ctk.CTkFrame(self)
        self.settings_frame.grid(row=1, column=0, padx=10, pady=10, sticky="nsew")
        self.settings_frame.grid_columnconfigure(1, weight=1)
        
        ctk.CTkLabel(self.settings_frame, text="Settings", font=("Arial", 16, "bold")).grid(row=0, column=0, columnspan=2, pady=5)
        
        ctk.CTkLabel(self.settings_frame, text="Delay before next click (s):").grid(row=1, column=0, padx=10, pady=5, sticky="w")
        self.delay_entry = ctk.CTkEntry(self.settings_frame, width=100)
        self.delay_entry.insert(0, "1.0")
        self.delay_entry.grid(row=1, column=1, padx=10, pady=5, sticky="w")
        
        ctk.CTkLabel(self.settings_frame, text="Number of loops (0 = infinite):").grid(row=2, column=0, padx=10, pady=5, sticky="w")
        self.loops_entry = ctk.CTkEntry(self.settings_frame, width=100)
        self.loops_entry.insert(0, "0")
        self.loops_entry.grid(row=2, column=1, padx=10, pady=5, sticky="w")

        # --- WATCHER SECTION ---
        self.watcher_frame = ctk.CTkFrame(self)
        self.watcher_frame.grid(row=2, column=0, padx=10, pady=10, sticky="nsew")
        
        ctk.CTkLabel(self.watcher_frame, text="Real-Time Image Stop Condition", font=("Arial", 16, "bold")).pack(pady=5)
        
        self.region_btn = ctk.CTkButton(self.watcher_frame, text="Select Stop Region", command=self.select_stop_region)
        self.region_btn.pack(pady=5)
        
        self.region_status = ctk.CTkLabel(self.watcher_frame, text="Stop Region: Not Selected", text_color="gray")
        self.region_status.pack(pady=2)
        
        tol_frame = ctk.CTkFrame(self.watcher_frame, fg_color="transparent")
        tol_frame.pack(fill="x", padx=10, pady=5)
        ctk.CTkLabel(tol_frame, text="Tolerance/Sensitivity:").pack(side="left", padx=5)
        
        self.tolerance_var = tk.DoubleVar(value=5.0)
        self.tolerance_slider = ctk.CTkSlider(tol_frame, from_=0.0, to=20.0, variable=self.tolerance_var, command=self.update_tol_label)
        self.tolerance_slider.pack(side="left", padx=5, expand=True, fill="x")
        
        self.tol_label = ctk.CTkLabel(tol_frame, text="5.0%")
        self.tol_label.pack(side="left", padx=5)

        # --- CONTROLS SECTION ---
        self.controls_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.controls_frame.grid(row=3, column=0, padx=10, pady=10, sticky="nsew")
        
        self.start_stop_btn = ctk.CTkButton(self.controls_frame, text="START (F8)", font=("Arial", 18, "bold"), fg_color="green", hover_color="darkgreen", command=self.toggle_start_stop)
        self.start_stop_btn.pack(fill="x", pady=10, ipady=10)

        # --- CONSOLE SECTION ---
        self.console = ctk.CTkTextbox(self, height=150)
        self.console.grid(row=4, column=0, padx=10, pady=10, sticky="nsew")
        self.console.insert("0.0", "System initialized. Waiting for input...\n")
        self.console.configure(state="disabled")

        # Global Hotkey Listener
        self.keyboard_listener = keyboard.Listener(on_press=self.on_key_press)
        self.keyboard_listener.start()
        
        self.mouse_listener = mouse.Listener(on_click=self.on_mouse_click)
        self.mouse_listener.start()

    def update_tol_label(self, val):
        self.tol_label.configure(text=f"{val:.1f}%")

    def manual_record_click(self):
        self.recording_mode = True
        self.log_message("Recording mode: ON. Click anywhere or press F2 to capture.")

    def on_mouse_click(self, x, y, button, pressed):
        if self.recording_mode and pressed and button == mouse.Button.left:
            self.recording_mode = False
            self.record_current_position(x, y)

    def record_current_position(self, x=None, y=None):
        if x is None or y is None:
            x, y = pyautogui.position()
        # Thread-safe GUI update
        self.after(0, self._record_current_position_safe, x, y)
        
    def _record_current_position_safe(self, x, y):
        self.coordinates.append((x, y))
        self.log_message(f"Recorded point {len(self.coordinates)}: ({x}, {y})")
        self.update_listbox()

    def clear_coords(self):
        self.coordinates.clear()
        self.update_listbox()
        self.log_message("Cleared all coordinates.")

    def delete_coord(self, index):
        if 0 <= index < len(self.coordinates):
            self.coordinates.pop(index)
            self.update_listbox()
            self.log_message(f"Deleted point {index + 1}.")

    def update_listbox(self):
        for widget in self.listbox_frame.winfo_children():
            widget.destroy()
            
        for i, (x, y) in enumerate(self.coordinates):
            frame = ctk.CTkFrame(self.listbox_frame, fg_color="transparent")
            frame.pack(fill="x", pady=2)
            
            lbl = ctk.CTkLabel(frame, text=f"Point {i+1}: ({x}, {y})")
            lbl.pack(side="left", padx=5)
            
            del_btn = ctk.CTkButton(frame, text="Delete", width=60, fg_color="darkred", hover_color="red", command=lambda idx=i: self.delete_coord(idx))
            del_btn.pack(side="right", padx=5)

    def select_stop_region(self):
        def on_region_selected(region_info):
            if region_info:
                self.stop_region_info = region_info
                bbox = region_info['bbox']
                self.region_status.configure(text=f"Stop Region: {bbox['width']}x{bbox['height']} at ({bbox['left']}, {bbox['top']})", text_color="white")
                self.log_message("Stop Region selected and baseline captured.")
            else:
                self.log_message("Stop Region selection cancelled.")
                
        self.log_message("Please draw a bounding box on the screen (Press ESC to cancel)...")
        OverlayWindow(self, on_region_selected)

    def get_delay(self):
        try:
            val = float(self.delay_entry.get())
            return max(0.0, val)
        except ValueError:
            return 1.0

    def get_loops(self):
        try:
            val = int(self.loops_entry.get())
            return max(0, val)
        except ValueError:
            return 0

    def get_tolerance(self):
        return self.tolerance_var.get()

    def toggle_start_stop(self):
        self.after(0, self._toggle_start_stop_safe)

    def _toggle_start_stop_safe(self):
        if self.bot.is_running:
            self.bot.stop()
            self.start_stop_btn.configure(text="START (F8)", fg_color="green", hover_color="darkgreen")
        else:
            if not self.coordinates:
                self.log_message("Error: Cannot start without coordinates.")
                return
            self.bot.start()
            self.start_stop_btn.configure(text="STOP (F8)", fg_color="red", hover_color="darkred")
            
            # Polling to reset the UI button if the bot stops due to image change
            self.after(500, self.check_bot_status)

    def check_bot_status(self):
        if not self.bot.is_running:
            self.start_stop_btn.configure(text="START (F8)", fg_color="green", hover_color="darkgreen")
        else:
            self.after(500, self.check_bot_status)

    def log_message(self, msg):
        self.after(0, self._log_message_safe, msg)
        
    def _log_message_safe(self, msg):
        self.console.configure(state="normal")
        ts = time.strftime("%H:%M:%S")
        self.console.insert("end", f"[{ts}] {msg}\n")
        self.console.see("end")
        self.console.configure(state="disabled")

    def on_key_press(self, key):
        try:
            if key == keyboard.Key.f2:
                if self.recording_mode:
                    self.recording_mode = False
                    self.record_current_position()
            elif key == keyboard.Key.f8:
                self.toggle_start_stop()
        except AttributeError:
            pass

    def on_closing(self):
        self.bot.stop("Application closing")
        self.keyboard_listener.stop()
        self.mouse_listener.stop()
        self.destroy()

if __name__ == "__main__":
    app = AutoClickerApp()
    app.protocol("WM_DELETE_WINDOW", app.on_closing)
    app.mainloop()
