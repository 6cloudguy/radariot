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
FADE_SECONDS  = 4         # how long a trail segment stays visible

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

# Transparent surface for alpha fading/glowing effects
overlay_surface = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)

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
    screen.fill((4, 10, 6)) # Deep military sci-fi green-black background

    # Concentric arcs (half-circles, top half only)
    for frac, label in [(1.0,  f"{MAX_DISTANCE}cm"),
                        (0.67, f"{int(MAX_DISTANCE*0.67)}cm"),
                        (0.33, f"{int(MAX_DISTANCE*0.33)}cm")]:
        r = int(RADAR_RADIUS * frac)
        rect = pygame.Rect(RADAR_CENTER[0] - r, RADAR_CENTER[1] - r, r * 2, r * 2)
        
        # Double draw for a clean CRT glow effect
        pygame.draw.arc(screen, (0, 40, 10), rect, 0, math.pi, 3)
        pygame.draw.arc(screen, (0, 110, 30), rect, 0, math.pi, 1)
        
        lbl = font_sm.render(label, True, (0, 140, 40))
        screen.blit(lbl, (RADAR_CENTER[0] + r + 8, RADAR_CENTER[1] - 10))

    # Spokes every 30° (0°–180°)
    for a in range(0, 181, 30):
        ex, ey = angle_tip(a)
        pygame.draw.line(screen, (0, 45, 15), RADAR_CENTER, (ex, ey), 1)
        lbl = font_sm.render(f"{a}°", True, (0, 120, 35))
        
        dx = ex - RADAR_CENTER[0]
        dy = ey - RADAR_CENTER[1]
        norm = math.hypot(dx, dy) or 1
        screen.blit(lbl, (ex + int(dx / norm * 12) - 10,
                           ey + int(dy / norm * 12) - 8))

    # Grid Base line 
    pygame.draw.line(screen, (0, 90, 25),
                     (RADAR_CENTER[0] - RADAR_RADIUS, RADAR_CENTER[1]),
                     (RADAR_CENTER[0] + RADAR_RADIUS, RADAR_CENTER[1]), 2)


def draw_sweep_line(angle):
    """
    Renders an alpha trailing fan, a high-contrast sweep head, 
    and persistent blips that smoothly fade over time.
    """
    overlay_surface.fill((0, 0, 0, 0)) # Clear previous frame alpha
    now = time.time()

    # ── 1. Draw Trailing Sweep Fan (Last 30 degrees) ──────────
    for offset in range(30, 0, -1):
        a = (angle - offset) % 360
        if not (0 <= a <= 180): 
            continue
            
        alpha = int(100 * (1 - offset / 30)) # Tail drop-off
        tx, ty = angle_tip(a)
        
        fade_d, _ = objects.get(a, (None, None))
        if fade_d is not None and 2 < fade_d < MAX_DISTANCE:
            ox, oy = polar_to_xy(a, fade_d)
            # Center to obstacle: Warning Amber/Red Trail
            pygame.draw.line(overlay_surface, (130, 40, 0, alpha), RADAR_CENTER, (ox, oy), 2)
            # Obstacle to outer rim: Soft Green Trail
            pygame.draw.line(overlay_surface, (0, 100, 30, alpha), (ox, oy), (tx, ty), 1)
        else:
            # Full clear sweep lane
            pygame.draw.line(overlay_surface, (0, 110, 35, alpha), RADAR_CENTER, (tx, ty), 2)

    # ── 2. Draw Fading Obstacle Blips ─────────────────────────
    for ang, (dist_cm, timestamp) in list(objects.items()):
        age = now - timestamp
        if age > FADE_SECONDS or dist_cm >= MAX_DISTANCE or dist_cm <= 2:
            continue
            
        # Calculate fade out alpha multiplier
        alpha_factor = 1.0 - (age / FADE_SECONDS)
        blip_alpha = int(255 * alpha_factor)
        
        bx, by = polar_to_xy(ang, dist_cm)
        
        # Outer Ring Glow, Inner hot-spot core
        pygame.draw.circle(overlay_surface, (255, 30, 60, int(blip_alpha * 0.4)), (bx, by), 7)
        pygame.draw.circle(overlay_surface, (255, 200, 210, blip_alpha), (bx, by), 3)

    # Blit the accumulated alpha changes over the main background
    screen.blit(overlay_surface, (0, 0))

    # ── 3. Bright Active Sweep Head (Drawn on top) ─────────────
    dist_at_angle, _ = objects.get(angle, (None, None))
    tx, ty = angle_tip(angle)

    if dist_at_angle is not None and 2 < dist_at_angle < MAX_DISTANCE:
        ox, oy = polar_to_xy(angle, dist_at_angle)
        # Visual fix: CENTER to OBJECT is blocked (RED/ORANGE). OBJECT to RIM is clear (GREEN).
        pygame.draw.line(screen, (255, 65, 65), RADAR_CENTER, (ox, oy), 3)   # Obstacle Segment
        pygame.draw.line(screen, (50, 255, 110), (ox, oy), (tx, ty), 2)     # Clear Beyond Segment
        
        # Primary threat marker blip
        pygame.draw.circle(screen, (255, 255, 255), (ox, oy), 4)
    else:
        # 100% Clear line
        pygame.draw.line(screen, (60, 255, 120), RADAR_CENTER, (tx, ty), 3)
        

def draw_hud():
    now = time.time()
    
    # Glowing Alert system banner
    if now < alert_until:
        flash_surf = font_lg.render("⚠  APPROACHING OBJECT DETECTED  ⚠", True, (255, 50, 50))
        # Simulated glow box backing
        pygame.draw.rect(screen, (40, 5, 5), (WIDTH//2 - 260, 4, 520, 32), border_radius=4)
        pygame.draw.rect(screen, (150, 20, 20), (WIDTH//2 - 260, 4, 520, 32), 1, border_radius=4)
        screen.blit(flash_surf, (WIDTH // 2 - flash_surf.get_width() // 2, 9))
    else:
        title = font_lg.render("ULTRASONIC RADAR SYSTEM", True, (0, 230, 90))
        screen.blit(title, (WIDTH // 2 - title.get_width() // 2, 9))

    # Lower Info Console Panel
    pygame.draw.rect(screen, (8, 18, 10), (0, HEIGHT - 60, WIDTH, 60))
    pygame.draw.line(screen, (0, 80, 30), (0, HEIGHT - 60), (WIDTH, HEIGHT - 60), 1)

    info = font_md.render(
        f"Active Pins: {len(objects)}   Max Range: {MAX_DISTANCE}cm   "
        f"Bearing: {sweep_angle:03d}°   Port: {port}",
        True, (0, 200, 75))
    screen.blit(info, (15, HEIGHT - 28))

    st = font_sm.render(f"STATUS // {status_msg.upper()}", True, (0, 150, 55))
    screen.blit(st, (15, HEIGHT - 48))

    # Clean UI Legend Alignment
    leg_x = WIDTH - 180
    pygame.draw.line(screen, (255, 65, 65),  (leg_x, HEIGHT - 41), (leg_x + 25, HEIGHT - 41), 3)
    screen.blit(font_sm.render("OBSTACLE", True, (240, 90, 90)), (leg_x + 35, HEIGHT - 47))
    
    pygame.draw.line(screen, (60, 255, 120),  (leg_x, HEIGHT - 21), (leg_x + 25, HEIGHT - 21), 3)
    screen.blit(font_sm.render("CLEAR",    True, (110, 230, 140)), (leg_x + 35, HEIGHT - 27))


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
                status_msg  = "Tracking Sector Sweep..."
                if 2 < dist < MAX_DISTANCE:
                    objects[angle] = (dist, time.time())

            elif parts[0] == "T" and len(parts) >= 4:
                angle  = int(parts[1])
                prev_d = float(parts[2])
                curr_d = float(parts[3])
                status_msg = f"Intercept vector {angle}°: {curr_d:.0f}cm"
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