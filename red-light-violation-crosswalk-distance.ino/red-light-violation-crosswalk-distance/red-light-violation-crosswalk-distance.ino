#include <WiFi.h>
#include <PubSubClient.h>

// ——— Wi-Fi & MQTT ——————————————————————
const char* ssid        = "Chris";
const char* password    = "123456789";
const char* mqtt_server = "172.20.10.4";

WiFiClient   wifiClient;
PubSubClient mqtt(wifiClient);

// ——— IR SENSOR (Red Light Violation) —————————————
const int irRedLight     = 15;     // IR beam just past the stop line
bool      lastIrHigh     = true;
unsigned long lastDebounce = 0;

// ——— CROSSWALK IR SENSOR ——————————————————
const int irCrosswalk    = 4;     // IR sensor for crosswalk detection
bool      lastCrosswalkIrHigh = true;
unsigned long lastCrosswalkDebounce = 0;
unsigned long crosswalkActiveTime = 0;
bool      crosswalkActive = false;
const unsigned long crosswalkDuration = 10000; // 10 seconds for crosswalk

// ——— ULTRASONIC SENSOR ————————————————————
const int ultrasonicPin = 13;     // Signal pin for ultrasonic sensor
const int maxDistance = 400;      // Maximum distance in cm
const int warningDistance = 150;  // Distance threshold for warning in cm
unsigned long lastDistanceCheck = 0;
const unsigned long distanceCheckInterval = 500; // Check every 500ms

// ——— MQTT TOPICS ————————————————————————
const char* topicPhase     = "traffic/phase";
const char* topicViolation = "traffic/violation";
const char* topicCrosswalk = "traffic/crosswalk";
const char* topicDistance  = "traffic/distance";
const char* topicOverride  = "traffic/override";

// tracks the latest retained phase
String currentPhase = "";

void mqttCallback(char* topic, byte* payload, unsigned int len) {
  String msg = "";
  for (unsigned i = 0; i < len; i++) {
    msg += char(payload[i]);
  }
  Serial.printf("MQTT ← %s : %s\n", topic, msg.c_str());
  
  if (String(topic) == topicPhase) {
    currentPhase = msg;
  }
}

void reconnect() {
  while (!mqtt.connected()) {
    Serial.print("MQTT→");
    if (mqtt.connect("ESP32_Sensors")) {
      Serial.println("connected");
      // subscribe to topics
      mqtt.subscribe(topicPhase);
    } else {
      Serial.print("fail rc="); Serial.print(mqtt.state());
      Serial.println(" retry in 3s");
      delay(3000);
    }
  }
}

// Function to read distance from ultrasonic sensor
int readUltrasonicDistance() {
  // Generate a 10-microsecond pulse to trigger the sensor
  pinMode(ultrasonicPin, OUTPUT);
  digitalWrite(ultrasonicPin, LOW);
  delayMicroseconds(2);
  digitalWrite(ultrasonicPin, HIGH);
  delayMicroseconds(10);
  digitalWrite(ultrasonicPin, LOW);
  
  // Switch to input to read the echo
  pinMode(ultrasonicPin, INPUT);
  
  // Measure the pulse width and calculate distance
  // Sound travels at 343 meters per second, so 1cm = 29.1µs round trip
  // We divide by 58 for cm (divide by 148 for inches)
  long duration = pulseIn(ultrasonicPin, HIGH, maxDistance * 58);
  if (duration == 0) {
    return maxDistance; // No echo received within timeout
  }
  
  int distance = duration / 58;
  return constrain(distance, 0, maxDistance);
}

void setup() {
  Serial.begin(115200);
  
  // Setup pins
  pinMode(irRedLight, INPUT_PULLUP);
  pinMode(irCrosswalk, INPUT_PULLUP);
  
  // connect Wi-Fi
  WiFi.begin(ssid, password);
  Serial.print("Wi-Fi→");
  while (WiFi.status() != WL_CONNECTED) {
    delay(200);
    Serial.print(".");
  }
  Serial.println(" OK");
  Serial.print("IP: "); Serial.println(WiFi.localIP());

  // setup MQTT
  mqtt.setServer(mqtt_server, 1883);
  mqtt.setCallback(mqttCallback);
  reconnect();
}

void loop() {
  if (!mqtt.connected()) reconnect();
  mqtt.loop();
  
  unsigned long currentMillis = millis();
  
  // 1. Handle Red Light Violation Detection
  bool redLightNowHigh = digitalRead(irRedLight);
  // on falling edge & debounce
  if (lastIrHigh && !redLightNowHigh && currentMillis - lastDebounce > 200) {
    lastDebounce = currentMillis;
    Serial.println("IR broken → checking phase…");

    // if horizontal light is RED (i.e. we're NOT in an H phase):
    if (currentPhase != "H_GREEN" && currentPhase != "H_YELLOW") {
      Serial.println("🚨 RED-LIGHT VIOLATION! 🚨");
      mqtt.publish(topicViolation, "RED_VIOLATION", true);
    } else {
      Serial.println("No violation; horizontal is " + currentPhase);
    }
  }
  lastIrHigh = redLightNowHigh;
  
  // 2. Handle Crosswalk Detection
  bool crosswalkNowHigh = digitalRead(irCrosswalk);
  // on falling edge & debounce (someone entered the crosswalk)
  if (lastCrosswalkIrHigh && !crosswalkNowHigh && currentMillis - lastCrosswalkDebounce > 200) {
    lastCrosswalkDebounce = currentMillis;
    Serial.println("Crosswalk IR broken → pedestrian detected");
    
    if (!crosswalkActive) {
      crosswalkActive = true;
      crosswalkActiveTime = currentMillis;
      
      // Request vertical traffic light to turn green
      if (currentPhase != "V_GREEN" && currentPhase != "V_YELLOW") {
        mqtt.publish(topicCrosswalk, "PEDESTRIAN_WAITING", true);
        Serial.println("Published: Pedestrian waiting at crosswalk");
        
        // Optional: You could also force a phase change through the override
        // mqtt.publish(topicOverride, "H_YELLOW", false);
      }
    }
  }
  lastCrosswalkIrHigh = crosswalkNowHigh;
  
  // Check if crosswalk active period has ended
  if (crosswalkActive && (currentMillis - crosswalkActiveTime > crosswalkDuration)) {
    crosswalkActive = false;
    mqtt.publish(topicCrosswalk, "CROSSWALK_CLEAR", true);
    Serial.println("Published: Crosswalk clear");
  }
  
  // 3. Handle Ultrasonic Distance Sensing (every 500ms)
  if (currentMillis - lastDistanceCheck >= distanceCheckInterval) {
    lastDistanceCheck = currentMillis;
    
    int distance = readUltrasonicDistance();
    Serial.printf("Distance: %d cm\n", distance);
    
    // Format distance as JSON
    char distanceBuf[32];
    snprintf(distanceBuf, sizeof(distanceBuf), "{\"distance\":%d}", distance);
    mqtt.publish(topicDistance, distanceBuf);
    
    // Warn about vehicles too close (collision risk)
    if (distance < warningDistance && distance > 0) {
      char warningBuf[48];
      snprintf(warningBuf, sizeof(warningBuf), "{\"warning\":true,\"distance\":%d}", distance);
      mqtt.publish(topicDistance, warningBuf);
      Serial.println("⚠️ Vehicle too close! ⚠️");
    }
  }
  
  // Short delay to prevent overwhelming the processor
  delay(10);
}