#include <WiFi.h>
#include <PubSubClient.h>

// ——— Wi-Fi & MQTT ——————————————————————
const char* ssid        = "chinkonfatt-2.4G";
const char* password    = "50105189";
const char* mqtt_server = "192.168.0.104";

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

// State machine phases
enum Phase { H_GREEN=0, H_YELLOW, V_GREEN, V_YELLOW };
Phase currentPhase = H_GREEN;

unsigned long phaseStart = 0;

// ——— MQTT Topics ————————————————————————
const char* topicDensity    = "traffic/density";
const char* topicPhase      = "traffic/phase";
const char* topicOverride   = "traffic/override";

// ——— MQTT Callback ——————————————————————
void mqttCallback(char* topic, byte* payload, unsigned int length) {
  // Null-terminate and convert to String
  String msg;
  for (int i = 0; i < length; i++) msg += char(payload[i]);
  Serial.printf("MQTT ← %s : %s\n", topic, msg.c_str());

  // Example override: if payload == "H_GREEN" force it
  if (String(topic) == topicOverride) {
    if (msg == "H_GREEN")      currentPhase = H_GREEN;
    else if (msg == "H_YELLOW") currentPhase = H_YELLOW;
    else if (msg == "V_GREEN")  currentPhase = V_GREEN;
    else if (msg == "V_YELLOW") currentPhase = V_YELLOW;
    phaseStart = millis();
    applyPhase(currentPhase);
  }
}

void setup() {
  Serial.begin(115200);
  setup_wifi();

  client.setServer(mqtt_server, 1883);
  client.setCallback(mqttCallback);

  // Subscribe to override topic
  if (client.connect("ESP32Client3")) {
    client.subscribe(topicOverride);
    Serial.println("MQTT → Subscribed to override");
  }

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

  // read densities
  int horCount = (digitalRead(ir1)==LOW) + (digitalRead(ir2)==LOW);
  int verCount = (digitalRead(ir3)==LOW) + (digitalRead(ir4)==LOW);

  // Publish density as JSON-like string
  char buf[64];
  snprintf(buf, sizeof(buf), "{\"H\":%d,\"V\":%d}", horCount, verCount);
  client.publish(topicDensity, buf);

  unsigned long now = millis();
  unsigned long elapsed = now - phaseStart;
  unsigned long phaseDuration = getPhaseDuration(currentPhase, horCount, verCount);

  // time to advance?
  if (elapsed >= phaseDuration) {
    // move to next phase
    currentPhase = Phase((currentPhase + 1) % 4);
    phaseStart = now;
    applyPhase(currentPhase);
  }
}

// determine how long the current phase lasts
unsigned long getPhaseDuration(Phase ph, int hCount, int vCount) {
  switch(ph) {
    case H_GREEN:
      // stay green between min and max based on traffic
      return constrain( minGreen + hCount*2000, minGreen, maxGreen );
    case V_GREEN:
      return constrain( minGreen + vCount*2000, minGreen, maxGreen );
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
  while (!client.connected()) {
    Serial.print("MQTT → ");
    if (client.connect("ESP32Client3")) {
      Serial.println("Connected");
    } else {
      Serial.print("Failed rc=");
      Serial.print(client.state());
      Serial.println(" retry in 5s");
      delay(5000);
    }
  }
}