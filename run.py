import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'vendor'))
from iq.server import main

if __name__ == '__main__':
    main()
