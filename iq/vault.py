"""API key storage: Windows DPAPI, owner-only file on other systems."""
import ctypes
import os
from pathlib import Path


def protect(data, decrypt=False):
    if os.name!='nt':return data
    from ctypes import wintypes
    class Blob(ctypes.Structure):
        _fields_=[('size',wintypes.DWORD),('data',ctypes.POINTER(ctypes.c_ubyte))]
    buf=ctypes.create_string_buffer(data)
    source=Blob(len(data),ctypes.cast(buf,ctypes.POINTER(ctypes.c_ubyte)));target=Blob()
    function=ctypes.windll.crypt32.CryptUnprotectData if decrypt else ctypes.windll.crypt32.CryptProtectData
    if not function(ctypes.byref(source),None,None,None,None,1,ctypes.byref(target)):
        raise OSError('Windows no pudo acceder a la clave protegida.')
    try:return ctypes.string_at(target.data,target.size)
    finally:ctypes.windll.kernel32.LocalFree(target.data)


class Vault:
    def __init__(self,directory):self.path=Path(directory)/'gemini.key'
    def get(self):
        if not self.path.exists():return ''
        return protect(self.path.read_bytes(),True).decode('utf-8')
    def set(self,key):
        if not key:
            self.path.unlink(missing_ok=True);return
        temp=self.path.with_suffix('.tmp')
        fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
        with os.fdopen(fd,'wb') as f:f.write(protect(key.encode('utf-8')))
        os.replace(temp,self.path)
