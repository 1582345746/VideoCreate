"""Validate and render the planning document; no product/provider operations."""
from collections import Counter
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PLAN = ROOT / 'docs/20261120-integrated-development-checklist.json'
REPORT = ROOT / 'docs/20261120-integrated-development-checklist.zh-CN.md'
CHECK = ROOT / 'docs/20261120-integrated-development-checklist.validation.json'


def read(relative):
    return json.loads((ROOT / relative).read_text(encoding='utf-8-sig'))


def sha(relative):
    return hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()


def cell(value):
    return str(value).replace('|', '\\|').replace('\n', '<br>')


def build():
    plan = json.loads(PLAN.read_text(encoding='utf-8'))
    tasks = {item['id']: item for item in plan['tasks']}
    assert len(tasks) == len(plan['tasks']), 'Duplicate task ID'
    modules = {item['id']: item for item in plan['modules']}
    phases = {item['id']: item for item in plan['phases']}
    assert len(modules) == 12 and len(plan['workflows']) == 6
    assert set(item['module'] for item in tasks.values()) == set(modules) | {'Q'}
    visiting, visited = set(), set()

    def visit(identity):
        assert identity in tasks, 'Unknown dependency: ' + identity
        assert identity not in visiting, 'Dependency cycle: ' + identity
        if identity in visited:
            return
        visiting.add(identity)
        item = tasks[identity]
        assert item['phase'] in phases
        assert item['priority'] in plan['priority_definitions']
        assert item['status'] in plan['status_definitions']
        assert item['remaining_work'] and item['acceptance'] and item['baseline']
        for dependency in item['depends_on']:
            visit(dependency)
        visiting.remove(identity)
        visited.add(identity)

    for identity in tasks:
        visit(identity)
    for target in plan.get('release_targets', {}).values():
        assert set(target['required_tasks']) <= set(tasks)
    def ancestors(identity):
        result = {identity}
        for dependency in tasks[identity]['depends_on']:
            result |= ancestors(dependency)
        return result
    core = {key for key, item in tasks.items() if item['lane'] == 'main'
            and item['phase'] in {'S0', 'S1', 'S2', 'S3'}}
    assert core <= ancestors('Q03'), 'Core integration not covered by regression gate'
    for module in modules.values():
        for relative in module['source_paths']:
            assert (ROOT / relative).exists(), 'Missing source location: ' + relative

    old_source = 'docs/20261113-development-plan-v2.json'
    remake_source = 'docs/20261120-reference-remake-development-checklist.json'
    original, remake = read(old_source), read(remake_source)
    old_ids = {row['id'] for row in original['work_packages']}
    remake_ids = {row['id'] for row in remake['tasks']}
    web_ids = {row['id'] for row in original['web_subitems']}
    assert len(old_ids) == 73 and len(remake_ids) == 14 and len(web_ids) == 22
    assert set(plan['legacy_owner_map']) == old_ids
    assert set(plan['reference_remake_owner_map']) == remake_ids
    assert set(plan['web_owner_map']) == web_ids
    for field in ('legacy_owner_map', 'reference_remake_owner_map', 'web_owner_map'):
        assert set(plan[field].values()) <= set(tasks), field
    for item in tasks.values():
        assert set(item['legacy_refs']) <= old_ids | remake_ids

    # Capture original statuses once. Subsequent render runs do not rewrite history.
    if 'source_snapshots' not in plan:
        plan['source_snapshots'] = [{'path': p, 'sha256': sha(p)} for p in plan['sources']]
        plan['legacy_mapping'] = []
        for row in original['work_packages']:
            owner = plan['legacy_owner_map'][row['id']]
            plan['legacy_mapping'].append({
                'old_id': row['id'], 'source': old_source, 'old_status': row['status'],
                'old_requirement': row['requirement'],
                'old_remaining': row.get('remaining'), 'old_acceptance': row.get('acceptance'),
                'primary_task': owner,
                'related_tasks': [i['id'] for i in tasks.values() if row['id'] in i['legacy_refs'] and i['id'] != owner],
                'disposition': '复用已有实现；完成新范围与原剩余要求的适用部分，不将旧状态改成通过。'})
        plan['reference_remake_mapping'] = [
            {'old_id': row['id'], 'source': remake_source, 'old_status': row['status'],
             'title': row['title'], 'old_acceptance': row['acceptance'],
             'primary_task': plan['reference_remake_owner_map'][row['id']],
             'related_tasks': [i['id'] for i in tasks.values() if row['id'] in i['legacy_refs']
                               and i['id'] != plan['reference_remake_owner_map'][row['id']]],
             'note': '旧文件是审计当时的状态；R01 后来有局部未发布修改，以 M06-01 当前说明为准。'}
            for row in remake['tasks']]
        plan['web_carry_forward'] = [
            {'old_id': row['id'], 'source': old_source, 'title': row['title'],
             'recorded_status': row['status'], 'primary_task': plan['web_owner_map'][row['id']],
             'acceptance': row['acceptance'], 'evidence': row.get('implementation_evidence', []),
             'policy': '保留候选及原证据；仅处理适用维护／验收；不扩展生产 Web。'}
            for row in original['web_subitems']]
        plan['web_remaining_notes'] = [
            'W10：新型号／新操作仅在合同明确时维护；不靠收费 POST 猜协议。',
            'W11：已有图片／视频计费复用；token／分钟等新单位按实际合同需要另验，实付未知仍未知。',
            'W17：保留草稿恢复边界；没有新的故障证据不反复扩大草稿工程。',
            'W19：2026-11-14 记录有 170 条旧项目／修订身份仍歧义；这是历史统计，不能猜原账户或据此改写快照。',
            'W20：素材服务与配置服务独立；旧 PID／端口仅作历史记录，不自动停启或迁移。',
            'W21：自动化已有证据；本机真人任务／读屏验收继续单列，不能由自动化代签。',
            'W22：候选构建／本机维护已有证据；干净 Windows 和正式采用仍需实际记录。']

    assert {x['old_id'] for x in plan['legacy_mapping']} == old_ids
    assert {x['old_id'] for x in plan['reference_remake_mapping']} == remake_ids
    assert {x['old_id'] for x in plan['web_carry_forward']} == web_ids
    changed_sources = [s['path'] for s in plan['source_snapshots'] if sha(s['path']) != s['sha256']]
    assert not changed_sources, 'Planning source changed; explicitly revise snapshots: ' + str(changed_sources)
    counts = dict(Counter(item['module'] for item in tasks.values()))
    phase_counts = dict(Counter(item['phase'] for item in tasks.values()))
    plan['counts'] = {'tasks': len(tasks), 'module_tasks': sum(counts.get(m, 0) for m in modules),
        'engineering_tasks': counts['Q'], 'by_module': counts, 'by_phase': phase_counts,
        'by_lane': dict(Counter(item['lane'] for item in tasks.values())),
        'legacy_packages_mapped': len(old_ids), 'reference_items_mapped': len(remake_ids),
        'web_subitems_carried': len(web_ids), 'acceptance_cases': len(plan['acceptance_cases'])}
    plan['live_test_policy'] = [
        '用户对必要上游访问／测试的授权继续有效；当前仅计划，不执行。',
        '先读取已有合同和回执，恢复或复用已生成素材；不会为了更新清单重生历史样片。',
        '先只读合同／目录和参考传输检查，再为仍不确定的输入组合或质量问题设计最小生成样本。',
        '每个问题先一条有明确验收目标的样本，记录预计费用、请求限额和停止条件；结果不明先恢复原任务。',
        '分别检查发送成功、生成成功、音色／动作／口型实际达标，三个结论不能合并。',
        '若现有授权、预算或协议不足以继续，具体说明缺口；不对已授权的同一步骤反复索要许可。']
    PLAN.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    lines = [
        '# VideoCreate 最新完整开发清单', '',
        '日期：2026-11-20（Asia/Shanghai） · 版本：框架整合计划 r1 · 状态：仅规划，开发暂停。', '',
        '**6 类主要制作流程、12 个共用模块、84 个工作项：75 项能力整合 + 9 项测试与交付。**', '',
        '84 是本次可验收工作项数量，包含复用、补验与开发，不代表 84 项全新功能，也不与原 73 项、R01–R14 或 Web W01–W22 相加。'
        '三个可选扩展、严格控制路线及干净环境验证有独立范围；不会阻止常用主线在本机完善。', '',
        '本文件由同名 JSON 生成；每项有依赖和验收，旧清单原始要求／状态保存在 JSON。框架依据：'
        '[整体框架](20261120-skill-framework-proposal.zh-CN.md)。', '',
        '## 当前基线与状态', '',
        '- 已安装标签 dev43；F 盘源码标签 dev44，未发布。保留 C 盘配置／凭据和全部未提交工作。',
        '- 声音与嘴部控制有局部源码修改：此前 6 项新专项及 40 项动画回归通过；尚未按完整声音方案验收、全回归或安装。',
        '- Web 已有候选和历史验证，不再按“全部未开发”重做；真人／读屏、干净环境和旧任务歧义继续单列。',
        '- 本轮仅更新计划：产品源码修改 0、上游调用 0、付费生成 0、安装 0。', '',
        '状态“计划整合”表示新范围尚未验收；“局部修改、暂停未发布”仅用于 M06-01。已有底座不等于整体完成。', '',
        '## 约束', '']
    lines += ['- ' + value for value in plan['constraints']]
    lines += ['', '## 执行批次与交付结果', '', '| 批次 | 工作项数 | 结果 | 退出条件 |', '|---|---:|---|---|']
    for phase in plan['phases']:
        lines.append('| ' + ' | '.join(cell(v) for v in (phase['id'] + ' ' + phase['title'],
            phase_counts.get(phase['id'], 0), phase['outcome'], phase['gate'])) + ' |')
    lines += ['', '每个实现项都随改动运行适用测试；S4 是集成验收，不表示开发前几批不测试。'
        '阶段内按依赖先做最小纵向链：单人参考换角 → 请求／恢复 → 静音交付 → 对照审片，再扩到多人。'
        'S2 的严格路线评估可得出“当前未支持”，但不能把未实现的严格控制记为已交付。', '',
        'P0：主线正确性与交付；P1：质量与流程完善；P2：条件性验证／可选扩展。优先级不替代依赖顺序。', '',
        '## 六类流程覆盖', '', '| 流程 | 验收结果 |', '|---|---|']
    for workflow in plan['workflows']:
        lines.append('| ' + cell(workflow['id'] + ' ' + workflow['title']) + ' | ' + cell(workflow['acceptance']) + ' |')
    lines += ['', 'W1–W6 是制作流程；历史 Web W01–W22 是配置子项，编号空间不同。'
        '声音版本、系列和精度是组合选项；不要求纯图片项目执行对白或视频审核。', '',
        '## 12 个模块的逐项清单', '']
    for module_id in list(modules) + ['Q']:
        if module_id == 'Q':
            title, baseline = '工程测试与交付', '历史证据按原版本保留；新源码、新协议或新交付范围需要自己的验证。'
        else:
            title, baseline = modules[module_id]['title'], modules[module_id]['baseline']
        lines += ['### ' + module_id + ' ' + title + '（' + str(counts[module_id]) + ' 项）', '',
                  '**已有基础：**' + baseline + '。', '']
        if module_id == 'M06':
            lines += ['**声音范围：**无声动作、无声对口型、对白、音乐、对白＋音乐；独立控制环境音与拟音。'
                '复刻声音必须提取实际音轨，混有音乐时按需分离人声，再将音频作为真实参考发给支持的上游。'
                '声音参考、最终声音和可见口型分别管理。', '']
        lines += ['| ID／优先级／批次 | 开发与整合内容 | 验收标准 | 依赖 |', '|---|---|---|---|']
        for item in tasks.values():
            if item['module'] != module_id:
                continue
            label = item['id'] + ' · ' + item['priority'] + ' · ' + item['phase']
            if item['status'] == 'paused-partial-unreleased':
                label += '（局部修改，暂停未发布）'
            if item['lane'] == 'conditional':
                label += '（条件性）'
            values = (label, '**' + item['title'] + '**：' + item['remaining_work'],
                      item['acceptance'], '、'.join(item['depends_on']) or '无')
            lines.append('| ' + ' | '.join(cell(v) for v in values) + ' |')
        lines.append('')

    lines += ['## 17 组实际需求验收样例', '',
        '这些是待验证的验收场景，优先复用现有素材和本地模拟；不代表要新增 17 次付费生成。'
        '每项分开记录结构、输入传输、实际画面、听审和用户采用。动作／口型误差按具体用途定义，不能统一冒称帧级保证。', '',
        '| 编号 | 场景 | 必查结果 |', '|---|---|---|']
    for case in plan['acceptance_cases']:
        lines.append('| ' + ' | '.join(cell(v) for v in (case['id'], case['title'], case['acceptance'])) + ' |')
    lines += ['', '## 必要上游测试策略', '']
    lines += ['- ' + p for p in plan['live_test_policy']]
    lines += ['', '## 原 73 项的完整归属', '',
        '原要求、旧剩余和旧验收已完整保存在 JSON；以下列主要归属。相关模块共同落实，归属不代表该旧项已通过。', '',
        '| 原项 | 原记录状态 | 主要归属 | 其他关联 |', '|---|---|---|---|']
    for row in plan['legacy_mapping']:
        lines.append('| ' + ' | '.join(cell(v) for v in (row['old_id'], row['old_status'], row['primary_task'],
            '、'.join(row['related_tasks']) or '—')) + ' |')
    lines += ['', '## R01–R14 的归属', '', '| 原项 | 主题 | 主要归属 | 其他关联 |', '|---|---|---|---|']
    for row in plan['reference_remake_mapping']:
        lines.append('| ' + ' | '.join(cell(v) for v in (row['old_id'], row['title'], row['primary_task'],
            '、'.join(row['related_tasks']) or '—')) + ' |')
    lines += ['', '## 历史 Web W01–W22：维护与发行轨', '',
        '这些是旧候选状态的保留记录，本轮没有重新运行它们。源码相关改动才触发适用回归。'
        '本机人工验收与干净机器验收分开，等待外部条件时继续制作主线。', '',
        '| 原项 | 范围 | 当前计划归属 |', '|---|---|---|']
    for row in plan['web_carry_forward']:
        lines.append('| ' + ' | '.join(cell(v) for v in (row['old_id'], row['title'], row['primary_task'])) + ' |')
    lines += ['', '旧 Web 重点剩余：', '']
    lines += ['- ' + value for value in plan['web_remaining_notes']]
    lines += ['', '## 分开管理的交付范围', '', '| 范围 | 前置验收 | 可以声明什么 |', '|---|---|---|']
    target_names = {'local_candidate': '本机候选', 'local_adoption': '本机采用',
        'portable_distribution': '可跨机发行', 'strict_motion_or_lipsync': '严格动作／口型能力'}
    for key, target in plan.get('release_targets', {}).items():
        lines.append('| ' + ' | '.join(cell(v) for v in (target_names[key],
            '、'.join(target['required_tasks']), target['claim'])) + ' |')
    lines += ['', '## 完成口径', '']
    lines += ['- ' + value for value in plan['completion_rules']]
    lines += ['', '每轮交付至少包含：已完成项、实际修改与版本、验证方法、真实素材结果、'
        '剩余缺口、下一批依赖。没有来源或实际审听证据的能力保持未核实。', '',
        '## 规划核对', '',
        '计划结构校验检查唯一编号、依赖无环、源路径、73＋14＋22 项映射与原文快照。'
        '它只证明清单完整一致，不证明产品实现或视频效果通过。', '',
        '生成器：`docs/prototypes/build-integrated-checklist-20261120.py`。', '']
    REPORT.write_text('\n'.join(lines), encoding='utf-8')
    result = {'date': plan['date'], 'ok': True, 'validation_scope': 'planning-structure-only',
        **plan['counts'], 'unique_ids': True, 'acyclic_dependencies': True,
        'core_tasks_covered_by_regression_gate': True,
        'source_paths_exist': True, 'source_snapshots_match': True,
        'product_tests_run': 0, 'provider_calls': 0, 'paid_generations': 0,
        'plan_sha256': sha(PLAN.relative_to(ROOT)), 'markdown_sha256': sha(REPORT.relative_to(ROOT)),
        'note': 'No implementation, media quality, live acceptance or release claim.'}
    CHECK.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    build()
