"""Paragraf rollerinin atanması: özellik çıkarımı (metin burada kalır) → sınıflandırıcı
(yalnızca özellikleri görür)."""

from __future__ import annotations

from synora.classify import RoleDecision, classify
from synora.features import extract_features
from synora.model import DocModel

__all__ = ["RoleDecision", "assign_roles"]


def assign_roles(doc: DocModel) -> dict[str, RoleDecision]:
    return {pid: classify(f) for pid, f in extract_features(doc).items()}
