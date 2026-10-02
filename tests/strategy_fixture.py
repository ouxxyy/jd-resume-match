"""结构/引用负例的合成夹具；业务分析验收另用真实模型产物。"""
import copy,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]


def fixture():
    p=ROOT/'examples/strategy-upgrade/education-first-work'
    report=json.loads((p/'report.json').read_text())
    ed=json.loads((p/'editorial-base.json').read_text())
    evs={x['quote']:x['evidence_id'] for x in report['evidence']}
    inventory=[];section=None;entry=None;orders={}; kinds={'教育背景':'education','工作经历':'work','技能清单':'skills'}
    def add(kind,raw,parent,entry_kind=None):
        iid='item-test-'+str(len(inventory)+1);orders[parent]=orders.get(parent,0)+1
        x={'item_id':iid,'kind':kind,'parent_id':parent,'original_order':orders[parent],'label':raw,'raw_quote':raw,'evidence_ids':[evs[raw]],'req_ids':[],'disposition':'keep','rationale':'保留已有事实，按目标岗位安排位置。'}
        if entry_kind:x['entry_kind']=entry_kind
        inventory.append(x);return iid
    for line in (p/'resume.md').read_text().splitlines():
        if line.startswith('## '):
            sec_label=line[3:];section=add('section',sec_label,None);entry=None
        elif section and line.startswith('- '):add('bullet',line[2:],entry)
        elif section and line.strip():entry=add('entry',line,section,kinds[sec_label])
    items={x['item_id']:x for x in inventory}
    def claim(text='这里缺少结果记录，需要核实。',basis='question',ids=None,reqs=None,ev=None):
        return {'text':text,'basis':basis,'req_ids':reqs or [],'evidence_ids':ev or [],'answer_ids':[],'item_ids':ids or []}
    blueprint=[]
    sections=[x for x in inventory if x['kind']=='section']
    for sec in [sections[1],sections[0],sections[2]]:
        entries=[]
        for e in inventory:
            if e['parent_id']==sec['item_id']:
                entries.append({'entry_id':e['item_id'],'rationale':'按相关性展示，保留任职信息。','bullet_ids':[b['item_id'] for b in inventory if b['parent_id']==e['item_id']]})
        blueprint.append({'section_id':sec['item_id'],'rationale':'核心岗位证据靠前，资格信息仍完整。','entries':entries})
    revisions=[]
    for rw in report['rewrites']:
        bullet=next(x for x in inventory if x['kind']=='bullet' and rw['original_quote'] in x['raw_quote'])
        revisions.append({'order':len(revisions)+1,'change':'调整条目信息顺序，保留事实归属。','location_item_ids':[bullet['item_id']],'impact':claim('已有具体行动，优先让读者看到。','fact',[bullet['item_id']],ev=bullet['evidence_ids']),'rewrite_ids':[rw['rewrite_id']]})
    work=next(x for x in inventory if x.get('entry_kind')=='work')
    insight={'entry_id':work['item_id'],**{f:claim(ids=[work['item_id']]) for f in ['problem','role','actions','outputs','changes','skills','impact']}}
    strategy={'job_id':report['primary_job_id'],'order_basis':'extracted_text','inventory':inventory,'job_focus':[{'concept':r['text'],'req_ids':[r['req_id']],'jd_quote':r['jd_quote'],'business_problem':claim('岗位可能需要稳定交付相关工作。','inference',reqs=[r['req_id']])} for r in report['requirements']],'blueprint':blueprint,'experience_insights':[insight],'recruiter_review':{'first_impression':[],'buried_evidence':[],'generic_statements':[],'concerns':[]},'ats_review':{'keywords':[],'readability':[],'format_status':'text_only','format_observations':[]},'revision_priorities':revisions,'missing_facts':[],'answer_links':[]}
    ed['resume_strategy']=strategy
    return report,ed
