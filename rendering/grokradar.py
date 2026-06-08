import pygame
import serial
import time
import math

# ========================= CONFIG =========================
SERIAL_PORT = "/dev/ttyACM1"          # ← CHANGE THIS (Windows: COM3, Linux: /dev/ttyUSB0)
BAUD_RATE = 9600

WIDTH, HEIGHT = 800, 600
CENTER = (WIDTH//2, HEIGHT//2)
MAX_DISTANCE = 150            # cm - same as Arduino threshold

pygame.init()
screen = pygame.display.set_mode((WIDTH, HEIGHT))
pygame.display.set_caption("Ultrasonic Radar System")
clock = pygame.time.Clock()
font = pygame.font.SysFont("consolas", 18)

ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
time.sleep(2)

objects = []  # list of (angle, distance)

running = True
while running:
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False

    screen.fill((0, 0, 0))

    # Draw radar background
    pygame.draw.circle(screen, (0, 30, 0), CENTER, 250, 2)
    pygame.draw.circle(screen, (0, 20, 0), CENTER, 180, 2)
    pygame.draw.circle(screen, (0, 15, 0), CENTER, 100, 2)
    
    # Draw scan lines
    for a in range(0, 181, 30):
        rad = math.radians(a - 90)
        end_x = CENTER[0] + int(250 * math.cos(rad))
        end_y = CENTER[1] + int(250 * math.sin(rad))
        pygame.draw.line(screen, (0, 80, 0), CENTER, (end_x, end_y), 1)

    # Read serial data
    try:
        line = ser.readline().decode('utf-8').strip()
        if line:
            parts = line.split(',')
            
            if parts[0] == "S" and len(parts) >= 3:          # Sweep data
                angle = int(parts[1])
                dist = float(parts[2])
                
                if 3 < dist < MAX_DISTANCE:
                    objects = [obj for obj in objects if abs(obj[0] - angle) > 8]  # avoid duplicates
                    objects.append((angle, dist))
                
            elif parts[0] == "T" and len(parts) >= 4:        # Tracking data
                angle = int(parts[1])
                prev_d = float(parts[2])
                curr_d = float(parts[3])
                
                if curr_d < prev_d - 4:
                    print(f"🚨 APPROACHING at {angle}° !")
                    # Flash effect or sound can be added here
            
            elif line == "A":
                print("🚨 BEEP - OBJECT APPROACHING!")
                
    except:
        pass

    # Draw detected objects
    for angle, dist in objects[:]:   # copy to avoid modification during loop
        rad = math.radians(angle - 90)
        x = CENTER[0] + int((dist / MAX_DISTANCE) * 240 * math.cos(rad))
        y = CENTER[1] + int((dist / MAX_DISTANCE) * 240 * math.sin(rad))
        
        pygame.draw.circle(screen, (0, 255, 0), (x, y), 8)
        pygame.draw.line(screen, (0, 100, 0), CENTER, (x, y), 2)

    # Sweep line effect (you can improve this)
    # Text info
    text = font.render(f"Objects detected: {len(objects)} | Max Range: {MAX_DISTANCE}cm", True, (0, 255, 0))
    screen.blit(text, (10, 10))

    pygame.display.flip()
    clock.tick(60)

ser.close()
pygame.quit()