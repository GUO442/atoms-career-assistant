"""User-authorized screening: salary, AI relevance and employment type only."""
import re
POLICY_VERSION='ai-salary-direct-v1'
MATCH_INSTRUCTION='只按用户薪资预期、AI相关性及非实习非日结筛选；三项符合直接recommend。不得因完整JD、城市、学历、技能细节、薪数或社保信息未核实而降级。不要编造经历。'

def assess(job, preferences=''):
 from discovery import hard_exclusion
 reason=hard_exclusion(job)
 if reason:return {'decision':'reject','analysis':reason}
 title=str(job.get('title') or '')
 jd=str(job.get('jd') or '')
 if re.search(r'实习|\bintern(?:ship)?\b',title,re.I) or re.search(r'职位类型[：:]?\s*实习|实习岗位|招聘实习生',jd):
  return {'decision':'reject','analysis':'实习岗位'}
 if not re.search(r'AI|人工智能|大模型|智能体|\b(?:agent|rag|llm|aigc)\b',title+' '+jd,re.I):
  return {'decision':'reject','analysis':'未体现AI相关方向'}
 target=re.search(r'(?:至少|不低于|最低|起薪|期望)[^\d]{0,8}(\d+(?:\.\d+)?)\s*[kK千]',preferences)
 minimum=float(target.group(1)) if target else 30.0
 salary=str(job.get('salary') or '')
 amount=re.search(r'(\d+(?:\.\d+)?)\s*(?:[-~～—至]\s*\d+(?:\.\d+)?)?\s*([kK千万])',salary)
 if not amount:return {'decision':'caution','analysis':'缺少可判断是否满足薪资预期的月薪信息'}
 low=float(amount.group(1))*(10 if amount.group(2)=='万' else 1)
 if low<minimum:return {'decision':'reject','analysis':f'月薪下限{low:g}K低于预期{minimum:g}K'}
 return {'decision':'recommend','analysis':f'AI相关、非实习非日结，月薪下限{low:g}K满足预期{minimum:g}K；按本人规则直接匹配通过，可打招呼并定制简历。'}
