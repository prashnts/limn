+++
summary = "A small NEMA 8 stepper from AliExpress (39 g, 0.4 A): too weak to pull the Z belt, fine on a lead screw. Limn's Z motor."
+++

![Its drawing](/img/notes/nema8-dims.webp)

![Its ratings](/img/notes/nema8-specs.webp)

- 39 g, rated 0.4 A at 2.1 V, 0.012 N·m holding torque, 1.8° steps.
- On the belt-driven Z it was a no-go: it buzzed, and it stalled even at 0.8 A ([log #3](/log/2026-04-03-nema-8-no-go-and-backlash-correction.html)).
- On the M3 lead screw it's plenty ([[limn-z-axis-rider]]).
- [i] It runs on the Melzi's Z driver at 5 V: the board's 12 V made the small motors run hot.
