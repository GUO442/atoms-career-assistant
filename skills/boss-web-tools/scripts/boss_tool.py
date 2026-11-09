import os,runpy
from pathlib import Path
root=Path(os.environ.get('BOSS_ASSISTANT_HOME',''))
if not (root/'boss_tools.py').is_file():root=Path(__file__).resolve().parents[3]
if not (root/'boss_tools.py').is_file():raise SystemExit('Set BOSS_ASSISTANT_HOME to the career-assistant folder')
import sys
sys.path.insert(0,str(root));runpy.run_path(str(root/'boss_tools.py'),run_name='__main__')
