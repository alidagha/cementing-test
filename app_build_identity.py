"""Bind App predictions to the runtime files in a local App extraction."""
from hashlib import sha256
from pathlib import Path


_APP_ROOT = Path(__file__).resolve().parent


def _build_identity(root):
    runtime = [path for path in root.glob('*.py') if not path.name.startswith('test_')]
    runtime.extend(root / name for name in ('ds_cent_products.json', 'master_template.docx', 'requirements.txt'))
    digest = sha256(b'CEMENTING_APP_LOCAL_BUILD_V1\0')
    for path in sorted(runtime, key=lambda item: item.name):
        try:
            contents = path.read_bytes()
        except OSError as exc:
            raise ValueError(f'Cannot read App build file {path.name}. Re-extract the App ZIP.') from exc
        digest.update(path.name.encode('utf-8') + b'\0')
        digest.update(sha256(contents).digest())
    # The geometry and numerical evidence ABI has a 40-hex source slot.
    # This is a domain-separated 160-bit build fingerprint, not a Git SHA.
    return digest.hexdigest()[:40]


try:
    _LOADED_BUILD = _build_identity(_APP_ROOT)
except ValueError:
    _LOADED_BUILD = None


def current_app_build_identity():
    identity = _build_identity(_APP_ROOT)
    if identity != _LOADED_BUILD:
        raise ValueError('CFW128 App build files changed during this process. Re-extract and restart the App.')
    return identity
