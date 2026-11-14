"""MediaPipe Tasks API pose, face and hand landmarkers (DESIGN §5, steps 2 to 4).

Uses mp.tasks.vision in VIDEO running mode, never the removed mp.solutions API.
Results are converted straight into plain numpy arrays (features.RawLandmarks), so no
MediaPipe type leaves this module.
"""

from __future__ import annotations

from types import TracebackType
from typing import Any

import mediapipe as mp
import numpy as np
import numpy.typing as npt

from app.vision import model_files
from app.vision.features import RawHand, RawLandmarks

_vision = mp.tasks.vision
_BaseOptions = mp.tasks.BaseOptions


def _base(name: str) -> Any:
    return _BaseOptions(model_asset_path=str(model_files.path(name)))


class Landmarkers:
    """Pose, face and hand landmarkers for one session. Close it (or use `with`) to free them."""

    def __init__(self, min_confidence: float, num_hands: int = 2) -> None:
        video = _vision.RunningMode.VIDEO
        c = min_confidence
        self._pose = _vision.PoseLandmarker.create_from_options(_vision.PoseLandmarkerOptions(
            base_options=_base(model_files.POSE), running_mode=video, num_poses=1,
            min_pose_detection_confidence=c, min_pose_presence_confidence=c, min_tracking_confidence=c,
        ))
        self._face = _vision.FaceLandmarker.create_from_options(_vision.FaceLandmarkerOptions(
            base_options=_base(model_files.FACE), running_mode=video, num_faces=1,
            min_face_detection_confidence=c, min_face_presence_confidence=c, min_tracking_confidence=c,
            output_facial_transformation_matrixes=True,
        ))
        self._hands = _vision.HandLandmarker.create_from_options(_vision.HandLandmarkerOptions(
            base_options=_base(model_files.HAND), running_mode=video, num_hands=num_hands,
            min_hand_detection_confidence=c, min_hand_presence_confidence=c, min_tracking_confidence=c,
        ))

    @classmethod
    def from_settings(cls, settings: dict[str, Any]) -> Landmarkers:
        return cls(settings["vision"]["mp_min_confidence"])

    def detect(
        self, rgb: npt.NDArray[np.uint8], timestamp_ms: int, run_hands: bool = True
    ) -> RawLandmarks:
        """Run the landmarkers on one RGB frame. Timestamps must strictly increase.

        With run_hands False, hands are skipped and returned as an empty list; the caller
        reuses the previous hands (vision.hands_every_n).
        """
        image = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb))

        pose = None
        pr = self._pose.detect_for_video(image, timestamp_ms)
        if pr.pose_landmarks:
            pose = np.array(
                [(p.x, p.y, p.z, p.visibility if p.visibility is not None else 0.0) for p in pr.pose_landmarks[0]],
                dtype=np.float64,
            )

        face = matrix = None
        fr = self._face.detect_for_video(image, timestamp_ms)
        if fr.face_landmarks:
            face = np.array([(p.x, p.y, p.z) for p in fr.face_landmarks[0]], dtype=np.float64)
            if fr.facial_transformation_matrixes:
                matrix = np.asarray(fr.facial_transformation_matrixes[0], dtype=np.float64)

        hands: list[RawHand] = []
        if run_hands:
            hr = self._hands.detect_for_video(image, timestamp_ms)
            for img_pts, world_pts in zip(hr.hand_landmarks, hr.hand_world_landmarks):
                hands.append(RawHand(
                    image=np.array([(p.x, p.y, p.z) for p in img_pts], dtype=np.float64),
                    world=np.array([(p.x, p.y, p.z) for p in world_pts], dtype=np.float64),
                ))

        return RawLandmarks(pose=pose, face=face, face_matrix=matrix, hands=hands)

    def close(self) -> None:
        for task in (self._pose, self._face, self._hands):
            task.close()

    def __enter__(self) -> Landmarkers:
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        self.close()
