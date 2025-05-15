import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import cv2
import numpy as np
import os
import paho.mqtt.client as mqtt
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime
import threading
import json
from PIL import Image, ImageTk
import time

# Firebase setup
cred = credentials.Certificate("traffic-light-system-23d76-firebase-adminsdk-fbsvc-8e9cd5da24.json")
firebase_admin.initialize_app(cred)
db = firestore.client()

# MQTT Configuration
MQTT_BROKER = '172.20.10.4'
MQTT_PORT = 1883

# Create violations folder if not exists
if not os.path.exists("violations"):
    os.makedirs("violations")

class TrafficSystemUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Smart Traffic Light System")
        self.root.geometry("1400x900")
        self.root.resizable(True, True)
        
        # Initialize camera to None first
        self.cam = None
        self.camera_index = 0 # Default camera index
        self.stop_camera_signal = threading.Event()
        
        # Initialize MQTT client
        self.mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)  # Updated to VERSION2
        self.mqtt_client.on_connect = self.on_connect
        self.mqtt_client.on_message = self.on_message
        
        # Variables for storing data
        self.traffic_phase = "Unknown"
        self.h_density = 0
        self.v_density = 0
        self.last_distance = 0
        self.crosswalk_status = "Clear"
        self.violations = []
        
        # Setup camera
        self.setup_camera(self.camera_index)
        
        # Create UI
        self.create_ui()
        
        # Connect to MQTT after UI is created
        self.connect_mqtt()
        
        # Start threads
        self.camera_thread = threading.Thread(target=self.camera_loop, daemon=True)
        self.camera_thread.start()
        
        # Start updating UI
        self.update_ui()

    def setup_camera(self, camera_index):
        """Setup the camera for capturing violations"""
        try:
            self.cam = cv2.VideoCapture(camera_index)
            if not self.cam.isOpened():
                messagebox.showerror("Error", f"Could not open camera index {camera_index}. UI will start without camera feed.")
                self.cam = None
                self.camera_label.configure(image=None) # Clear previous image
                self.camera_label.imgtk = None
            else:
                self.camera_index = camera_index # Store the successfully opened index
                print(f"Camera {camera_index} opened successfully.")
        except Exception as e:
            messagebox.showerror("Error", f"Camera error with index {camera_index}: {str(e)}")
            self.cam = None
            self.camera_label.configure(image=None) # Clear previous image
            self.camera_label.imgtk = None

    def connect_mqtt(self):
        """Connect to MQTT broker"""
        try:
            self.mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
            self.mqtt_client.loop_start()
            print(f"Connected to MQTT broker at {MQTT_BROKER}:{MQTT_PORT}")
        except Exception as e:
            print(f"Failed to connect to MQTT broker: {str(e)}")
            messagebox.showerror("Error", f"Failed to connect to MQTT broker: {str(e)}")

    def on_connect(self, client, userdata, flags, rc, properties=None):
        """Callback when connected to MQTT broker"""
        print(f"Connected with result code {rc}")
        # Subscribe to topics
        topics = [
            ('traffic/phase', 0),
            ('traffic/violation', 0),
            ('traffic/density', 0),
            ('traffic/distance', 0),
            ('traffic/crosswalk', 0)
        ]
        client.subscribe(topics)

    def on_message(self, client, userdata, msg):
        """Handle incoming MQTT messages"""
        topic = msg.topic
        payload = msg.payload.decode()
        print(f"Received: {topic} - {payload}")
        
        if topic == 'traffic/phase':
            self.traffic_phase = payload
            # Update crosswalk status based on phase
            if payload in ["H_GREEN", "H_YELLOW"]:
                self.crosswalk_status = "Clear"
            elif payload in ["V_GREEN", "V_YELLOW"]:
                self.crosswalk_status = "Not Clear"
        
        elif topic == 'traffic/density':
            try:
                density_data = json.loads(payload)
                self.h_density = density_data.get('H', 0)
                self.v_density = density_data.get('V', 0)
            except json.JSONDecodeError:
                print(f"Invalid JSON in density data: {payload}")
        
        elif topic == 'traffic/distance':
            try:
                distance_data = json.loads(payload)
                self.last_distance = distance_data.get('distance', 0)
            except json.JSONDecodeError:
                print(f"Invalid JSON in distance data: {payload}")
        
        elif topic == 'traffic/crosswalk':
            if payload == "PEDESTRIAN_WAITING":
                self.crosswalk_status = "Pedestrian Waiting"
            elif payload == "CROSSWALK_CLEAR":
                # Only update to Clear if we're in horizontal phase
                if self.traffic_phase in ["H_GREEN", "H_YELLOW"]:
                    self.crosswalk_status = "Clear"
                else:
                    self.crosswalk_status = "Not Clear"
        
        elif topic == 'traffic/violation':
            if payload == 'RED_VIOLATION':
                print("Violation detected! Handling violation...")
                self.handle_violation()

    def handle_violation(self):
        """Handle a red light violation"""
        if self.cam is None:
            print("Camera not available for capturing violation")
            return
        
        # Add 150ms delay before capturing
        time.sleep(0.15)  # 150ms delay
            
        ret, frame = self.cam.read()
        if not ret:
            print("Failed to capture image for violation")
            return
            
        # Save image
        now = datetime.now()
        filename = now.strftime("violations/violation_%Y%m%d_%H%M%S.jpg")
        cv2.imwrite(filename, frame)
        print(f"Saved violation image to {filename}")
        
        # Upload to Firebase
        self.upload_violation(filename)
        
        # Update violations list
        violation_entry = {
            'date': now.strftime("%Y-%m-%d"),
            'time': now.strftime("%H:%M:%S"),
            'image_filename': filename
        }
        self.violations.insert(0, violation_entry)  # Insert at the beginning for newest first
        
        # Update the violations text area
        self.update_violations_list()

    def upload_violation(self, image_filename):
        """Upload violation details to Firebase"""
        try:
            now = datetime.now()
            data = {
                'date': now.strftime("%Y-%m-%d"),
                'time': now.strftime("%H:%M:%S"),
                'image_filename': image_filename
            }
            doc_ref = db.collection('violations').document()
            doc_ref.set(data)
            print(f"Uploaded to Firebase: {data}")
        except Exception as e:
            print(f"Failed to upload to Firebase: {str(e)}")

    def create_ui(self):
        """Create the UI components"""
        # Main frame
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Create left panel (traffic light status and controls)
        left_panel = ttk.LabelFrame(main_frame, text="Traffic Control System", padding="10")
        left_panel.pack(side=tk.LEFT, fill=tk.BOTH, expand=False, padx=5, pady=5)
        
        # Traffic light status
        status_frame = ttk.LabelFrame(left_panel, text="Current Status", padding="10")
        status_frame.pack(fill=tk.X, pady=5)
        
        # Traffic light phase
        ttk.Label(status_frame, text="Traffic Phase:").grid(row=0, column=0, sticky=tk.W, pady=2)
        self.phase_label = ttk.Label(status_frame, text="Unknown", font=("Arial", 12, "bold"))
        self.phase_label.grid(row=0, column=1, sticky=tk.W, pady=2)
        
        # Traffic density
        ttk.Label(status_frame, text="Horizontal Density:").grid(row=1, column=0, sticky=tk.W, pady=2)
        self.h_density_label = ttk.Label(status_frame, text="0")
        self.h_density_label.grid(row=1, column=1, sticky=tk.W, pady=2)
        
        ttk.Label(status_frame, text="Vertical Density:").grid(row=2, column=0, sticky=tk.W, pady=2)
        self.v_density_label = ttk.Label(status_frame, text="0")
        self.v_density_label.grid(row=2, column=1, sticky=tk.W, pady=2)
        
        # Vehicle Proximity Sensor section
        proximity_frame = ttk.LabelFrame(left_panel, text="Vehicle Proximity Sensor", padding="10")
        proximity_frame.pack(fill=tk.X, pady=5)

        ttk.Label(proximity_frame, text="Vehicle Distance:").grid(row=0, column=0, sticky=tk.W, pady=2)
        self.distance_label = ttk.Label(proximity_frame, text="0 cm")
        self.distance_label.grid(row=0, column=1, sticky=tk.W, pady=2)

        self.white_line_warning_label = ttk.Label(proximity_frame, text="", font=("Arial", 10, "bold"), foreground="red")
        self.white_line_warning_label.grid(row=1, column=0, columnspan=2, sticky=tk.W, pady=2)

        # Crosswalk Status section
        crosswalk_info_frame = ttk.LabelFrame(left_panel, text="Crosswalk Status", padding="10")
        crosswalk_info_frame.pack(fill=tk.X, pady=5)

        ttk.Label(crosswalk_info_frame, text="Status:").grid(row=0, column=0, sticky=tk.W, pady=2)
        self.crosswalk_label = ttk.Label(crosswalk_info_frame, text="Clear")
        self.crosswalk_label.grid(row=0, column=1, sticky=tk.W, pady=2)
        
        # Traffic light visualization
        light_frame = ttk.LabelFrame(left_panel, text="Traffic Light Visualization", padding="10")
        light_frame.pack(fill=tk.X, pady=10)
        
        # Horizontal lights
        ttk.Label(light_frame, text="Horizontal").grid(row=0, column=0, padx=10)
        self.h_red = ttk.Label(light_frame, text="●", font=("Arial", 24), foreground="gray")
        self.h_red.grid(row=1, column=0, padx=10)
        self.h_yellow = ttk.Label(light_frame, text="●", font=("Arial", 24), foreground="gray")
        self.h_yellow.grid(row=2, column=0, padx=10)
        self.h_green = ttk.Label(light_frame, text="●", font=("Arial", 24), foreground="gray")
        self.h_green.grid(row=3, column=0, padx=10)
        
        # Vertical lights
        ttk.Label(light_frame, text="Vertical").grid(row=0, column=1, padx=10)
        self.v_red = ttk.Label(light_frame, text="●", font=("Arial", 24), foreground="gray")
        self.v_red.grid(row=1, column=1, padx=10)
        self.v_yellow = ttk.Label(light_frame, text="●", font=("Arial", 24), foreground="gray")
        self.v_yellow.grid(row=2, column=1, padx=10)
        self.v_green = ttk.Label(light_frame, text="●", font=("Arial", 24), foreground="gray")
        self.v_green.grid(row=3, column=1, padx=10)
        
        # Manual control
        control_frame = ttk.LabelFrame(left_panel, text="Manual Control", padding="10")
        control_frame.pack(fill=tk.X, pady=10)
        
        # Override buttons
        ttk.Button(control_frame, text="H_GREEN", command=lambda: self.override_phase("H_GREEN")).pack(side=tk.LEFT, padx=5)
        ttk.Button(control_frame, text="H_YELLOW", command=lambda: self.override_phase("H_YELLOW")).pack(side=tk.LEFT, padx=5)
        ttk.Button(control_frame, text="V_GREEN", command=lambda: self.override_phase("V_GREEN")).pack(side=tk.LEFT, padx=5)
        ttk.Button(control_frame, text="V_YELLOW", command=lambda: self.override_phase("V_YELLOW")).pack(side=tk.LEFT, padx=5)
        
        # Create right panel (camera feed and violations)
        right_panel = ttk.LabelFrame(main_frame, text="Monitoring System", padding="10")
        right_panel.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Camera feed
        camera_frame = ttk.LabelFrame(right_panel, text="Camera Feed", padding="10")
        camera_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        
        # Camera controls frame
        camera_controls = ttk.Frame(camera_frame)
        camera_controls.pack(fill=tk.X, pady=5)
        
        # Camera selection
        ttk.Label(camera_controls, text="Camera Index:").pack(side=tk.LEFT, padx=(0, 5))
        self.camera_index_entry = ttk.Entry(camera_controls, width=5)
        self.camera_index_entry.insert(0, str(self.camera_index))
        self.camera_index_entry.pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(camera_controls, text="Change Camera", command=self.change_camera).pack(side=tk.LEFT, padx=(0, 10))
        
        # Camera feed container
        self.camera_container = ttk.Frame(camera_frame)
        self.camera_container.pack(fill=tk.BOTH, expand=True, pady=5)
        
        self.camera_label = ttk.Label(self.camera_container)
        self.camera_label.pack(fill=tk.BOTH, expand=True)
        
        # Violations list
        violations_frame = ttk.LabelFrame(right_panel, text="Violations", padding="10")
        violations_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        
        self.violations_text = scrolledtext.ScrolledText(violations_frame, height=10)
        self.violations_text.pack(fill=tk.BOTH, expand=True)
        
        # Fetch recent violations from Firebase
        self.fetch_violations()
        
        # Status bar
        status_bar = ttk.Label(self.root, text="Ready. Waiting for events...", relief=tk.SUNKEN, anchor=tk.W)
        status_bar.pack(side=tk.BOTTOM, fill=tk.X)
        self.status_bar = status_bar

    def fetch_violations(self):
        """Fetch recent violations from Firebase"""
        try:
            # Get most recent 10 violations
            violations_ref = db.collection('violations').order_by('time', direction=firestore.Query.DESCENDING).limit(10)
            docs = violations_ref.get()
            
            self.violations = []
            for doc in docs:
                self.violations.append(doc.to_dict())
            
            self.update_violations_list()
        except Exception as e:
            print(f"Failed to fetch violations: {str(e)}")

    def update_violations_list(self):
        """Update the violations list in the UI"""
        self.violations_text.delete(1.0, tk.END)
        
        if not self.violations:
            self.violations_text.insert(tk.END, "No violations recorded.")
            return
            
        for v in self.violations:
            entry = f"Date: {v.get('date', 'Unknown')} | Time: {v.get('time', 'Unknown')}\n"
            self.violations_text.insert(tk.END, entry)
    
    def override_phase(self, phase):
        """Override the traffic light phase"""
        try:
            self.mqtt_client.publish("traffic/override", phase)
            self.status_bar.config(text=f"Override sent: {phase}")
            print(f"Published override: {phase}")
        except Exception as e:
            print(f"Failed to override phase: {str(e)}")
            messagebox.showerror("Error", f"Failed to override phase: {str(e)}")

    def change_camera(self):
        """Change the active camera source"""
        try:
            new_index_str = self.camera_index_entry.get()
            new_index = int(new_index_str)
        except ValueError:
            messagebox.showerror("Error", "Invalid camera index. Please enter a number.")
            return

        if new_index == self.camera_index and self.cam and self.cam.isOpened():
            messagebox.showinfo("Info", f"Camera index {new_index} is already active.")
            return

        # Signal camera loop to stop
        self.stop_camera_signal.set()
        if self.camera_thread and self.camera_thread.is_alive():
            self.camera_thread.join(timeout=1.5) # Wait for the thread to finish

        # Release old camera
        if self.cam is not None:
            self.cam.release()
            self.cam = None
        
        # Clear the camera label before trying to set up a new one
        self.camera_label.configure(image=None)
        self.camera_label.imgtk = None

        # Reset signal and setup new camera
        self.stop_camera_signal.clear()
        self.setup_camera(new_index) # This will update self.camera_index if successful

        if self.cam and self.cam.isOpened():
            # Update entry with the actually used index
            self.camera_index_entry.delete(0, tk.END)
            self.camera_index_entry.insert(0, str(self.camera_index))
            
            # Restart camera thread
            self.camera_thread = threading.Thread(target=self.camera_loop, daemon=True)
            self.camera_thread.start()
            self.status_bar.config(text=f"Switched to camera index {self.camera_index}")
            print(f"Successfully switched to camera index {self.camera_index}")
        else:
            self.status_bar.config(text=f"Failed to open camera index {new_index}. Try another.")
            # If setup_camera failed, it already showed an error. 
            # We might want to revert to the old index if possible or indicate no camera.
            # For now, we just show no feed.
            self.camera_index_entry.delete(0, tk.END)
            self.camera_index_entry.insert(0, str(self.camera_index)) # Show last successful index

    def camera_loop(self):
        """Thread for updating the camera feed"""
        print("Camera loop started.")
        while not self.stop_camera_signal.is_set():
            if self.cam is None or not self.cam.isOpened():
                if hasattr(self, 'camera_label') and self.camera_label.winfo_exists():
                    if self.camera_label.cget("image") != "":
                        self.camera_label.configure(image=None)
                        self.camera_label.imgtk = None
                time.sleep(0.5)
                continue

            try:
                ret, frame = self.cam.read()
                if ret:
                    # Resize frame for display (increased size)
                    frame_resized = cv2.resize(frame, (640, 480))
                    
                    # Convert to RGB for tkinter
                    cv2image = cv2.cvtColor(frame_resized, cv2.COLOR_BGR2RGB)
                    img = Image.fromarray(cv2image)
                    imgtk = ImageTk.PhotoImage(image=img)
                    
                    if hasattr(self, 'camera_label') and self.camera_label.winfo_exists():
                        self.camera_label.imgtk = imgtk
                        self.camera_label.configure(image=imgtk)
                else:
                    print("Failed to read frame from camera.")
                    if hasattr(self, 'camera_label') and self.camera_label.winfo_exists():
                        if self.camera_label.cget("image") != "":
                            self.camera_label.configure(image=None)
                            self.camera_label.imgtk = None
                    time.sleep(0.1)
            except Exception as e:
                print(f"Camera loop error: {str(e)}")
                if hasattr(self, 'camera_label') and self.camera_label.winfo_exists():
                    if self.camera_label.cget("image") != "":
                        self.camera_label.configure(image=None)
                        self.camera_label.imgtk = None
                time.sleep(0.5)
                
            time.sleep(0.03)  # ~30 FPS
        print("Camera loop stopped.")

    def update_ui(self):
        """Update UI elements with current data"""
        # Update phase label
        self.phase_label.config(text=self.traffic_phase)
        
        # Update density labels
        self.h_density_label.config(text=str(self.h_density))
        self.v_density_label.config(text=str(self.v_density))
        
        # Update distance label
        self.distance_label.config(text=f"{self.last_distance} cm")
        
        # Update crosswalk label
        self.crosswalk_label.config(text=self.crosswalk_status)
        
        # Update white line warning label - only for vertical red light
        if (self.traffic_phase in ["H_GREEN", "H_YELLOW"] and  # Vertical lane has red light
            self.last_distance > 0 and self.last_distance <= 15):
            self.white_line_warning_label.config(text="DANGER: Car past white line!")
        else:
            self.white_line_warning_label.config(text="")
        
        # Update traffic light visualization
        # Reset all lights to gray
        self.h_red.config(foreground="gray")
        self.h_yellow.config(foreground="gray")
        self.h_green.config(foreground="gray")
        self.v_red.config(foreground="gray")
        self.v_yellow.config(foreground="gray")
        self.v_green.config(foreground="gray")
        
        # Set active lights based on current phase
        if self.traffic_phase == "H_GREEN":
            self.h_green.config(foreground="green")
            self.v_red.config(foreground="red")
        elif self.traffic_phase == "H_YELLOW":
            self.h_yellow.config(foreground="yellow")
            self.v_red.config(foreground="red")
        elif self.traffic_phase == "V_GREEN":
            self.v_green.config(foreground="green")
            self.h_red.config(foreground="red")
        elif self.traffic_phase == "V_YELLOW":
            self.v_yellow.config(foreground="yellow")
            self.h_red.config(foreground="red")
        
        # Schedule the next update
        self.root.after(500, self.update_ui)

    def on_closing(self):
        """Handle window closing"""
        print("Closing application...")
        self.stop_camera_signal.set() # Signal camera loop to stop
        
        if self.camera_thread and self.camera_thread.is_alive():
            print("Waiting for camera thread to join...")
            self.camera_thread.join(timeout=1.5) # Wait for camera thread to finish
        
        if self.cam is not None:
            print("Releasing camera...")
            self.cam.release()
        
        if self.mqtt_client:
            print("Stopping MQTT client loop...")
            self.mqtt_client.loop_stop()
        
        print("Destroying root window...")
        self.root.destroy()

if __name__ == "__main__":
    root = tk.Tk()
    app = TrafficSystemUI(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop() 