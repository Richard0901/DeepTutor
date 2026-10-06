"""Learning-surface mapping for the teaching-domain paths.

``require_learning_surface`` denies learner accounts on unmapped paths, so
the teaching/clinical prefixes must be mapped (course-level RBAC is enforced
inside the routers themselves).
"""

from __future__ import annotations

from deeptutor.api.routers.auth import _learning_surface_for_path


def test_teaching_paths_map_to_learner_surface():
    assert _learning_surface_for_path("/api/v1/teaching/courses", "GET") == "chat"
    assert _learning_surface_for_path("/api/v1/teaching/classes/x/members", "POST") == "chat"
    assert _learning_surface_for_path("/api/v1/clinical/cases", "GET") == "chat"
    assert _learning_surface_for_path("/api/v1/clinical/attempts", "POST") == "chat"
    assert _learning_surface_for_path("/api/v1/clinical/attempts/x/steps", "POST") == "chat"


def test_unrelated_paths_stay_unmapped():
    assert _learning_surface_for_path("/api/v2/other", "GET") == ""
    assert _learning_surface_for_path("/api/v1/teaching-other", "GET") == ""
    assert _learning_surface_for_path("/api/v1/clinic", "GET") == ""
