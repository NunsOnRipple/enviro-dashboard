
import time
import requests
import st7735
from fonts.ttf import RobotoMedium as UserFont
from PIL import Image, ImageDraw, ImageFont

# Setup display
disp = st7735.ST7735(
    port=0, cs=1, dc=9, backlight=12,
    rotation=270, spi_speed_hz=10000000
)
disp.begin()

WIDTH = disp.width
HEIGHT = disp.height

font_tiny = ImageFont.truetype(UserFont, 10)

DATA_URL = "http://localhost:5000/data"

while True:
    try:
        response = requests.get(DATA_URL, timeout=2)
        data = response.json()

        img = Image.new('RGB', (WIDTH, HEIGHT), color=(20, 20, 40))
        draw = ImageDraw.Draw(img)

        draw.text((5, 2),  f"Temp:  {data['temperature']} F", font=font_tiny, fill=(240, 120, 180))
        draw.text((5, 14), f"Hum:   {data['humidity']} %", font=font_tiny, fill=(240, 120, 180))
        draw.text((5, 26), f"Pres:  {data['pressure']} hPa", font=font_tiny, fill=(240, 120, 180))

        draw.text((5, 40), f"PM1:   {data['pm1']} ug", font=font_tiny, fill=(100, 220, 255))
        draw.text((5, 52), f"PM2.5: {data['pm25']} ug", font=font_tiny, fill=(100, 220, 255))
        draw.text((5, 64), f"PM10:  {data['pm10']} ug", font=font_tiny, fill=(100, 220, 255))

        disp.display(img)

    except Exception as e:
        print(f"Error: {e}")

    time.sleep(5)
