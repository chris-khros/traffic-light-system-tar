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
MQTT_BROKER = '192.168.0.104'
MQTT_PORT = 1883

# Create violations folder if not exists
if not os.path.exists("violations"):
    os.makedirs("violations")

class TrafficSystemUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Smart Traffic Light System")
        self.root.geometry("1200x800")
        self.root.resizable(True, True)
        
        # Initialize camera to None first
        self.cam = None
        
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
        self.setup_camera()
        
        # Create UI
        self.create_ui()
        
        # Connect to MQTT after UI is created
        self.connect_mqtt()
        
        # Start threads
        self.camera_thread = threading.Thread(target=self.camera_loop, daemon=True)
        self.camera_thread.start()
        
        # Start updating UI
        self.update_ui()

    def setup_camera(self):
        """Setup the camera for capturing violations"""
        try:
            self.cam = cv2.VideoCapture(0)
            if not self.cam.isOpened():
                messagebox.showerror("Error", "Could not open camera. UI will start without camera feed.")
                self.cam = None
        except Exception as e:
            messagebox.showerror("Error", f"Camera error: {str(e)}")
            self.cam = None

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
            self.crosswalk_status = payload
        
        elif topic == 'traffic/violation':
            if payload == 'RED_VIOLATION':
                print("Violation detected! Handling violation...")
                self.handle_violation()

    def handle_violation(self):
        """Handle a red light violation"""
        if self.cam is None:
            print("Camera not available for capturing violation")
            return
            
        ret, frame = self.cam.read()
        if not ret:
            print("Failed to capture image for violation")
            return
            
        # Save image
        now = datetime.now()
        filename = now.strftime("violations/violation_%Y%m%d_%H%M%S.jpg")
        cv2.imwrite(filename, frame)
        print(f"Saved violation image to {filename}")
        
        # Detect color
        color = self.better_simple_color_detect(frame)
        print(f"Detected vehicle color: {color}")
        
        # Upload to Firebase
        self.upload_violation(color, filename)
        
        # Update violations list
        violation_entry = {
            'color': color,
            'date': now.strftime("%Y-%m-%d"),
            'time': now.strftime("%H:%M:%S"),
            'image_filename': filename
        }
        self.violations.insert(0, violation_entry)  # Insert at the beginning for newest first
        
        # Update the violations text area
        self.update_violations_list()

    def better_simple_color_detect(self, image):
        """Simple color detection focusing on center of image"""
        h, w, _ = image.shape
        center_crop = image[h//3:h*2//3, w//3:w*2//3]
        
        # Increase brightness slightly
        center_crop = cv2.convertScaleAbs(center_crop, alpha=1.2, beta=30)
        
        # Average color
        avg_color_per_row = np.average(center_crop, axis=0)
        avg_color = np.average(avg_color_per_row, axis=0)
        
        b, g, r = avg_color
        print(f"Average BGR values: {b:.2f}, {g:.2f}, {r:.2f}")
        
        # Thresholds
        if r > 120 and r > g + 30 and r > b + 30:
            return "Red"
        elif b > 120 and b > r + 30 and b > g + 30:
            return "Blue"
        elif g > 120 and g > r + 30 and g > b + 30:
            return "Green"
        elif r > 150 and g > 150 and b < 100:
            return "Yellow"
        elif r < 80 and g < 80 and b < 80:
            return "Black"
        elif r > 180 and g > 180 and b > 180:
            return "White"
        else:
            return "Unknown"

    def upload_violation(self, color_detected, image_filename):
        """Upload violation details to Firebase"""
        try:
            now = datetime.now()
            data = {
                'color': color_detected,
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
        left_panel.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5, pady=5)
        
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
        
        # Distance sensor
        ttk.Label(status_frame, text="Vehicle Distance:").grid(row=3, column=0, sticky=tk.W, pady=2)
        self.distance_label = ttk.Label(status_frame, text="0 cm")
        self.distance_label.grid(row=3, column=1, sticky=tk.W, pady=2)
        
        # Crosswalk status
        ttk.Label(status_frame, text="Crosswalk Status:").grid(row=4, column=0, sticky=tk.W, pady=2)
        self.crosswalk_label = ttk.Label(status_frame, text="Clear")
        self.crosswalk_label.grid(row=4, column=1, sticky=tk.W, pady=2)
        
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
        camera_frame.pack(fill=tk.X, pady=5)
        
        self.camera_label = ttk.Label(camera_frame)
        self.camera_label.pack(pady=5)
        
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
            entry = f"Date: {v.get('date', 'Unknown')} | Time: {v.get('time', 'Unknown')} | Color: {v.get('color', 'Unknown')}\n"
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

    def camera_loop(self):
        """Thread for updating the camera feed"""
        if self.cam is None:
            return
            
        while True:
            try:
                ret, frame = self.cam.read()
                if ret:
                    # Resize frame for display
                    frame = cv2.resize(frame, (320, 240))
                    # Convert to RGB for tkinter
                    cv2image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    img = Image.fromarray(cv2image)
                    imgtk = ImageTk.PhotoImage(image=img)
                    
                    # Update camera label
                    self.camera_label.imgtk = imgtk
                    self.camera_label.configure(image=imgtk)
            except Exception as e:
                print(f"Camera error: {str(e)}")
                
            time.sleep(0.1)  # Small delay to reduce CPU usage

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
        if self.cam is not None:
            self.cam.release()
        self.mqtt_client.loop_stop()
        self.root.destroy()

if __name__ == "__main__":
    root = tk.Tk()
    app = TrafficSystemUI(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop() 