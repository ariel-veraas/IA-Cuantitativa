"""Local hardware report. No network, file collection, host name or user name."""
import json
import os
import platform
import shutil
import subprocess
import sys


def hardware():
    result={'system':platform.system(),'release':platform.release(),'architecture':platform.machine(),
            'python':platform.python_version(),'logical_cpus':os.cpu_count(),'ram_gib':None,
            'nvidia_gpus':[],'note':'RAM y VRAM totales; no son una medición del consumo del modelo.'}
    try:
        if sys.platform=='win32':
            import ctypes
            class Memory(ctypes.Structure):
                _fields_=[('length',ctypes.c_ulong),('load',ctypes.c_ulong)]+[(n,ctypes.c_ulonglong) for n in ('total','available','page_total','page_available','virtual_total','virtual_available','extended')]
            info=Memory();info.length=ctypes.sizeof(info)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(info)):result['ram_gib']=round(info.total/1024**3,2)
        elif sys.platform=='darwin':
            result['ram_gib']=round(int(subprocess.check_output(['sysctl','-n','hw.memsize'],timeout=5))/1024**3,2)
        else:result['ram_gib']=round(os.sysconf('SC_PAGE_SIZE')*os.sysconf('SC_PHYS_PAGES')/1024**3,2)
    except (OSError,ValueError,subprocess.SubprocessError,AttributeError):pass
    executable=shutil.which('nvidia-smi')
    if executable:
        try:
            output=subprocess.check_output([executable,'--query-gpu=name,memory.total,driver_version','--format=csv,noheader,nounits'],timeout=5,stderr=subprocess.DEVNULL,text=True)
            result['nvidia_gpus']=[line.strip() for line in output.splitlines() if line.strip()]
        except (OSError,subprocess.SubprocessError):pass
    # A GPU changes the right default a lot: measured on real hardware, the 4B
    # profile answers a document question in ~1s on GPU vs ~8s on CPU, while the
    # 1.7B profile answers in ~3s either way. Without a detected GPU, recommend
    # the profile that does not depend on one.
    result['recommended_profile']='balanced' if result['nvidia_gpus'] else 'light'
    return result


if __name__=='__main__':print(json.dumps(hardware(),ensure_ascii=False,indent=2))
