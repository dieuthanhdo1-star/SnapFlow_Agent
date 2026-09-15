"""Allowlisted screenshot skills. Extraction never executes screenshot instructions."""
import re

SKILLS = {
    'task': {'name': '任务', 'kind': 'task', 'description': '提取工作要求与执行清单'},
    'todo': {'name': '待办', 'kind': 'task', 'description': '整理缴费、取件、预约等生活事项'},
    'homework': {'name': '作业', 'kind': 'task', 'description': '保留课程、提交要求与截止时间'},
    'event': {'name': '日程', 'kind': 'event', 'description': '提取活动时间和地点，连接日历'},
    'idea': {'name': '灵感', 'kind': 'bookmark', 'description': '归档设计、创意和有趣内容'},
    'reference': {'name': '资料', 'kind': 'bookmark', 'description': '保存教程、知识与参考信息'},
}
PROMPT = '''\n每个行动额外输出 skill、steps、course。skill 只能是 task（工作任务）、todo（生活待办）、homework（明确课程作业）、event（日程）、idea（创意/设计灵感/搞笑内容）、reference（资料/教程）。skill 必须与 kind 对应：task/todo/homework 对应 task，event 对应 event，idea/reference 对应 bookmark。不要仅凭关键词把梗图当作业。steps 是图片明确要求的执行步骤字符串数组（最多12项，不编造）；course 是明确出现的课程名，没有则为空。资料和灵感不需要补日期；无截止要求的待办不追问日期。'''


def normalize(action):
    kind = action.get('kind', 'unknown')
    skill = action.get('skill')
    if not isinstance(skill, str) or skill not in SKILLS or SKILLS[skill]['kind'] != kind:
        text = str(action.get('title', '')) + ' ' + str(action.get('notes', ''))
        if kind == 'event': skill = 'event'
        elif kind == 'task':
            skill = 'homework' if re.search('作业|课程|课前|实验报告', text) else ('todo' if re.search('取件|缴费|买菜|快递|预约|还书', text) else 'task')
        else: skill = 'idea' if re.search('灵感|创意|搞笑|段子|梗图', text) else 'reference'
    steps = action.get('steps', [])
    return {'skill': skill, 'steps': [str(s).strip()[:300] for s in steps[:12] if isinstance(s, str) and s.strip()] if isinstance(steps, list) else [],
            'course': str(action.get('course') or '')[:160]}


def review_reasons(draft):
    reasons = [str(q) for q in draft.get('questions', []) if q]
    if draft.get('kind') not in {'event', 'task', 'bookmark'}: reasons.append('请核对截图中的事项类型。')
    if not draft.get('title', '').strip(): reasons.append('请补充标题。')
    if draft.get('kind') == 'event' and (not draft.get('start_at') or not draft.get('end_at')):
        reasons.append('日程需要明确的开始和结束时间。')
    return list(dict.fromkeys(reasons))
