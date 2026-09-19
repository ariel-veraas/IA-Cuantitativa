"""Single application owner per data directory, released by the operating system."""
import os
from pathlib import Path


class DataLock:
    def __init__(self, directory):
        directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
        self.file=(directory/'.instance.lock').open('a+b')
        self.file.seek(0,os.SEEK_END)
        if self.file.tell()==0:self.file.write(b'0');self.file.flush()
        self.file.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(self.file.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:
            self.file.close()
            raise ValueError('Ya hay una aplicación usando esta carpeta de datos. Cerrala antes de continuar.') from None

    def close(self):
        if not self.file.closed:
            self.file.seek(0)
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(self.file.fileno(),msvcrt.LK_UNLCK,1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(),fcntl.LOCK_UN)
            self.file.close()
