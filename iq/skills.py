import hashlib
import json
from .config import ROOT


class SkillRegistry:
    """Only bundled declarative skills. No arbitrary imports or script execution."""
    def __init__(self):
        folder=ROOT/'skills'/'evaluar-documento'
        self.folder=folder
        self.metadata=json.loads((folder/'manifest.json').read_text('utf-8'))
        if self.metadata['handler']!='document_evaluation' or self.metadata['allows_scripts']:
            raise ValueError('Skill no admitida por este runtime.')

    def catalog(self):
        return [dict(self.metadata)]

    def load(self,skill_id='evaluar-documento'):
        if skill_id!=self.metadata['id']: raise ValueError('Skill no disponible.')
        raw=(self.folder/'SKILL.md').read_text('utf-8')
        body=raw.split('---',2)[2].strip()
        return {**self.metadata,'instructions':body,'sha256':hashlib.sha256(raw.encode()).hexdigest()}
