import time
from random import randrange

from rgbmatrix import RGBMatrixOptions, RGBMatrix
from PIL import Image, ImageDraw

options = RGBMatrixOptions()

options.rows = 64
options.cols = 128

options.chain_length = 1
options.parallel     = 1

options.hardware_mapping = "adafruit-hat"

options.gpio_slowdown = 4

options.brightness = 100                                                                           


matrix = RGBMatrix(options = options)


while True:
    matrix.Clear()
    # for _ in range(10000):
    r = randrange(256)
    g = randrange(256)
    b = randrange(256)

    x = randrange(128)
    y = randrange(64)

    matrix.Fill(r,g,b)

    time.sleep(0.5)