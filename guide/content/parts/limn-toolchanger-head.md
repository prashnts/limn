+++
summary = "Picks a tool up by its key: a Maxwell coupling of three magnetic screws lines the tool up, and the K axis turns the key to lock it."
+++

## How it holds a tool

- **Alignment**: a Maxwell (kinematic) coupling. Three shafted M2.5 screws on the head meet three on the tool, so each tool comes back to the same place every time. 2 mm magnets on the screws pull the tool in: *it does a "click" now when taken from the rack* ([log #1](/log/2026-03-31-first-steps.html)).
- **Lock**: the K axis, a [[5mm-stepper-slider]] (a tiny linear stepper, run at 5 V), turns a key through a geared rack. In v88 it's the [[k-gear]], the [[k-pin]] and the [[2x12-k-dowel]]. `K_LOCK` and `K_UNLOCK` drive it, and a micro switch is its endstop.
- **Contacts**: the coupling screws carry current too. Each screw pair is wired on its own, in 28 AWG solid-core wire. In v88, four [[pogo-pin-5mm]] pins carry power and data to the tool, and a [[qre1113-line-sensor]] sees whether the lock is closed.


## Hardware, from the build notes

| Part | Qty | For |
|---|---|---|
| 5 mm linear stepper | 1 | the K axis, 5 V |
| M2.5 shafted screws | 6 | the coupling |
| 2 mm magnets | 12 | on the shafted screws |
| 2 × 12 mm dowel | 1 | the key |
| Micro switch | 1 | the key's endstop |
| BT2×10, BT2×6 (3), BT1.6×6 (5), BT2.5×10 | | the structure |
| 28 AWG solid-core wire | 3 | joins the screw pairs |

## Tethered tools

A tool can keep a cable: a UVC camera on a tool docked and undocked fine ([log #9](/log/2026-05-01-applying-tool-parameters-tethered-tools.html)). Later a camera rode on the key itself, so it turns with the lock: locked, it looks down at the paper; unlocked, straight ahead at the dock.

![A camera on a tethered tool](/img/notes/tethered-tool-camera.webp)
