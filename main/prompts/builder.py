from __future__ import annotations

import json
import re
from dataclasses import dataclass

from main.domain.models import ImagePromptContext

@dataclass(frozen=True, slots=True)
class PromptSpec:
    subject: str = ''
    action: str = ''
    environment: str = ''
    composition: str = ''
    camera: str = ''
    lighting: str = ''
    atmosphere: str = ''
    details: str = ''

class PromptBuilder:
    _FIELDS = ('subject', 'action', 'environment', 'composition', 'camera', 'lighting', 'atmosphere', 'details')

    @staticmethod
    def _clean(value: object) -> str:
        if value is None:
            return ''
        return ' '.join(str(value).strip().split()).strip(' ,.;:')

    @classmethod
    def parse(cls, raw: str) -> PromptSpec:
        text = (raw or '').strip().lstrip('\ufeff')
        if not text:
            return PromptSpec()
        cleaned = text
        if cleaned.startswith('```'):
            first_newline = cleaned.find('\n')
            if first_newline >= 0:
                cleaned = cleaned[first_newline + 1:]
            else:
                cleaned = cleaned[3:]
                if cleaned.lower().startswith('json'):
                    cleaned = cleaned[4:]
            if cleaned.rstrip().endswith('```'):
                cleaned = cleaned.rstrip()[:-3].rstrip()
        data = None
        try:
            data = json.loads(cleaned)
        except (TypeError, ValueError):
            match = re.search(r'\{.*\}', cleaned, flags=re.S)
            if match:
                try:
                    data = json.loads(match.group(0))
                except (TypeError, ValueError):
                    data = None
        if not isinstance(data, dict):
            return PromptSpec(details=cls._clean(text))
        return PromptSpec(**{field: cls._clean(data.get(field)) for field in cls._FIELDS})

    @classmethod
    def render(cls, spec: PromptSpec, context: ImagePromptContext) -> str:
        parts = []
        seen = set()
        for value in (spec.subject, spec.environment, spec.action, spec.composition, spec.camera, spec.lighting, spec.atmosphere, spec.details):
            value = cls._clean(value)
            key = value.lower()
            if value and key not in seen:
                parts.append(value)
                seen.add(key)
        return ', '.join(parts)
