import cv2
import numpy as np
import os
import paho.mqtt.client as mqtt
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime

# 1. Setup Firebase
cred = credentials.Certificate("traffic-light-system-23d76-firebase-adminsdk-fbsvc-8e9cd5da24.json")  # <-- your Firebase key path
firebase_admin.initialize_app(cred)
db = firestore.client()

# 2. Setup Camera
cam = cv2.VideoCapture(0)

# 3. Create 'violations' folder if not exists
if not os.path.exists("violations"):
    os.makedirs("violations")

# 4. Setup MQTT
MQTT_BROKER = '192.168.0.104'
MQTT_TOPIC = 'traffic/violation'

def better_simple_color_detect(image):
    """Simple color detection focusing on center of image and handling weaker lighting."""
    h, w, _ = image.shape
    center_crop = image[h//3:h*2//3, w//3:w*2//3]  # Only the center area

    # Optional: Increase brightness slightly to help weak lighting
    center_crop = cv2.convertScaleAbs(center_crop, alpha=1.2, beta=30)

    # Average color
    avg_color_per_row = np.average(center_crop, axis=0)
    avg_color = np.average(avg_color_per_row, axis=0)

    b, g, r = avg_color
    print(f"Average Center Color BGR: {b:.2f}, {g:.2f}, {r:.2f}")

    # Thresholds (more tolerant for weaker light)
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

def upload_violation(color_detected, image_filename):
    """Upload violation details to Firebase."""
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

def save_violation_image(frame):
    """Save the captured image locally with timestamp."""
    now = datetime.now()
    filename = now.strftime("violations/violation_%Y%m%d_%H%M%S.jpg")
    cv2.imwrite(filename, frame)
    print(f"Violation image saved: {filename}")
    return filename

def on_message(client, userdata, msg):
    print(f"MQTT Message received: {msg.topic} {msg.payload.decode()}")

    if msg.payload.decode() == 'RED_VIOLATION':
        ret, frame = cam.read()
        if not ret:
            print("Failed to capture image")
            return

        # Save image
        image_filename = save_violation_image(frame)

        # Detect color
        color = better_simple_color_detect(frame)
        print(f"Detected Color: {color}")

        # Display captured image for preview
        cv2.imshow("Violation Captured", frame)
        cv2.waitKey(5000)
        cv2.destroyAllWindows()

        # Upload to Firebase
        upload_violation(color, image_filename)

client = mqtt.Client()
client.on_message = on_message

client.connect(MQTT_BROKER, 1883, 60)
client.subscribe(MQTT_TOPIC)

print("Listening for violations...")
client.loop_forever()