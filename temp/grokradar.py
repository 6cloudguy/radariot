import pygame
import serial
import serial.tools.list_ports
import time
import math
import sys

# ========================= CONFIG =========================
SERIAL_PORT   = None      # Set to "COM3" / "/dev/ttyACM0" to skip auto-detect
BAUD_RATE     = 9600

WIDTH, HEIGHT = 900, 680
# Arc opens upward → center sits near the bottom
RADAR_CENTER  = (WIDTH // 2, HEIGHT - 60)
RADAR_RADIUS  = 530
MAX_DISTANCE  = 150       # cm — must match Arduino DETECTION_THRESHOLD
FADE_SECONDS  = 8         # how long a trail segment stays visible

# ──────────────────────────────────────────────────────────
def find_serial_port():
    if SERIAL_PORT:
        return SERIAL_PORT
    ports = list(serial.tools.list_ports.comports())
    arduino_ports = [p.device for p in ports
                     if "Arduino" in (p.description or "")
                     or "USB"     in (p.description or "")
                     or "ACM"     in p.device
                     or "usbmodem" in p.device]
    if arduino_ports:
        print(f"Auto-detected port: {arduino_ports[0]}")
        return arduino_ports[0]
    if ports:
        print("Available ports:")
        for i, p in enumerate(ports):
            print(f"  [{i}] {p.device}  — {p.description}")
        idx = input("Enter port number: ").strip()
        return ports[int(idx)].device
    print("ERROR: No serial ports found.")
    sys.exit(1)

# ──────────────────────────────────────────────────────────
pygame.init()
screen = pygame.display.set_mode((WIDTH, HEIGHT))
pygame.display.set_caption("Ultrasonic Radar")
clock  = pygame.time.Clock()

font_sm = pygame.font.SysFont("consolas", 14)
font_md = pygame.font.SysFont("consolas", 18)
font_lg = pygame.font.SysFont("consolas", 22, bold=True)

port = find_serial_port()
try:
    ser = serial.Serial(port, BAUD_RATE, timeout=0.05)
    time.sleep(2)
    print(f"Connected to {port} @ {BAUD_RATE} baud")
except serial.SerialException as e:
    print(f"Serial error: {e}")
    sys.exit(1)

# ── State ──────────────────────────────────────────────────
# objects: angle (int) → (dist_cm, timestamp)
objects     = {}
sweep_angle = 0
alert_until = 0
status_msg  = "Sweeping..."

# ── Coordinate mapping ─────────────────────────────────────
# Servo 0°  → right   (3 o'clock)
# Servo 90° → top     (12 o'clock)
# Servo 180°→ left    (9 o'clock)
# Formula: x = cx + r*cos(angle_deg),  y = cy - r*sin(angle_deg)
def polar_to_xy(angle_deg, dist_cm):
    rad = math.radians(angle_deg)
    r   = (dist_cm / MAX_DISTANCE) * RADAR_RADIUS
    x   = RADAR_CENTER[0] + int(r * math.cos(rad))
    y   = RADAR_CENTER[1] - int(r * math.sin(rad))
    return x, y

def angle_tip(angle_deg):
    """Full-radius endpoint for a given angle."""
    return polar_to_xy(angle_deg, MAX_DISTANCE)

# ── Drawing helpers ────────────────────────────────────────
def draw_radar_bg():
    screen.fill((5, 5, 10))

    # Concentric arcs (half-circles, top half only)
    for frac, label in [(1.0,  f"{MAX_DISTANCE}cm"),
                        (0.67, f"{int(MAX_DISTANCE*0.67)}cm"),
                        (0.33, f"{int(MAX_DISTANCE*0.33)}cm")]:
        r = int(RADAR_RADIUS * frac)
        # pygame.draw.arc uses degrees: 0=right, CCW. We want the upper semicircle.
        rect = pygame.Rect(RADAR_CENTER[0] - r, RADAR_CENTER[1] - r, r * 2, r * 2)
        pygame.draw.arc(screen, (0, 60, 0), rect, 0, math.pi, 1)
        # label near the right end of the arc
        lbl = font_sm.render(label, True, (0, 100, 0))
        screen.blit(lbl, (RADAR_CENTER[0] + r + 4, RADAR_CENTER[1] - 10))

    # Spokes every 30° (0°–180°)
    for a in range(0, 181, 30):
        ex, ey = angle_tip(a)
        pygame.draw.line(screen, (0, 50, 0), RADAR_CENTER, (ex, ey), 1)
        lbl = font_sm.render(f"{a}°", True, (0, 80, 0))
        # nudge label outward a bit
        dx = ex - RADAR_CENTER[0]
        dy = ey - RADAR_CENTER[1]
        norm = math.hypot(dx, dy) or 1
        screen.blit(lbl, (ex + int(dx / norm * 10) - 10,
                           ey + int(dy / norm * 10) - 8))

    # Base line (flat bottom of the arc)
    pygame.draw.line(screen, (0, 80, 0),
                     (RADAR_CENTER[0] - RADAR_RADIUS, RADAR_CENTER[1]),
                     (RADAR_CENTER[0] + RADAR_RADIUS, RADAR_CENTER[1]), 1)


def draw_sweep_line(angle):
    """
    Sweep line split into two segments:
      • center → detected object : RED   (obstacle in the way)
      • detected object → tip    : GREEN (clear space beyond)
    If nothing detected at this angle, the full line is green.
    Trail fan drawn behind the sweep head (last 20°).
    """
    dist_at_angle = objects.get(angle, (None, None))[0]   # None if nothing

    # ── Trailing fan (20° behind sweep head) ──────────────
    for offset in range(20, 0, -1):
        a = angle - offset
        if a < 0:
            continue
        fade_d = objects.get(a, (None, None))[0]
        alpha  = int(180 * (1 - offset / 20))

        if fade_d is not None and 2 < fade_d < MAX_DISTANCE:
            # red segment: center → object
            ox, oy = polar_to_xy(a, fade_d)
            pygame.draw.line(screen, (alpha, 0, 0),      RADAR_CENTER,  (ox, oy), 1)
            # green segment: object → tip
            tx, ty = angle_tip(a)
            pygame.draw.line(screen, (0, alpha, 0),      (ox, oy),      (tx, ty), 1)
        else:
            tx, ty = angle_tip(a)
            pygame.draw.line(screen, (0, alpha, 0),      RADAR_CENTER,  (tx, ty), 1)

    # ── Bright sweep head ──────────────────────────────────
    if dist_at_angle is not None and 2 < dist_at_angle < MAX_DISTANCE:
        ox, oy = polar_to_xy(angle, dist_at_angle)
        tx, ty = angle_tip(angle)
        pygame.draw.line(screen, (40, 255,  40),  RADAR_CENTER,  (ox, oy), 2)   # red
        pygame.draw.line(screen, (255,  40, 80),  (ox, oy),      (tx, ty), 2)   # green

    else:
        tx, ty = angle_tip(angle)
        pygame.draw.line(screen, (40, 255, 80), RADAR_CENTER, (tx, ty), 2)
        

def draw_hud():
    now = time.time()
    if now < alert_until:
        flash = font_lg.render("⚠  APPROACHING OBJECT  ⚠", True, (255, 60, 0))
        screen.blit(flash, (WIDTH // 2 - flash.get_width() // 2, 8))
    else:
        title = font_lg.render("ULTRASONIC RADAR", True, (0, 220, 80))
        screen.blit(title, (WIDTH // 2 - title.get_width() // 2, 8))

    info = font_md.render(
        f"Objects: {len(objects)}   Range: {MAX_DISTANCE}cm   "
        f"Sweep: {sweep_angle}°   Port: {port}",
        True, (0, 180, 60))
    screen.blit(info, (10, HEIGHT - 28))

    st = font_sm.render(status_msg, True, (0, 140, 60))
    screen.blit(st, (10, HEIGHT - 50))

    # Legend
    pygame.draw.line(screen, (255, 40, 40),  (WIDTH - 160, HEIGHT - 44), (WIDTH - 130, HEIGHT - 44), 2)
    screen.blit(font_sm.render("obstacle", True, (200, 100, 100)), (WIDTH - 125, HEIGHT - 50))
    pygame.draw.line(screen, (40, 255, 80),  (WIDTH - 160, HEIGHT - 26), (WIDTH - 130, HEIGHT - 26), 2)
    screen.blit(font_sm.render("clear",    True, (100, 200, 100)), (WIDTH - 125, HEIGHT - 32))


# ── Main loop ──────────────────────────────────────────────
running = True
while running:
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False
        if event.type == pygame.KEYDOWN and event.key == pygame.K_c:
            objects.clear()

    for _ in range(20):
        try:
            raw = ser.readline()
            if not raw:
                break
            line = raw.decode('utf-8', errors='ignore').strip()
            if not line:
                continue
            parts = line.split(',')

            if parts[0] == "S" and len(parts) >= 3:
                angle = int(parts[1])
                dist  = float(parts[2])
                sweep_angle = angle
                status_msg  = "Sweeping..."
                if 2 < dist < MAX_DISTANCE:
                    objects[angle] = (dist, time.time())

            elif parts[0] == "T" and len(parts) >= 4:
                angle  = int(parts[1])
                prev_d = float(parts[2])
                curr_d = float(parts[3])
                status_msg = f"Tracking {angle}°: {curr_d:.0f}cm (was {prev_d:.0f}cm)"
                if curr_d < prev_d - 5:
                    print(f"⚠  Approaching at {angle}°: {prev_d}→{curr_d} cm")
                    alert_until = time.time() + 3

            elif line == "A":
                print("⚠  ALERT: object approaching!")
                alert_until = time.time() + 3

        except (UnicodeDecodeError, ValueError):
            pass
        except serial.SerialException:
            break

    draw_radar_bg()
    draw_sweep_line(sweep_angle)
    draw_hud()

    pygame.display.flip()
    clock.tick(60)

ser.close()
pygame.quit()