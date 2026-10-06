"""Clinical case domain: content model, versions, review and publication.

Implements the case workflow of the 2026-07-24 plan (WP3):

    draft → under_review → (two distinct approvals) → approved → published

Published versions are immutable; edits create a new draft version and the
old one is superseded only when the successor is published (hard constraints
#3 and #5: 未审核病例不发布、所有正式记录可回放).
"""
