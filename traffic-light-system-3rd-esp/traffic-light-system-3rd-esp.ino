#include <WiFi.h>
#include <PubSubClient.h>

// ——— Wi-Fi & MQTT ——————————————————————
const char* ssid        = "Chris";
const char* password    = "123456789";
const char* mqtt_server = "172.20.10.4";

WiFiClient espClient;
PubSubClient client(espClient);

// ——— IR SENSOR PINS —————————————————————
const int ir1 = 12;  // horizontal lane A
const int ir2 = 13;  // horizontal lane B
const int ir3 = 14;  // vertical lane A
const int ir4 = 15;  // vertical lane B

// ——— TRAFFIC LIGHT PINS ————————————————
const int green1  = 23;   // Horizontal green
const int yellow1 = 22;   // Horizontal yellow
const int red1    = 21;   // Horizontal red

const int green2  = 19;   // Vertical green
const int yellow2 = 18;   // Vertical yellow
const int red2    = 5;    // Vertical red

// ——— Timing Parameters ————————————————————
const unsigned long yellowDuration = 3000;   // 3s yellow
const unsigned long minGreen      = 5000;   // 5s minimum green
const unsigned long maxGreen      = 20000;  // 20s maximum green
const unsigned long densityPublishInterval = 1000; // 1s between density updates
unsigned long lastDensityPublish = 0;

// State machine phases
enum Phase { H_GREEN=0, H_YELLOW, V_GREEN, V_YELLOW };
Phase currentPhase = H_GREEN;
bool pedestrianWaiting = false;

unsigned long phaseStart = 0;

// ——— MQTT Topics ————————————————————————
const char* topicDensity    = "traffic/density";
const char* topicPhase      = "traffic/phase";
const char* topicOverride   = "traffic/override";
const char* topicCrosswalk  = "traffic/crosswalk";

// ——— MQTT Callback ——————————————————————
void mqttCallback(char* topic, byte* payload, unsigned int length) {
  // Null-terminate and convert to String
  String msg;
  for (int i = 0; i < length; i++) msg += char(payload[i]);
  Serial.printf("MQTT ← %s : %s\n", topic, msg.c_str());

  // Handle override commands
  if (String(topic) == topicOverride) {
    if (msg == "H_GREEN")      currentPhase = H_GREEN;
    else if (msg == "H_YELLOW") currentPhase = H_YELLOW;
    else if (msg == "V_GREEN")  currentPhase = V_GREEN;
    else if (msg == "V_YELLOW") currentPhase = V_YELLOW;
    phaseStart = millis();
    applyPhase(currentPhase);
  }
  
  // Handle crosswalk notifications
  else if (String(topic) == topicCrosswalk) {
    if (msg == "PEDESTRIAN_WAITING") {
      pedestrianWaiting = true;
      Serial.println("Pedestrian waiting detected - will prioritize vertical green");
      
      // If we're in horizontal green, we should transition to yellow soon
      if (currentPhase == H_GREEN) {
        // Only force transition if we've been in this phase for at least minimum time
        unsigned long elapsed = millis() - phaseStart;
        if (elapsed >= minGreen) {
          currentPhase = H_YELLOW;
          phaseStart = millis();
          applyPhase(currentPhase);
        }
      }
    }
    else if (msg == "CROSSWALK_CLEAR") {
      pedestrianWaiting = false;
    }
  }
}

void setup() {
  Serial.begin(115200);
  setup_wifi();

  client.setServer(mqtt_server, 1883);
  client.setCallback(mqttCallback);

  // Connect and subscribe
  reconnect();

  // IR sensors
  pinMode(ir1, INPUT);
  pinMode(ir2, INPUT);
  pinMode(ir3, INPUT);
  pinMode(ir4, INPUT);

  // Lights
  for (int p : {green1,yellow1,red1,green2,yellow2,red2})
    pinMode(p, OUTPUT);

  // initialize all red
  digitalWrite(red1, HIGH);
  digitalWrite(red2, HIGH);
  phaseStart = millis();
  lastDensityPublish = millis();
}

void setup_wifi() {
  Serial.print("Wi-Fi → ");
  WiFi.begin(ssid,password);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println(" OK");
  Serial.print("IP: "); Serial.println(WiFi.localIP());
}

void loop() {
  if (!client.connected()) reconnect();
  client.loop();

  unsigned long now = millis();

  // read densities
  int horCount = (digitalRead(ir1)==LOW) + (digitalRead(ir2)==LOW);
  int verCount = (digitalRead(ir3)==LOW) + (digitalRead(ir4)==LOW);

  // Publish density at regular intervals (not every loop)
  if (now - lastDensityPublish >= densityPublishInterval) {
    // Publish density as JSON-like string
    char buf[64];
    snprintf(buf, sizeof(buf), "{\"H\":%d,\"V\":%d}", horCount, verCount);
    client.publish(topicDensity, buf);
    lastDensityPublish = now;
  }

  unsigned long elapsed = now - phaseStart;
  unsigned long phaseDuration = getPhaseDuration(currentPhase, horCount, verCount);

  // time to advance?
  if (elapsed >= phaseDuration) {
    // move to next phase
    currentPhase = Phase((currentPhase + 1) % 4);
    phaseStart = now;
    applyPhase(currentPhase);
    
    // Reset pedestrian waiting flag if we've reached V_GREEN
    if (currentPhase == V_GREEN) {
      pedestrianWaiting = false;
    }
  }
}

// determine how long the current phase lasts
unsigned long getPhaseDuration(Phase ph, int hCount, int vCount) {
  switch(ph) {
    case H_GREEN:
      // If pedestrian is waiting, use minimum green time
      if (pedestrianWaiting) {
        return minGreen;
      }
      // Otherwise stay green between min and max based on traffic
      return constrain(minGreen + hCount*2000, minGreen, maxGreen);
    
    case V_GREEN:
      // If pedestrian is waiting, use maximum green time to allow crossing
      if (pedestrianWaiting) {
        return maxGreen;
      }
      // Otherwise base on traffic density
      return constrain(minGreen + vCount*2000, minGreen, maxGreen);
    
    case H_YELLOW:
    case V_YELLOW:
      return yellowDuration;
  }
  return yellowDuration;
}

// drive the lights for each phase
void applyPhase(Phase ph) {
  // reset all
  digitalWrite(green1, LOW);
  digitalWrite(yellow1, LOW);
  digitalWrite(red1,   LOW);
  digitalWrite(green2, LOW);
  digitalWrite(yellow2, LOW);
  digitalWrite(red2,   LOW);

   // pick the new phase
  const char* phaseStr;
  switch(ph) {
    case H_GREEN:
      digitalWrite(green1, HIGH);
      digitalWrite(red2,   HIGH);
      phaseStr = "H_GREEN";
      break;
    case H_YELLOW:
      digitalWrite(yellow1, HIGH);
      digitalWrite(red2,    HIGH);
      phaseStr = "H_YELLOW";
      break;
    case V_GREEN:
      digitalWrite(green2, HIGH);
      digitalWrite(red1,   HIGH);
      phaseStr = "V_GREEN";
      break;
    case V_YELLOW:
      digitalWrite(yellow2, HIGH);
      digitalWrite(red1,     HIGH);
      phaseStr = "V_YELLOW";
      break;
  }

  // *** Publish retained phase immediately ***
  client.publish(topicPhase, phaseStr, true);
  Serial.printf("Published phase → %s\n", phaseStr);
}

void reconnect() {
  int attempts = 0;
  while (!client.connected() && attempts < 5) {
    attempts++;
    Serial.print("MQTT → ");
    // Create a unique client ID
    String clientId = "ESP32Client3-";
    clientId += String(random(0xffff), HEX);
    
    if (client.connect(clientId.c_str())) {
      Serial.println("Connected");
      
      // Subscribe to relevant topics
      client.subscribe(topicOverride);
      client.subscribe(topicCrosswalk);
      
      Serial.println("MQTT → Subscribed to topics");
    } else {
      Serial.print("Failed rc=");
      Serial.print(client.state());
      Serial.println(" retry in 5s");
      delay(5000);
    }
  }
}