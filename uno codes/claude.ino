#include <Servo.h>

// ── Pin definitions ──────────────────────────────────────────
const uint8_t trigPin   = 9;
const uint8_t echoPin   = 10;
const uint8_t servoPin  = 11;
const uint8_t buzzerPin = 12;

// ── Tuning constants ─────────────────────────────────────────
const uint8_t  SWEEP_START         = 0;
const uint8_t  SWEEP_END           = 180;
const uint8_t  STEP_DELAY          = 30;
const uint8_t  ANGLE_STEP          = 1;
const uint16_t DETECTION_THRESHOLD = 500;
const uint8_t  NUM_READINGS        = 8;
const uint16_t BEEP_DURATION       = 2000;
const uint16_t TRACKING_TIME_MS    = 1000;
const uint8_t  MAX_ANGLE_GAP       = 3;
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
  unsigned long duration = pulseIn(echoPin, HIGH, 20000);
  return (uint16_t)(duration * 17UL / 1000);
}

void finalizeCluster() {
  if (!cluster.active || cluster.count == 0) return;
  if (objectCount >= MAX_OBJECTS) return;

  DetectedObject &obj = objects[objectCount++];
  obj.spanStart    = cluster.startAngle;
  obj.spanEnd      = cluster.lastAngle;
  obj.avgDistance  = (uint16_t)(cluster.distSum / cluster.count);
  obj.readingCount = cluster.count;

  Serial.print(F("Obj #"));   Serial.print(objectCount);
  Serial.print(F(" span:"));  Serial.print(obj.spanStart);
  Serial.print(F("-"));       Serial.print(obj.spanEnd);
  Serial.print(F("deg dist:"));Serial.print(obj.avgDistance);
  Serial.print(F("cm pts:")); Serial.println(obj.readingCount);

  cluster.active = false;
}

// ── Core logic ────────────────────────────────────────────────
void sweepAndDetect() {
  objectCount    = 0;
  cluster.active = false;
  Serial.println(F("Sweeping..."));

  for (uint8_t angle = SWEEP_START; angle <= SWEEP_END; angle += ANGLE_STEP) {
    myServo.write(angle);
    delay(STEP_DELAY);

    uint16_t dist = getDistance();
    bool valid = (dist > 2 && dist < DETECTION_THRESHOLD);

    if (valid) {
      bool angleBreak = cluster.active && (angle - cluster.lastAngle > MAX_ANGLE_GAP);
      bool distBreak  = cluster.active &&
                        (abs((int16_t)dist - (int16_t)cluster.lastDist) > MAX_DIST_DIFF);

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
  Serial.println(F("Tracking..."));

  unsigned long trackStart = millis();

  for (uint8_t i = 0; i < objectCount; i++) {
    if (millis() - trackStart > 10000UL) break;

    uint8_t  ang      = (objects[i].spanStart + objects[i].spanEnd) / 2;
    uint16_t prevDist = objects[i].avgDistance;

    myServo.write(ang);
    delay(400);

    uint32_t total     = 0;
    uint8_t validReads = 0;

    for (uint8_t r = 0; r < NUM_READINGS; r++) {
      uint16_t d = getDistance();
      if (d > 2 && d < 400) {
        total += d;
        validReads++;
      }
      delay(TRACKING_TIME_MS / NUM_READINGS);
    }

    uint16_t currentDist = (validReads > 0) ? (uint16_t)(total / validReads) : prevDist;

    Serial.print(F("ang:")); Serial.print(ang);
    Serial.print(F(" prev:")); Serial.print(prevDist);
    Serial.print(F(" now:")); Serial.println(currentDist);

    if (currentDist + 3 < prevDist) {   // approaching
      tone(buzzerPin, 1000, BEEP_DURATION);
      delay(BEEP_DURATION);
      return;
    }
  }

  objectCount = 0;
}

// ── Arduino entry points ──────────────────────────────────────
void setup() {
  pinMode(trigPin, OUTPUT);
  pinMode(echoPin, INPUT);
  pinMode(buzzerPin, OUTPUT);
  myServo.attach(servoPin);
  Serial.begin(9600);
  myServo.write(90);
  delay(500);
}

void loop() {
  sweepAndDetect();
  trackObjects();
  delay(500);
}