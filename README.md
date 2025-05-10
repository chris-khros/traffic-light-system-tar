# Smart Traffic Light System

This project implements a complete traffic light system with violation detection, crosswalk sensing, and distance monitoring using ESP32 microcontrollers and a Python-based monitoring dashboard.

## Components

1. **Traffic Light Controller (ESP32)**: Controls the traffic light signals, detects vehicle density, and manages traffic flow.
2. **Violation & Sensor ESP32**: Detects red light violations, pedestrian crosswalk usage, and monitors vehicle distances.
3. **Monitoring Dashboard (Python)**: Provides a GUI to monitor and control the entire system.

## Requirements

### Hardware
- 2x ESP32 microcontrollers
- IR sensors for vehicle detection
- Ultrasonic sensor for distance measurement
- LEDs for traffic lights
- Webcam for violation capture

### Software
- Python 3.7+
- Libraries:
  - tkinter
  - OpenCV
  - NumPy
  - Paho MQTT
  - Firebase Admin
  - Pillow (PIL)

## Installation

1. Install required Python packages:
```
pip install opencv-python numpy paho-mqtt firebase-admin pillow
```

2. Upload the Arduino sketches to their respective ESP32 boards:
   - `traffic-light-system-3rd-esp.ino` to the traffic light controller ESP32
   - `red-light-violation-crosswalk-distance.ino` to the violation detection ESP32

3. Configure the MQTT broker (default: 192.168.0.104) on all devices

4. Ensure Firebase credentials are properly set up (use the provided JSON file)

5.  npm install
    npm run

## Usage

1. Start the MQTT broker
2. Power up both ESP32 devices
3. Run the monitoring dashboard:
```
python traffic_system_ui.py
```

## Features

- Real-time monitoring of traffic light states
- Live camera feed for violation detection
- Traffic density monitoring
- Crosswalk pedestrian detection
- Vehicle distance warnings
- Manual traffic light phase override
- Violation logging to Firebase
- Visual traffic light representation

## MQTT Topics

- `traffic/phase`: Current traffic light phase
- `traffic/violation`: Red light violation notifications
- `traffic/density`: Traffic density data
- `traffic/distance`: Vehicle distance measurements
- `traffic/crosswalk`: Pedestrian crosswalk status
- `traffic/override`: Manual override commands

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Acknowledgments

- Based on a smart traffic light system for IoT applications
- Uses ESP32 for sensor integration and control 