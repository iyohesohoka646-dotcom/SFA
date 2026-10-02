from pathlib import Path

from ...agent.privacy import clean_text
from ..planning import fingerprint


class SkillService:
    """Import a versioned instruction document; it grants no file or tool authority."""
    def __init__(self, store):
        self.store = store

    def register(self, path):
        path = Path(path).resolve(strict=True)
        if path.suffix.lower() != '.md' or path.stat().st_size > 256 * 1024:
            raise ValueError('Select a Markdown Skill of at most 256 KiB')
        text = path.read_text(encoding='utf-8')
        key = fingerprint({'path': str(path), 'text': text})
        return self.store.put('skills', key, {'id': key, 'path': str(path), 'version': key, 'title': clean_text(text.splitlines()[0] if text else path.stem),
            'instructions': clean_text(text, 16384), 'truncated': len(text) > 16384, 'grants_capabilities': False})

    def list(self):
        return [{k: v for k, v in skill.items() if k != 'instructions'} for skill in self.store.list('skills')]

    def load(self, key):
        return self.store.get('skills', key)
