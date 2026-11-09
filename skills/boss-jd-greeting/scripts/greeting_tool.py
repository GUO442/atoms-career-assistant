import os,runpy,sys
from pathlib import Path
root=Path(os.environ.get('BOSS_ASSISTANT_HOME',''))
if not (root/'greeting_tools.py').is_file():
 hint=Path(__file__).with_name('assistant-root.txt')
 if hint.exists():root=Path(hint.read_text().strip())
if not (root/'greeting_tools.py').is_file():root=Path(__file__).resolve().parents[3]
if not (root/'greeting_tools.py').is_file():raise SystemExit('Set BOSS_ASSISTANT_HOME to the career-assistant workspace')
sys.path.insert(0,str(root));runpy.run_path(str(root/'greeting_tools.py'),run_name='__main__')
