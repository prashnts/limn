+++
summary = "An 8 × 8 time-of-flight distance sensor on the Z rider, tried for finding the dock's holders. It worked in parts, and was set aside."
+++

- The VL53L5X gives an 8 × 8 grid of distances, for about 20 euros. It's wired to the Pi's I2C, alongside the holder switches.
- The idea was to find a docked tool's centre without touching it: the coupling screws, the key hole ([log #14](/log/2026-08-16-calibrating-the-dock-parameters-automatically-with-tof-sensor.html)).

![The dock through the ToF sensor](/img/notes/tof-dock.webp)

- Its pixels are too big to find Z. But a known pattern at a known place looks sharper when the tool is lined up, and that can be used.

![Looking for a known pattern](/img/notes/tof-pattern.webp)

- It was set aside once the dock trouble turned out to be loose belts. It still serves an MJPEG stream of what it sees, next to the other cameras.
