"""Server-owned presentation defaults; not fields for Gemini to invent or return."""

from lerny.heygen_lecture_profile import PROFILE_ID

ASPECT_RATIO = "16:9"


def legacy_panel_profile():
    # Return fresh objects so a response consumer cannot mutate subsequent requests.
    return {
        "profile_id": "lecture_landscape_v1",
        "aspect_ratio": ASPECT_RATIO,
        "layout": {
            "ratio_scope": "content_area",
            "instructor_width_ratio": 0.3,
            "material_width_ratio": 0.7,
            "instructor_position": "left",
            "title_position": "top",
            "captions_position": "bottom",
            "gesture_targeting": "element_id",
        },
    }


def presentation_profile():
    return {
        "profile_id": PROFILE_ID,
        "aspect_ratio": "16:9",
        "layout": {
            "scene_style": "seated_instructor_with_right_materials",
            "instructor_position": "left",
            "material_position": "right",
            "preserve_look_background": True,
            "camera": "fixed",
            "materials_designed_by": "heygen_video_agent",
            "ratio_scope": "approximate_visual_emphasis",
            "instructor_width_ratio": 0.4,
            "material_width_ratio": 0.6,
            "split_screen": False,
            "captions_position": "bottom",
            "gesture_targeting": "natural",
        },
    }
