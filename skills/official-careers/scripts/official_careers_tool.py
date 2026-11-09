import os, sys, json
from pathlib import Path

root = Path(os.environ.get('CAREER_HOME', ''))
if not (root / 'official_careers.py').is_file():
    root = Path(__file__).resolve().parents[3]
if not (root / 'official_careers.py').is_file():
    raise SystemExit('Set CAREER_HOME to the career-assistant folder')
sys.path.insert(0, str(root))
import official_careers


def main(argv):
    if not argv or argv[0] in ('-h', '--help'):
        print('用法: official_careers_tool.py <catalog|search|detail> [--json {...}]')
        print('  catalog                               列出已注册公司')
        print('  search  --json \'{"query":"AI测试","companies":"tencent,bytedance"}\'')
        print('  detail  --json \'{"job_id":"真实岗位ID","platform":"tencent"}\'')
        return 0 if argv else 1
    name = argv[0]
    args = {}
    rest = argv[1:]
    for i, a in enumerate(rest):
        if a == '--json' and i + 1 < len(rest):
            args = json.loads(rest[i + 1])
            break
        if a.startswith('--json='):
            args = json.loads(a[len('--json='):])
            break
    result = official_careers.call(name, args)
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return 0 if result.get('ok') else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
