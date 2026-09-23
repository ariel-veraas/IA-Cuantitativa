"""Explicit configuration; secrets never go to browser or SQLite."""
import json
import math
import os
from dataclasses import dataclass, asdict
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent


def loopback_url(url):
    if not isinstance(url, str):
        raise ValueError('La dirección del motor local debe ser texto.')
    p = urlsplit(url)
    if (p.scheme != 'http' or p.hostname not in ('127.0.0.1', 'localhost', '::1')
            or p.username or p.password or p.query or p.fragment or p.path not in ('', '/')):
        raise ValueError('El motor local debe usar http://127.0.0.1:puerto sin rutas ni credenciales.')
    port = p.port or 80
    if not 1 <= port <= 65535:
        raise ValueError('Puerto local inválido.')
    # Canonicalize localhost to avoid DNS resolution and rebinding.
    return f'http://[{p.hostname}]:{port}' if p.hostname == '::1' else f'http://127.0.0.1:{port}'


@dataclass(frozen=True)
class Config:
    local_url: str = 'http://127.0.0.1:8080'
    local_model: str = 'local'
    local_enabled: bool = False
    local_backend: str = 'llamacpp'
    context_tokens: int = 4096
    timeout_seconds: int = 90
    max_context_chars: int = 10000
    max_output_tokens: int = 900
    reasoning_max_output_tokens: int = 1600
    embedding_model: str = ''
    cloud_enabled: bool = False
    web_search_enabled: bool = False
    gemini_model: str = ''
    input_usd_per_million: float = 0.0
    output_usd_per_million: float = 0.0
    monthly_budget_usd: float = 0.0
    per_job_budget_usd: float = 0.0
    pricing_confirmed: bool = False

    def validate(self):
        loopback_url(self.local_url)
        if self.local_backend not in ('llamacpp','ollama'):
            raise ValueError('Motor local desconocido.')
        if type(self.context_tokens) is not int or not 2048<=self.context_tokens<=8192:
            raise ValueError('El contexto local debe estar entre 2048 y 8192 tokens.')
        for name in ('local_enabled', 'cloud_enabled', 'web_search_enabled', 'pricing_confirmed'):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f'{name} debe ser verdadero o falso.')
        for name, lo, hi in [('timeout_seconds',5,300),('max_context_chars',1000,24000),
                             ('max_output_tokens',128,2000),('reasoning_max_output_tokens',128,4000)]:
            v = getattr(self, name)
            if type(v) is not int or not lo <= v <= hi:
                raise ValueError(f'{name} fuera del rango {lo}–{hi}.')
        # Reasoning traces add tokens on top of the answer; bound them but never
        # below the plain-answer budget, or turning reasoning on would truncate replies.
        if self.reasoning_max_output_tokens < self.max_output_tokens:
            raise ValueError('reasoning_max_output_tokens debe ser mayor o igual a max_output_tokens.')
        for name in ('input_usd_per_million','output_usd_per_million','monthly_budget_usd','per_job_budget_usd'):
            v = getattr(self, name)
            if type(v) not in (int,float) or not math.isfinite(v) or v < 0:
                raise ValueError(f'{name} debe ser un número finito no negativo.')
        if not isinstance(self.local_model,str) or not 1 <= len(self.local_model) <= 160:
            raise ValueError('Nombre de modelo local inválido.')
        if not isinstance(self.embedding_model,str) or len(self.embedding_model) > 160:
            raise ValueError('Nombre de modelo de embeddings inválido.')
        if self.cloud_enabled:
            # These documented models support thinkingBudget=0. Fail closed for others.
            if self.gemini_model not in ('gemini-2.5-flash','gemini-2.5-flash-lite'):
                raise ValueError('Esta alfa solo admite Gemini 2.5 Flash o Flash Lite sin thinking. Verificá su disponibilidad.')
            if not self.pricing_confirmed or any(getattr(self,k)<=0 for k in (
                'input_usd_per_million','output_usd_per_million','monthly_budget_usd','per_job_budget_usd')):
                raise ValueError('Gemini necesita tarifas verificadas y presupuestos positivos.')
        elif self.web_search_enabled:
            raise ValueError('La búsqueda web necesita Gemini habilitado.')
        return self

    def public(self):
        return asdict(self)


def load_config(path=None):
    p = Path(path or os.environ.get('IQ_CONFIG', ROOT/'config.json'))
    data = json.loads(p.read_text('utf-8')) if p.exists() else {}
    if not isinstance(data,dict) or set(data) - set(Config.__dataclass_fields__):
        raise ValueError('config.json contiene campos desconocidos.')
    return Config(**data).validate()
