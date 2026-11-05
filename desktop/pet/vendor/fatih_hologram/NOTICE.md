# Hologram credits and licenses

Portrait renderer and mesh builder: **FatihMakes**, MARK 54–56 / Mark-LVI.
Source: https://github.com/FatihMakes/Mark-LVI
Pinned revision: `4d4035c1b40a3bc796ac63f2f1b6a99bc0dd334d`.
Copyright (c) 2026 FatihMakes. **CC BY-NC 4.0**, full text in `LICENSE`.
License: https://creativecommons.org/licenses/by-nc/4.0/
Used for this user's personal, noncommercial Alex installation. Do not remove
attribution or assume these files can be distributed commercially.

Changes by Codex for Alex, 29 October 2026: PyQt6 imports changed to PySide6,
relative mesh import, computed eyelid state applied to the painted eye ring.
Alex supplies its own state/animation adapter in `pet/hologram_face.py`.
No upstream assistant, camera, microphone, cloud provider or actions are imported.
Source is adapted; it is not endorsed by FatihMakes.

`face_model.obj`: canonical MediaPipe human face geometry, Apache-2.0,
Copyright 2019–2023 The MediaPipe Authors (upstream notice retained in OBJ).
Source: https://github.com/google-ai-edge/mediapipe/blob/master/mediapipe/modules/face_geometry/data/canonical_face_model.obj
Only v/f geometry retained and rounded by FatihMakes; no texture coordinates.
Full Apache-2.0 text: `LICENSE-MediaPipe`.
