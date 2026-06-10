// ═══════════════════════════════════════════════════════════════
//  Ultrasonic Radar — Arduino sketch
//  Serial protocol (115200 baud):
//    S,<angle>,<dist_cm>              per-angle sweep reading
//    T,<angle>,<prev_cm>,<now_cm>     tracking update per object
//    A                                approaching alert (buzzer fired)
// ═══════════════════════════════════════════════════════════════
#include <Servo.h>

// ── Pin definitions ──────────────────────────────────────────
const uint8_t trigPin   = 9;
const uint8_t echoPin   = 10;
const uint8_t servoPin  = 11;
const uint8_t buzzerPin = 12;

// ── Tuning constants ─────────────────────────────────────────
const uint8_t  SWEEP_START         = 0;
const uint8_t  SWEEP_END           = 180;
const uint8_t  STEP_DELAY          = 80;    // ms per step — HC-SR04 needs ~10ms settle; 40ms is solid
const uint8_t  ANGLE_STEP          = 1;
const uint16_t DETECTION_THRESHOLD = 150;   // cm — must match Python MAX_DISTANCE
const uint8_t  NUM_READINGS        = 6;
const uint16_t TRACKING_TIME_MS    = 800;
const uint8_t  MAX_ANGLE_GAP       = 5;
const uint8_t  MAX_DIST_DIFF       = 15;

// ── Data structures ───────────────────────────────────────────
Servo myServo;

struct DetectedObject {
  uint8_t  spanStart;
  uint8_t  spanEnd;
  uint16_t avgDistance;
  uint8_t  readingCount;
};

const uint8_t MAX_OBJECTS = 10;
DetectedObject objects[MAX_OBJECTS];
uint8_t objectCount = 0;

struct {
  bool     active;
  uint8_t  startAngle;
  uint8_t  lastAngle;
  uint16_t lastDist;
  uint32_t distSum;
  uint8_t  count;
} cluster;

// ── Helpers ───────────────────────────────────────────────────
uint16_t getDistance() {
  digitalWrite(trigPin, LOW);
  delayMicroseconds(2);
  digitalWrite(trigPin, HIGH);
  delayMicroseconds(10);
  digitalWrite(trigPin, LOW);
  unsigned long duration = pulseIn(echoPin, HIGH, 5400UL);
  if (duration == 0) return 0;
  // speed of sound ~343 m/s = 0.0343 cm/µs
  // distance = duration * 0.0343 / 2  →  duration * 343 / 20000
  return (uint16_t)(duration * 343UL / 20000UL);
}

void finalizeCluster() {
  if (!cluster.active || cluster.count == 0) return;
  if (objectCount >= MAX_OBJECTS) { cluster.active = false; return; }

  DetectedObject &obj = objects[objectCount++];
  obj.spanStart    = cluster.startAngle;
  obj.spanEnd      = cluster.lastAngle;
  obj.avgDistance  = (uint16_t)(cluster.distSum / cluster.count);
  obj.readingCount = cluster.count;
  cluster.active   = false;
}

// ── Core logic ────────────────────────────────────────────────
void sweepAndDetect() {
  objectCount    = 0;
  cluster.active = false;

  for (uint8_t angle = SWEEP_START; angle <= SWEEP_END; angle += ANGLE_STEP) {
    myServo.write(angle);
    delay(STEP_DELAY);

    uint16_t dist = getDistance();
    bool valid = (dist > 2 && dist < DETECTION_THRESHOLD);

    Serial.print(F("S,"));
    Serial.print(angle);
    Serial.print(F(","));
    Serial.println(valid ? dist : 0);

    if (valid) {
      bool angleBreak = cluster.active && (angle - cluster.lastAngle > MAX_ANGLE_GAP);
      bool distBreak  = cluster.active &&
                        (dist > cluster.lastDist + MAX_DIST_DIFF ||
                         cluster.lastDist > dist + MAX_DIST_DIFF);

      if (angleBreak || distBreak) finalizeCluster();

      if (!cluster.active) {
        cluster.active     = true;
        cluster.startAngle = angle;
        cluster.distSum    = 0;
        cluster.count      = 0;
      }
      cluster.lastAngle = angle;
      cluster.lastDist  = dist;
      cluster.distSum  += dist;
      cluster.count++;
    } else {
      if (cluster.active) finalizeCluster();
    }
  }
  if (cluster.active) finalizeCluster();
}

void trackObjects() {
  if (objectCount == 0) return;

  uint32_t trackStart = millis();

  for (uint8_t i = 0; i < objectCount; i++) {
    if (millis() - trackStart > 8000UL) break;

    uint8_t  ang         = (objects[i].spanStart + objects[i].spanEnd) / 2;
    uint16_t prevDist    = objects[i].avgDistance;
    uint16_t currentDist = prevDist;

    myServo.write(ang);
    delay(300);

    // ── Initial averaged reading ────────────────────────────
    uint32_t total     = 0;
    uint8_t  validReads = 0;
    for (uint8_t r = 0; r < NUM_READINGS; r++) {
      uint16_t d = getDistance();
      if (d > 2 && d < DETECTION_THRESHOLD) { total += d; validReads++; }
      delay(TRACKING_TIME_MS / NUM_READINGS);
    }
    if (validReads > 0) currentDist = (uint16_t)(total / validReads);

    Serial.print(F("T,"));
    Serial.print(ang);
    Serial.print(F(","));
    Serial.print(prevDist);
    Serial.print(F(","));
    Serial.println(currentDist);

    // ── Stare loop: hold on this object while it's approaching ──
    if (currentDist + 5 < prevDist) {
      while (true) {
        Serial.println(F("A"));
        tone(buzzerPin, 1000, 250);   // short repeating beep
        delay(400);

        uint16_t d    = getDistance();
        bool inRange  = (d > 2 && d < DETECTION_THRESHOLD);

        Serial.print(F("T,"));
        Serial.print(ang);
        Serial.print(F(","));
        Serial.print(currentDist);
        Serial.print(F(","));
        Serial.println(inRange ? d : 0);

        // Break when object stops closing in (within 5 cm tolerance) or leaves range
        if (!inRange || d >= currentDist - 5) break;

        currentDist = d;
      }
      noTone(buzzerPin);

      // Update stored distance so the next sweep starts from fresh baseline
      objects[i].avgDistance = currentDist;
    }
    // Fall through to next object naturally
  }
}

// ── Arduino entry points ──────────────────────────────────────
void setup() {
  pinMode(trigPin,   OUTPUT);
  pinMode(echoPin,   INPUT);
  pinMode(buzzerPin, OUTPUT);
  noTone(buzzerPin);    // ensure silent on boot
  myServo.attach(servoPin);
  Serial.begin(115200);
  myServo.write(90);
  delay(500);
}

void loop() {
  sweepAndDetect();
  trackObjects();
  delay(200);
}
