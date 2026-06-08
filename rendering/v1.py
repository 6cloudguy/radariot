import pygame
import serial
import serial.tools.list_ports
import time
import math
import sys

# ========================= CONFIG =========================
# Auto-detect port or override manually:
#   Windows  → "COM3", "COM4", ...
#   Linux    → "/dev/ttyUSB0", "/dev/ttyACM0", ...
#   macOS    → "/dev/tty.usbmodem...", ...
SERIAL_PORT   = None      # ← Set to a string like "COM3" to skip auto-detect
BAUD_RATE     = 9600

WIDTH, HEIGHT = 900, 650
RADAR_CENTER  = (WIDTH // 2, HEIGHT // 2 + 40)
RADAR_RADIUS  = 280
MAX_DISTANCE  = 150       # cm — must match Arduino DETECTION_THRESHOLD
FADE_SECONDS  = 8         # how long a detected dot stays visible

# ──────────────────────────────────────────────────────────
def find_serial_port():
    """Return the first Arduino-looking serial port, or ask the user."""
    if SERIAL_PORT:
        return SERIAL_PORT
    ports = list(serial.tools.list_ports.comports())
    arduino_ports = [p.device for p in ports
                     if "Arduino" in (p.description or "")
                     or "USB" in (p.description or "")
                     or "ACM" in p.device
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
    print("ERROR: No serial ports found. Check USB connection.")
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
objects    = {}          # angle → (distance, timestamp)
sweep_angle = 0          # current sweep line angle
alert_until = 0          # time.time() until alert flash is shown
status_msg  = "Sweeping..."

# ── Drawing helpers ────────────────────────────────────────
def polar_to_xy(angle_deg, dist_cm):
    """Convert radar polar coords to screen xy."""
    rad = math.radians(angle_deg - 90)
    r   = (dist_cm / MAX_DISTANCE) * RADAR_RADIUS
    x   = RADAR_CENTER[0] + int(r * math.cos(rad))
    y   = RADAR_CENTER[1] + int(r * math.sin(rad))
    return x, y

def draw_radar_bg():
    screen.fill((5, 5, 10))

    # Grid rings
    for frac, label in [(1.0, f"{MAX_DISTANCE}cm"),
                        (0.67, f"{int(MAX_DISTANCE*0.67)}cm"),
                        (0.33, f"{int(MAX_DISTANCE*0.33)}cm")]:
        r = int(RADAR_RADIUS * frac)
        pygame.draw.circle(screen, (0, 60, 0), RADAR_CENTER, r, 1)
        lbl = font_sm.render(label, True, (0, 100, 0))
        screen.blit(lbl, (RADAR_CENTER[0] + r + 4, RADAR_CENTER[1] - 8))

    # Spokes every 30°
    for a in range(0, 181, 30):
        rad = math.radians(a - 90)
        ex  = RADAR_CENTER[0] + int(RADAR_RADIUS * math.cos(rad))
        ey  = RADAR_CENTER[1] + int(RADAR_RADIUS * math.sin(rad))
        pygame.draw.line(screen, (0, 50, 0), RADAR_CENTER, (ex, ey), 1)
        # angle label
        lbl = font_sm.render(f"{a}°", True, (0, 80, 0))
        screen.blit(lbl, (ex - 14, ey - 8))

    # Flat base line (0°–180°)
    lx = RADAR_CENTER[0] - RADAR_RADIUS
    rx = RADAR_CENTER[0] + RADAR_RADIUS
    pygame.draw.line(screen, (0, 80, 0), (lx, RADAR_CENTER[1]), (rx, RADAR_CENTER[1]), 1)

def draw_sweep_line(angle):
    """Glowing green sweep line + trailing fan."""
    for offset in range(20, 0, -1):
        a   = angle - offset
        if a < 0: continue
        rad = math.radians(a - 90)
        ex  = RADAR_CENTER[0] + int(RADAR_RADIUS * math.cos(rad))
        ey  = RADAR_CENTER[1] + int(RADAR_RADIUS * math.sin(rad))
        alpha = int(200 * (1 - offset / 20))
        color = (0, alpha, 0)
        pygame.draw.line(screen, color, RADAR_CENTER, (ex, ey), 1)

    # Bright tip
    rad = math.radians(angle - 90)
    ex  = RADAR_CENTER[0] + int(RADAR_RADIUS * math.cos(rad))
    ey  = RADAR_CENTER[1] + int(RADAR_RADIUS * math.sin(rad))
    pygame.draw.line(screen, (0, 255, 80), RADAR_CENTER, (ex, ey), 2)

def draw_objects():
    now = time.time()
    expired = []
    for angle, (dist, ts) in objects.items():
        age = now - ts
        if age > FADE_SECONDS:
            expired.append(angle)
            continue

        fade  = max(0, 1 - age / FADE_SECONDS)
        green = int(255 * fade)
        red   = int(180 * (1 - fade))     # goes yellow → red as it ages
        color = (red, green, 0)

        x, y = polar_to_xy(angle, dist)
        pygame.draw.circle(screen, color, (x, y), 7)
        pygame.draw.circle(screen, (255, 255, 255), (x, y), 7, 1)

        lbl = font_sm.render("", True, (180, 255, 180))
        screen.blit(lbl, (x + 9, y - 6))

    for a in expired:
        del objects[a]

def draw_hud():
    now = time.time()
    # Alert flash
    if now < alert_until:
        flash = font_lg.render("⚠  APPROACHING OBJECT  ⚠", True, (255, 60, 0))
        screen.blit(flash, (WIDTH // 2 - flash.get_width() // 2, 8))
    else:
        title = font_lg.render("ULTRASONIC RADAR", True, (0, 220, 80))
        screen.blit(title, (WIDTH // 2 - title.get_width() // 2, 8))

    info = font_md.render(
        f"Objects: {len(objects)}   Range: {MAX_DISTANCE} cm   "
        f"Sweep: {sweep_angle}°   Port: {port}",
        True, (0, 180, 60))
    screen.blit(info, (10, HEIGHT - 28))

    st = font_sm.render(status_msg, True, (0, 140, 60))
    screen.blit(st, (10, HEIGHT - 50))

# ── Main loop ──────────────────────────────────────────────
running = True
while running:
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False
        if event.type == pygame.KEYDOWN and event.key == pygame.K_c:
            objects.clear()   # C key clears the display

    # Read all available serial lines this frame
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
                status_msg = "Sweeping..."

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

    # Draw
    draw_radar_bg()
    draw_sweep_line(sweep_angle)
    draw_objects()
    draw_hud()

    pygame.display.flip()
    clock.tick(60)

ser.close()
pygame.quit()
